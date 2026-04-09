"""Browse commands: list, search, show — read-only views of curated memories."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _snippet(text: str, max_len: int = 60) -> str:
    """Return a short snippet of text, truncated with ... if needed."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _fmt_confidence(c: float) -> str:
    return f"{c:.2f}"


def list_memories(
    conn: sqlite3.Connection,
    *,
    type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent non-deleted curated memories, ordered by created_at DESC."""
    params: list[Any] = []
    type_clause = ""
    if type is not None:
        type_clause = "AND type = ?"
        params.append(type)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, content, type, source, tags, confidence, created_at
        FROM curated_memories
        WHERE deleted_at IS NULL
        {type_clause}
        ORDER BY created_at DESC
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
            "created_at": row[6],
        }
        for row in rows
    ]


def print_list(memories: list[dict[str, Any]]) -> None:
    """Print memories as a human-readable numbered table."""
    if not memories:
        print("No memories found.")
        return

    # Determine column widths
    id_w = max(len(str(m["id"])) for m in memories)
    id_w = max(id_w, 2)
    type_w = max(len(m["type"]) for m in memories)
    type_w = max(type_w, 4)
    conf_w = 6

    header = (
        f"{'#':>3}  "
        f"{'ID':<{id_w}}  "
        f"{'TYPE':<{type_w}}  "
        f"{'CONF':>{conf_w}}  "
        f"CONTENT"
    )
    print(header)
    print("-" * len(header))

    for i, m in enumerate(memories, 1):
        snippet = _snippet(m["content"], 60)
        print(
            f"{i:>3}  "
            f"{m['id']:<{id_w}}  "
            f"{m['type']:<{type_w}}  "
            f"{_fmt_confidence(m['confidence']):>{conf_w}}  "
            f"{snippet}"
        )


def search_memories(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Run FTS5 search and return ranked results (delegates to recall_curated)."""
    from cortex.curated import recall_curated
    return recall_curated(conn, query, limit=limit)


def print_search(results: list[dict[str, Any]], query: str) -> None:
    """Print search results with rank scores."""
    if not results:
        print(f"No results for: {query!r}")
        return

    print(f"Results for: {query!r}  ({len(results)} found)")
    print()

    # BM25 scores are negative (lower = better match in SQLite FTS5)
    for i, r in enumerate(results, 1):
        score = r.get("rank", 0.0)
        snippet = _snippet(r["content"], 70)
        print(f"{i:>3}.  [{r['id']}] {r['type']}  score={score:.4f}")
        print(f"      {snippet}")
        if r.get("tags"):
            print(f"      tags: {', '.join(r['tags'])}")
        print()


def get_memory(conn: sqlite3.Connection, memory_id: int) -> dict[str, Any] | None:
    """Fetch a single memory by ID (including deleted ones for show command)."""
    row = conn.execute(
        """
        SELECT id, content, type, source, tags, confidence,
               created_at, updated_at, deleted_at, supersedes_id
        FROM curated_memories WHERE id = ?
        """,
        (memory_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "content": row[1],
        "type": row[2],
        "source": row[3],
        "tags": json.loads(row[4]) if row[4] else [],
        "confidence": row[5],
        "created_at": row[6],
        "updated_at": row[7],
        "deleted_at": row[8],
        "supersedes_id": row[9],
    }


def get_superseded_by(conn: sqlite3.Connection, memory_id: int) -> list[dict[str, Any]]:
    """Return memories that supersede the given memory_id (newer ones pointing at it)."""
    rows = conn.execute(
        """
        SELECT id, content, type, confidence, created_at, deleted_at
        FROM curated_memories WHERE supersedes_id = ?
        """,
        (memory_id,),
    ).fetchall()
    return [
        {
            "id": row[0],
            "content": row[1],
            "type": row[2],
            "confidence": row[3],
            "created_at": row[4],
            "deleted_at": row[5],
        }
        for row in rows
    ]


def print_show(conn: sqlite3.Connection, memory_id: int) -> bool:
    """Print full memory details + supersession chain. Returns False if not found."""
    mem = get_memory(conn, memory_id)
    if mem is None:
        print(f"No memory with id={memory_id}")
        return False

    status_str = "DELETED" if mem["deleted_at"] else "active"

    print(f"Memory #{mem['id']}  [{status_str}]")
    print("=" * 60)
    print(f"Content   : {mem['content']}")
    print(f"Type      : {mem['type']}")
    print(f"Source    : {mem['source'] or '(none)'}")
    print(f"Tags      : {', '.join(mem['tags']) if mem['tags'] else '(none)'}")
    print(f"Confidence: {_fmt_confidence(mem['confidence'])}")
    print(f"Created   : {mem['created_at']}")
    print(f"Updated   : {mem['updated_at'] or '(never)'}")
    if mem["deleted_at"]:
        print(f"Deleted   : {mem['deleted_at']}")

    # Supersession chain: what this memory replaced
    if mem["supersedes_id"] is not None:
        print()
        print("Supersession chain (this memory replaced):")
        from cortex.curated import get_history
        chain = get_history(conn, memory_id)
        # chain[0] is the current memory; chain[1:] are predecessors
        for ancestor in chain[1:]:
            deleted_mark = " [DELETED]" if ancestor["deleted_at"] else ""
            print(f"  <- #{ancestor['id']}{deleted_mark}: {_snippet(ancestor['content'], 55)}")
            print(f"     created {ancestor['created_at']}")

    # Memories that supersede THIS one (newer memories pointing here)
    superseded_by = get_superseded_by(conn, memory_id)
    if superseded_by:
        print()
        print("Superseded by (newer memories that replaced this):")
        for newer in superseded_by:
            deleted_mark = " [DELETED]" if newer["deleted_at"] else ""
            print(f"  -> #{newer['id']}{deleted_mark}: {_snippet(newer['content'], 55)}")
            print(f"     created {newer['created_at']}")

    return True
