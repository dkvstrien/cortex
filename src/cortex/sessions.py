"""Sessions layer: parse staging JSONL files into the sessions table."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("cortex")

MIN_CONTENT_LEN = 50


def ingest_sessions(
    conn: sqlite3.Connection,
    staging_dir: str | Path,
) -> dict[str, int]:
    """Parse all staging JSONL files and upsert one row per session_id.

    Idempotent — running twice on the same files produces the same result.
    Does not touch classified sessions (status != 'unprocessed') — chunk_count
    is updated on re-runs to catch new chunks in existing sessions.

    Returns dict with keys: sessions_created, sessions_updated, files_processed.
    """
    staging_dir = Path(staging_dir)
    if not staging_dir.is_dir():
        logger.warning("Staging directory does not exist: %s", staging_dir)
        return {"sessions_created": 0, "sessions_updated": 0, "files_processed": 0}

    # session_id -> {date, chunk_count}
    seen: dict[str, dict] = {}

    for jsonl_path in sorted(staging_dir.glob("*.jsonl")):
        # Date comes from the filename: YYYY-MM-DD.jsonl
        date = jsonl_path.stem  # e.g. "2026-04-09"

        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            session_id = obj.get("session_id", "")
            content = obj.get("content", "")
            if not session_id or len(content) < MIN_CONTENT_LEN:
                continue

            if session_id not in seen:
                seen[session_id] = {"date": date, "chunk_count": 0}
            seen[session_id]["chunk_count"] += 1

    sessions_created = 0
    sessions_updated = 0

    for session_id, info in seen.items():
        existing = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO sessions (id, date, chunk_count, status)
                VALUES (?, ?, ?, 'unprocessed')
                """,
                (session_id, info["date"], info["chunk_count"]),
            )
            sessions_created += 1
        else:
            conn.execute(
                "UPDATE sessions SET chunk_count = ? WHERE id = ?",
                (info["chunk_count"], session_id),
            )
            sessions_updated += 1

    conn.commit()
    return {
        "sessions_created": sessions_created,
        "sessions_updated": sessions_updated,
        "files_processed": len(list(staging_dir.glob("*.jsonl"))),
    }
