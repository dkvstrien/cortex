"""Tests for the session classifier."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.classify import classify_prompt, process_classification


@pytest.fixture()
def conn():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        connection = init_db(db_path)
        yield connection
        connection.close()


def _insert_session(conn, session_id: str, date: str = "2026-04-09",
                    status: str = "unprocessed") -> None:
    conn.execute(
        "INSERT INTO sessions (id, date, status, chunk_count) VALUES (?, ?, ?, 1)",
        (session_id, date, status),
    )
    conn.commit()


def _insert_chunk(conn, session_id: str, content: str) -> None:
    conn.execute(
        """INSERT INTO raw_chunks (content, source, source_type)
           VALUES (?, ?, 'session')""",
        (content, f"staging:2026-04-09.jsonl:{session_id}"),
    )
    conn.commit()


def test_classify_prompt_returns_none_when_no_unprocessed(conn):
    """classify_prompt returns None when there are no unprocessed sessions."""
    _insert_session(conn, "aaa", status="closed")
    assert classify_prompt(conn) is None


def test_classify_prompt_includes_session_content(conn):
    """classify_prompt includes chunks for unprocessed sessions."""
    _insert_session(conn, "aaa")
    _insert_chunk(conn, "aaa", "Here is how to fix the Lely robot alarm.")
    prompt = classify_prompt(conn)
    assert prompt is not None
    assert "aaa" in prompt
    assert "Lely" in prompt


def test_process_classification_updates_sessions(conn):
    """process_classification writes title/summary/status/tags to sessions."""
    _insert_session(conn, "abc")
    haiku_json = json.dumps([{
        "session_id": "abc",
        "title": "Lely alarm debugging",
        "summary": "Discussed the Lely A5 alarm firing when robot is parked.",
        "status": "open",
        "tags": ["farm", "lely"],
    }])
    result = process_classification(conn, haiku_json)
    assert result["classified"] == 1
    row = conn.execute(
        "SELECT title, status, tags, classified_at FROM sessions WHERE id='abc'"
    ).fetchone()
    assert row[0] == "Lely alarm debugging"
    assert row[1] == "open"
    assert json.loads(row[2]) == ["farm", "lely"]
    assert row[3] is not None


def test_process_classification_handles_markdown_fences(conn):
    """process_classification strips markdown code fences from Haiku output."""
    _insert_session(conn, "xyz")
    haiku_output = "```json\n" + json.dumps([{
        "session_id": "xyz",
        "title": "Test session",
        "summary": "A test.",
        "status": "closed",
        "tags": [],
    }]) + "\n```"
    result = process_classification(conn, haiku_output)
    assert result["classified"] == 1


def test_process_classification_ignores_unknown_sessions(conn):
    """Sessions in Haiku output that don't exist in DB are skipped."""
    haiku_json = json.dumps([{
        "session_id": "nonexistent",
        "title": "Ghost session",
        "summary": "Does not exist.",
        "status": "closed",
        "tags": [],
    }])
    result = process_classification(conn, haiku_json)
    assert result["classified"] == 0
    assert result["skipped"] == 1
