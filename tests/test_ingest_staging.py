"""Tests for the staging file ingestion subcommand."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.ingest_staging import (
    _META_PREFIX,
    _is_file_ingested,
    _mark_file_ingested,
    ingest_staging,
)


@pytest.fixture()
def conn():
    """Temporary Cortex database for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        connection = init_db(db_path)
        yield connection
        connection.close()


@pytest.fixture()
def staging_dir():
    """Temporary staging directory."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _make_jsonl_line(content: str, session_id: str = "sess1") -> str:
    return json.dumps({
        "timestamp": "2026-04-09T10:00:00Z",
        "session_id": session_id,
        "content": content,
    })


# --- meta table helpers ---


def test_mark_and_check_file_ingested(conn):
    """_mark_file_ingested records the file; _is_file_ingested detects it."""
    assert not _is_file_ingested(conn, "2026-04-09.jsonl")
    _mark_file_ingested(conn, "2026-04-09.jsonl")
    assert _is_file_ingested(conn, "2026-04-09.jsonl")


def test_meta_key_format(conn):
    """Meta key uses the expected prefix."""
    _mark_file_ingested(conn, "testfile.jsonl")
    row = conn.execute(
        "SELECT key, value FROM meta WHERE key = ?",
        (_META_PREFIX + "testfile.jsonl",),
    ).fetchone()
    assert row is not None
    assert row[0] == "ingested_staging_file:testfile.jsonl"
    assert row[1] == "done"


# --- ingest_staging core behaviour ---


def test_ingest_staging_processes_jsonl(conn, staging_dir):
    """ingest_staging reads .jsonl files and stores chunks."""
    content = "word " * 60  # 60 words, well over 50 chars
    (staging_dir / "2026-04-09.jsonl").write_text(_make_jsonl_line(content))

    result = ingest_staging(conn, staging_dir)

    assert result["lines_processed"] >= 1
    assert result["chunks_stored"] >= 1
    assert result["files_completed"] == 1
    assert result["files_skipped"] == 0

    count = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]
    assert count == result["chunks_stored"]


def test_ingest_staging_source_type_is_session(conn, staging_dir):
    """Stored chunks have source_type='session'."""
    content = "word " * 60
    (staging_dir / "2026-04-09.jsonl").write_text(_make_jsonl_line(content))
    ingest_staging(conn, staging_dir)

    rows = conn.execute("SELECT DISTINCT source_type FROM raw_chunks").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "session"


def test_ingest_staging_skips_short_content(conn, staging_dir):
    """Lines with content shorter than 50 chars are skipped."""
    short = json.dumps({
        "timestamp": "2026-04-09T10:00:00Z",
        "session_id": "sess1",
        "content": "too short",
    })
    long_content = "word " * 60
    long = _make_jsonl_line(long_content)
    (staging_dir / "2026-04-09.jsonl").write_text(short + "\n" + long)

    result = ingest_staging(conn, staging_dir)

    # Only the long line should be processed
    assert result["lines_processed"] == 1


def test_ingest_staging_multiple_files(conn, staging_dir):
    """ingest_staging processes all .jsonl files in the directory."""
    content = "word " * 60
    (staging_dir / "2026-04-08.jsonl").write_text(_make_jsonl_line(content))
    (staging_dir / "2026-04-09.jsonl").write_text(_make_jsonl_line(content))

    result = ingest_staging(conn, staging_dir)

    assert result["files_completed"] == 2
    assert result["lines_processed"] == 2


def test_ingest_staging_ignores_non_jsonl(conn, staging_dir):
    """Non-.jsonl files in the directory are ignored."""
    (staging_dir / "notes.txt").write_text("word " * 60)
    content = "word " * 60
    (staging_dir / "2026-04-09.jsonl").write_text(_make_jsonl_line(content))

    result = ingest_staging(conn, staging_dir)

    assert result["files_completed"] == 1


def test_ingest_staging_missing_directory(conn):
    """ingest_staging returns zeros if staging directory doesn't exist."""
    result = ingest_staging(conn, "/nonexistent/staging/path")
    assert result == {
        "lines_processed": 0,
        "chunks_stored": 0,
        "files_completed": 0,
        "files_skipped": 0,
    }


# --- idempotency ---


def test_ingest_staging_idempotent(conn, staging_dir):
    """Re-ingesting the same staging file skips it and keeps chunk count unchanged."""
    content = "word " * 60
    (staging_dir / "2026-04-09.jsonl").write_text(_make_jsonl_line(content))

    result1 = ingest_staging(conn, staging_dir)
    assert result1["files_completed"] == 1
    assert result1["files_skipped"] == 0

    count_after_first = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]

    result2 = ingest_staging(conn, staging_dir)
    assert result2["files_completed"] == 0
    assert result2["files_skipped"] == 1
    assert result2["chunks_stored"] == 0
    assert result2["lines_processed"] == 0

    count_after_second = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]
    assert count_after_second == count_after_first


def test_ingest_staging_new_file_after_skip(conn, staging_dir):
    """After a file is marked done, new files in the directory are still processed."""
    content = "word " * 60
    (staging_dir / "2026-04-08.jsonl").write_text(_make_jsonl_line(content))
    ingest_staging(conn, staging_dir)

    # Add a new file
    (staging_dir / "2026-04-09.jsonl").write_text(_make_jsonl_line(content))
    result = ingest_staging(conn, staging_dir)

    assert result["files_completed"] == 1
    assert result["files_skipped"] == 1


# --- CLI integration ---


def test_source_uses_session_id(conn, staging_dir):
    """raw_chunks source uses staging:file:session_id format; session_id is last segment."""
    lines = [_make_jsonl_line("x" * 60, session_id="my-session")]
    (staging_dir / "2026-04-09.jsonl").write_text("\n".join(lines))
    ingest_staging(conn, staging_dir)
    row = conn.execute("SELECT source FROM raw_chunks LIMIT 1").fetchone()
    assert row[0].endswith(":my-session")
    assert row[0].startswith("staging:")


def test_cli_ingest_staging(staging_dir, tmp_path):
    """CLI subcommand ingest-staging runs and prints summary."""
    import subprocess
    import sys

    db_path = tmp_path / "cortex.db"
    content = "word " * 60
    (staging_dir / "2026-04-09.jsonl").write_text(_make_jsonl_line(content))

    result = subprocess.run(
        [
            sys.executable, "-m", "cortex",
            "ingest-staging",
            "--db", str(db_path),
            "--staging-dir", str(staging_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = result.stdout
    assert "lines processed" in output
    assert "chunks stored" in output
    assert "files completed" in output
    assert "files skipped" in output
