"""Curated memory layer: remember, recall, forget, supersede, and history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from cortex.decay import reinforce


def remember(
    conn: sqlite3.Connection,
    content: str,
    *,
    type: str = "fact",
    source: str | None = None,
    tags: list[str] | None = None,
    confidence: float = 1.0,
    supersedes_id: int | None = None,
) -> int:
    """Store a curated memory and return its integer ID.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    content:
        The memory text to store.
    type:
        One of: decision, preference, procedure, entity, fact, idea.
    source:
        Where the memory came from (e.g. 'manual', 'session:123').
    tags:
        List of tag strings. Stored as a JSON array; indexed in FTS5.
    confidence:
        Confidence score 0.0-1.0 (default 1.0).
    supersedes_id:
        If this memory replaces an older one, the ID of the old memory.
    """
    tags_json = json.dumps(tags or [])
    cursor = conn.execute(
        """
        INSERT INTO curated_memories (content, type, source, tags, confidence, supersedes_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (content, type, source, tags_json, confidence, supersedes_id),
    )
    conn.commit()
    return cursor.lastrowid


def recall_curated(
    conn: sqlite3.Connection,
    query: str,
    *,
    type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search curated memories via FTS5 with BM25 ranking.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    query:
        Free-text search query. Each term is automatically expanded with
        a prefix wildcard for partial matching.
    type:
        If set, only return memories of this type.
    limit:
        Maximum number of results (default 10).

    Returns
    -------
    List of dicts with keys: id, content, type, source, tags, confidence,
    rank, created_at. Results are ordered by BM25 relevance (best first).
    """
    # Build prefix query: "database preference" -> "database* OR preference*"
    terms = query.strip().split()
    fts_query = " OR ".join(f"{term}*" for term in terms) if terms else query

    # Build WHERE clause
    params: list[Any] = [fts_query]
    type_filter = ""
    if type is not None:
        type_filter = "AND cm.type = ?"
        params.append(type)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT
            cm.id,
            cm.content,
            cm.type,
            cm.source,
            cm.tags,
            cm.confidence,
            bm25(curated_memories_fts) AS rank,
            cm.created_at
        FROM curated_memories_fts fts
        JOIN curated_memories cm ON cm.id = fts.rowid
        WHERE curated_memories_fts MATCH ?
            AND cm.deleted_at IS NULL
            AND cm.id NOT IN (
                SELECT supersedes_id FROM curated_memories
                WHERE supersedes_id IS NOT NULL
            )
            {type_filter}
        ORDER BY rank
        LIMIT ?
        """,
        params,
    ).fetchall()

    results = [
        {
            "id": row[0],
            "content": row[1],
            "type": row[2],
            "source": row[3],
            "tags": json.loads(row[4]) if row[4] else [],
            "confidence": row[5],
            "rank": row[6],
            "created_at": row[7],
        }
        for row in rows
    ]

    # Auto-reinforce returned results: reset confidence to 1.0 and refresh updated_at
    for result in results:
        reinforce(conn, result["id"])
        result["confidence"] = 1.0

    return results


def forget(conn: sqlite3.Connection, memory_id: int) -> None:
    """Soft-delete a curated memory by setting deleted_at.

    Also removes the memory from the FTS5 index so it no longer
    appears in search results.

    Raises
    ------
    KeyError
        If no memory with the given ID exists.
    """
    row = conn.execute(
        "SELECT id, content, type, tags FROM curated_memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"No curated memory with id={memory_id}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute(
        "UPDATE curated_memories SET deleted_at = ? WHERE id = ?",
        (now, memory_id),
    )
    # Remove from FTS5 index so it won't match searches
    conn.execute(
        "INSERT INTO curated_memories_fts(curated_memories_fts, rowid, content, type, tags) "
        "VALUES ('delete', ?, ?, ?, ?)",
        (row[0], row[1], row[2], row[3]),
    )
    conn.commit()


def supersede(
    conn: sqlite3.Connection,
    old_id: int,
    new_content: str,
    *,
    type: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
    confidence: float = 1.0,
) -> int:
    """Replace an existing curated memory with a new one.

    Creates a new memory whose supersedes_id points to *old_id*, then
    soft-deletes the old memory.  By default the new memory inherits
    type, source, and tags from the old one unless explicitly overridden.

    Returns the ID of the new memory.

    Raises
    ------
    KeyError
        If no memory with *old_id* exists.
    """
    old = conn.execute(
        "SELECT type, source, tags FROM curated_memories WHERE id = ?",
        (old_id,),
    ).fetchone()
    if old is None:
        raise KeyError(f"No curated memory with id={old_id}")

    new_type = type if type is not None else old[0]
    new_source = source if source is not None else old[1]
    new_tags = tags if tags is not None else (json.loads(old[2]) if old[2] else [])

    new_id = remember(
        conn,
        new_content,
        type=new_type,
        source=new_source,
        tags=new_tags,
        confidence=confidence,
        supersedes_id=old_id,
    )
    forget(conn, old_id)
    return new_id


def get_history(conn: sqlite3.Connection, memory_id: int) -> list[dict[str, Any]]:
    """Return the full supersession chain for a memory.

    Walks backwards from *memory_id* via supersedes_id links, collecting
    every ancestor.  The returned list is ordered newest-first (the
    given memory_id is at index 0).

    Raises
    ------
    KeyError
        If no memory with the given ID exists.
    """
    chain: list[dict[str, Any]] = []
    current_id: int | None = memory_id

    while current_id is not None:
        row = conn.execute(
            "SELECT id, content, type, source, tags, confidence, created_at, "
            "deleted_at, supersedes_id FROM curated_memories WHERE id = ?",
            (current_id,),
        ).fetchone()
        if row is None:
            if not chain:
                raise KeyError(f"No curated memory with id={memory_id}")
            break

        chain.append(
            {
                "id": row[0],
                "content": row[1],
                "type": row[2],
                "source": row[3],
                "tags": json.loads(row[4]) if row[4] else [],
                "confidence": row[5],
                "created_at": row[6],
                "deleted_at": row[7],
                "supersedes_id": row[8],
            }
        )
        current_id = row[8]  # follow the chain

    return chain
