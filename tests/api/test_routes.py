"""API route tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from cortex.db import init_db


@pytest.fixture(autouse=True)
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("CORTEX_DB_PATH", str(db_path))
    conn = init_db(db_path)
    conn.close()
    yield db_path


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


import json as json_mod


def _insert_session(db_path, session_id, title, status, date="2026-04-09", tags=None):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO sessions (id, date, title, summary, status, tags, chunk_count, classified_at)
           VALUES (?, ?, ?, 'A test session.', ?, ?, 1, '2026-04-09T22:00:00Z')""",
        (session_id, date, title, status, json_mod.dumps(tags or [])),
    )
    conn.commit()
    conn.close()


def _insert_chunk(db_path, session_id, content):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO raw_chunks (content, source, source_type) VALUES (?, ?, 'session')",
        (content, f"staging:2026-04-09.jsonl:{session_id}"),
    )
    conn.commit()
    conn.close()


def _insert_memory(db_path, session_id, content, mem_type="fact"):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO curated_memories (content, type, source, tags) VALUES (?, ?, ?, '[]')",
        (content, mem_type, session_id),
    )
    conn.commit()
    conn.close()


def test_list_sessions_empty(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sessions_returns_sessions(client, test_db):
    _insert_session(test_db, "aaa", "Lely alarm", "open", tags=["farm"])
    _insert_session(test_db, "bbb", "Cortex debug", "closed", tags=["cortex"])
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["id"] in ("aaa", "bbb")


def test_list_sessions_filter_by_status(client, test_db):
    _insert_session(test_db, "aaa", "Open one", "open")
    _insert_session(test_db, "bbb", "Closed one", "closed")
    resp = client.get("/api/sessions?status=open")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "open"


def test_get_session_detail(client, test_db):
    _insert_session(test_db, "aaa", "Lely alarm", "open")
    _insert_chunk(test_db, "aaa", "Here is the robot response text.")
    _insert_memory(test_db, "aaa", "Lely alarm fires when parked")
    resp = client.get("/api/sessions/aaa")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "aaa"
    assert len(data["chunks"]) == 1
    assert len(data["memories"]) == 1


def test_get_session_not_found(client):
    resp = client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404


def test_get_transcript(client, test_db):
    _insert_session(test_db, "aaa", "Test", "closed")
    _insert_chunk(test_db, "aaa", "Chunk one content here for the robot.")
    _insert_chunk(test_db, "aaa", "Chunk two content here for the robot.")
    resp = client.get("/api/sessions/aaa/transcript")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["chunks"]) == 2
