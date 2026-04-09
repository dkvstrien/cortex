"""Confidence decay system for curated memories.

Exponential decay with configurable half-life. Accessing a memory via
recall reinforces it (resets confidence to 1.0).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


def reinforce(conn: sqlite3.Connection, memory_id: int) -> None:
    """Reset a memory's confidence to 1.0 and refresh updated_at."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute(
        "UPDATE curated_memories SET confidence = 1.0, updated_at = ? WHERE id = ?",
        (now, memory_id),
    )
    conn.commit()


def decay_confidence(
    conn: sqlite3.Connection,
    *,
    half_life_days: float = 90.0,
) -> int:
    """Apply exponential decay to all curated memory confidence values.

    Formula: new_confidence = confidence * (0.5 ^ (days_since_update / half_life_days))

    This is meant to be called periodically (e.g. daily via cron), not on
    every access.

    Returns the number of memories updated.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # Apply absolute decay from updated_at (last reinforcement).
    # Do NOT update updated_at here -- only reinforce() should do that.
    # Formula: new_confidence = 1.0 * (0.5 ^ (days_since_update / half_life))
    # We use the original confidence=1.0 baseline because updated_at marks
    # the last reinforcement when confidence was reset to 1.0.
    cursor = conn.execute(
        """
        UPDATE curated_memories
        SET confidence = POWER(0.5, (julianday(?) - julianday(updated_at)) / ?)
        WHERE deleted_at IS NULL
          AND (julianday(?) - julianday(updated_at)) > 0
        """,
        (now, half_life_days, now),
    )
    conn.commit()
    return cursor.rowcount


def get_stale(
    conn: sqlite3.Connection,
    *,
    threshold: float = 0.1,
) -> list[dict[str, Any]]:
    """Return curated memories with confidence below *threshold*."""
    rows = conn.execute(
        """
        SELECT id, content, type, source, tags, confidence, created_at, updated_at
        FROM curated_memories
        WHERE confidence < ?
          AND deleted_at IS NULL
        ORDER BY confidence ASC
        """,
        (threshold,),
    ).fetchall()

    return [
        {
            "id": row[0],
            "content": row[1],
            "type": row[2],
            "source": row[3],
            "tags": row[4],
            "confidence": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]
