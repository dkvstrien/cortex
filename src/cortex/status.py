"""Status and health dashboard for Cortex."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


def status(conn: sqlite3.Connection, db_path: str | Path) -> dict[str, Any]:
    """Return a health dashboard dict for the Cortex database.

    Keys returned:
        curated_count: number of non-deleted curated memories
        raw_count: number of raw chunks
        by_type: dict mapping memory type -> count (non-deleted)
        by_source: dict mapping source_type -> count
        last_memory_at: most recent created_at from curated_memories (or None)
        last_consolidation_at: value from meta table (or None)
        db_size_mb: database file size in megabytes
        stale_count: curated memories with confidence < 0.1 and not deleted
        integrity: dict with FTS and vec index consistency checks
    """
    db_path = Path(db_path)

    # Curated count (non-deleted)
    curated_count = conn.execute(
        "SELECT COUNT(*) FROM curated_memories WHERE deleted_at IS NULL"
    ).fetchone()[0]

    # Raw count
    raw_count = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]

    # By type
    rows = conn.execute(
        "SELECT type, COUNT(*) FROM curated_memories "
        "WHERE deleted_at IS NULL GROUP BY type"
    ).fetchall()
    by_type = {row[0]: row[1] for row in rows}

    # By source
    rows = conn.execute(
        "SELECT source_type, COUNT(*) FROM raw_chunks GROUP BY source_type"
    ).fetchall()
    by_source = {row[0]: row[1] for row in rows}

    # Last memory timestamp
    row = conn.execute(
        "SELECT MAX(created_at) FROM curated_memories WHERE deleted_at IS NULL"
    ).fetchone()
    last_memory_at = row[0] if row else None

    # Last consolidation timestamp from meta table
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'last_consolidation_at'"
    ).fetchone()
    last_consolidation_at = row[0] if row else None

    # DB file size
    db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 4)

    # Stale count
    stale_count = conn.execute(
        "SELECT COUNT(*) FROM curated_memories "
        "WHERE confidence < 0.1 AND deleted_at IS NULL"
    ).fetchone()[0]

    # Integrity checks
    integrity = _check_integrity(conn)

    return {
        "curated_count": curated_count,
        "raw_count": raw_count,
        "by_type": by_type,
        "by_source": by_source,
        "last_memory_at": last_memory_at,
        "last_consolidation_at": last_consolidation_at,
        "db_size_mb": db_size_mb,
        "stale_count": stale_count,
        "integrity": integrity,
    }


def _check_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    """Check FTS5 and vec index consistency."""
    result: dict[str, Any] = {"ok": True, "issues": []}

    # FTS5 vs curated_memories
    curated_count = conn.execute(
        "SELECT COUNT(*) FROM curated_memories WHERE deleted_at IS NULL"
    ).fetchone()[0]

    # Use the docsize shadow table to get the actual indexed row count,
    # since content-sync FTS5 COUNT(*) reads from the content table.
    fts_count = conn.execute(
        "SELECT COUNT(*) FROM curated_memories_fts_docsize"
    ).fetchone()[0]

    if fts_count != curated_count:
        result["ok"] = False
        result["issues"].append(
            f"FTS5 count ({fts_count}) differs from curated_memories count ({curated_count})"
        )

    # Vec index vs raw_chunks
    raw_count = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]

    try:
        vec_count = conn.execute(
            "SELECT COUNT(*) FROM raw_chunks_vec"
        ).fetchone()[0]

        if vec_count != raw_count:
            result["ok"] = False
            result["issues"].append(
                f"Vec index count ({vec_count}) differs from raw_chunks count ({raw_count})"
            )
    except sqlite3.OperationalError:
        result["ok"] = False
        result["issues"].append("raw_chunks_vec table does not exist")

    return result
