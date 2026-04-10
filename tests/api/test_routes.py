"""API route tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Point at a fresh test DB before importing app
@pytest.fixture(autouse=True)
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("CORTEX_DB_PATH", str(db_path))
    # Init schema using the existing Cortex db module
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from cortex.db import init_db
    conn = init_db(db_path)
    conn.close()
    yield db_path


@pytest.fixture()
def client(test_db):
    # Import after env var is set
    from api.main import app
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
