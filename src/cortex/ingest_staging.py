"""Staging file ingestion: read JSONL staging files and store in raw layer."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from cortex.ingest import chunk_text
from cortex.raw import store_chunk

logger = logging.getLogger("cortex")

_META_PREFIX = "ingested_staging_file:"


def _is_file_ingested(conn: sqlite3.Connection, filename: str) -> bool:
    """Check if a staging file has already been ingested (tracked in meta table)."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?",
        (_META_PREFIX + filename,),
    ).fetchone()
    return row is not None and row[0] == "done"


def _mark_file_ingested(conn: sqlite3.Connection, filename: str) -> None:
    """Record a staging file as fully ingested in the meta table."""
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, 'done')",
        (_META_PREFIX + filename,),
    )
    conn.commit()


def ingest_staging(
    conn: sqlite3.Connection,
    staging_dir: str | Path,
    max_tokens: int = 300,
    overlap: int = 50,
) -> dict[str, int]:
    """Process all .jsonl staging files in *staging_dir*.

    Each JSONL line must have a ``content`` field.  The content is chunked
    and stored in raw_chunks with source_type='session'.  Completed files are
    tracked in the meta table so re-running is idempotent.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    staging_dir:
        Directory containing .jsonl staging files.
    max_tokens:
        Maximum tokens per chunk (default 300).
    overlap:
        Overlap tokens between chunks (default 50).

    Returns
    -------
    Dict with keys: lines_processed, chunks_stored, files_completed,
    files_skipped.
    """
    staging_dir = Path(staging_dir)
    if not staging_dir.is_dir():
        logger.warning("Staging directory does not exist: %s", staging_dir)
        return {
            "lines_processed": 0,
            "chunks_stored": 0,
            "files_completed": 0,
            "files_skipped": 0,
        }

    jsonl_files = sorted(staging_dir.glob("*.jsonl"))

    lines_processed = 0
    chunks_stored = 0
    files_completed = 0
    files_skipped = 0

    for jsonl_path in jsonl_files:
        filename = jsonl_path.name

        if _is_file_ingested(conn, filename):
            logger.debug("Skipping already-ingested staging file: %s", filename)
            files_skipped += 1
            continue

        file_lines = 0
        file_chunks = 0

        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON line in %s", filename)
                continue

            content = obj.get("content", "")
            if not content or len(content) < 50:
                continue

            session_id = obj.get("session_id", filename)
            source = f"staging:{filename}:{session_id}"

            text_chunks = chunk_text(content, max_tokens=max_tokens, overlap=overlap)
            for chunk in text_chunks:
                store_chunk(conn, chunk, source, "session")
                file_chunks += 1

            file_lines += 1

        lines_processed += file_lines
        chunks_stored += file_chunks
        _mark_file_ingested(conn, filename)
        files_completed += 1
        logger.debug(
            "Ingested staging file %s: %d lines, %d chunks",
            filename, file_lines, file_chunks,
        )

    return {
        "lines_processed": lines_processed,
        "chunks_stored": chunks_stored,
        "files_completed": files_completed,
        "files_skipped": files_skipped,
    }
