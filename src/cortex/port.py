"""Export and import curated memories as portable JSON."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

logger = logging.getLogger("cortex")


def export_memories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all non-deleted curated memories as a list of dicts.

    Fields included: id, content, type, source, tags, confidence,
    created_at, updated_at, supersedes_id.
    """
    rows = conn.execute(
        """
        SELECT id, content, type, source, tags, confidence,
               created_at, updated_at, supersedes_id
        FROM curated_memories
        WHERE deleted_at IS NULL
        ORDER BY id
        """
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
            "updated_at": row[7],
            "supersedes_id": row[8],
        }
        for row in rows
    ]


def import_memories(
    conn: sqlite3.Connection, memories: list[dict[str, Any]]
) -> dict[str, int]:
    """Insert memories from a list of dicts, skipping duplicates.

    Idempotency check: a memory is skipped if a non-deleted memory with
    the same content AND type already exists in the database.

    Returns a dict with keys 'imported' and 'skipped'.
    """
    from cortex.curated import remember

    imported = 0
    skipped = 0

    for mem in memories:
        content = mem.get("content", "")
        mem_type = mem.get("type", "fact")

        # Idempotency: skip if identical content+type already exists
        existing = conn.execute(
            """
            SELECT id FROM curated_memories
            WHERE content = ? AND type = ? AND deleted_at IS NULL
            LIMIT 1
            """,
            (content, mem_type),
        ).fetchone()

        if existing is not None:
            skipped += 1
            logger.debug("Skipping duplicate memory: %.60s", content)
            continue

        tags = mem.get("tags") or []
        if isinstance(tags, str):
            tags = json.loads(tags)

        remember(
            conn,
            content,
            type=mem_type,
            source=mem.get("source"),
            tags=tags,
            confidence=mem.get("confidence", 1.0),
            # Don't try to preserve supersedes_id — IDs differ across DBs
        )
        imported += 1

    return {"imported": imported, "skipped": skipped}
