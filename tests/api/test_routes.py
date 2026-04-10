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
