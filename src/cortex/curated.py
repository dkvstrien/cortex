"""Curated memory layer: remember and recall via FTS5 search."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


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

    return [
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
