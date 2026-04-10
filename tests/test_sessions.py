"""Tests for sessions ingestion."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.sessions import ingest_sessions


@pytest.fixture()
def conn():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        connection = init_db(db_path)
        yield connection
        connection.close()


@pytest.fixture()
def staging_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _write_staging(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(l) for l in lines))


def test_ingest_creates_sessions(conn, staging_dir):
    """ingest_sessions creates one row per unique session_id."""
    _write_staging(staging_dir / "2026-04-09.jsonl", [
        {"timestamp": "2026-04-09T10:00:00Z", "session_id": "aaa", "content": "x" * 60},
        {"timestamp": "2026-04-09T10:05:00Z", "session_id": "aaa", "content": "y" * 60},
        {"timestamp": "2026-04-09T11:00:00Z", "session_id": "bbb", "content": "z" * 60},
    ])
    result = ingest_sessions(conn, staging_dir)
    assert result["sessions_created"] == 2
    rows = conn.execute("SELECT id, date, status, chunk_count FROM sessions ORDER BY id").fetchall()
    assert rows == [
        ("aaa", "2026-04-09", "unprocessed", 2),
        ("bbb", "2026-04-09", "unprocessed", 1),
    ]


def test_ingest_idempotent(conn, staging_dir):
    """Running ingest_sessions twice does not duplicate sessions."""
    _write_staging(staging_dir / "2026-04-09.jsonl", [
        {"timestamp": "2026-04-09T10:00:00Z", "session_id": "aaa", "content": "x" * 60},
    ])
    ingest_sessions(conn, staging_dir)
    result = ingest_sessions(conn, staging_dir)
    assert result["sessions_created"] == 0
    count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert count == 1


def test_ingest_skips_short_content(conn, staging_dir):
    """Lines with content shorter than 50 chars are not counted as chunks."""
    _write_staging(staging_dir / "2026-04-09.jsonl", [
        {"timestamp": "2026-04-09T10:00:00Z", "session_id": "aaa", "content": "short"},
        {"timestamp": "2026-04-09T10:01:00Z", "session_id": "aaa", "content": "x" * 60},
    ])
    ingest_sessions(conn, staging_dir)
    row = conn.execute("SELECT chunk_count FROM sessions WHERE id='aaa'").fetchone()
    assert row[0] == 1


def test_ingest_returns_stats(conn, staging_dir):
    """ingest_sessions returns a stats dict."""
    _write_staging(staging_dir / "2026-04-09.jsonl", [
        {"timestamp": "2026-04-09T10:00:00Z", "session_id": "aaa", "content": "x" * 60},
    ])
    result = ingest_sessions(conn, staging_dir)
    assert set(result.keys()) == {"sessions_created", "sessions_updated", "files_processed"}
