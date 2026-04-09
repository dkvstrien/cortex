"""Tests for cortex.curated: remember and recall_curated."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import remember, recall_curated


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


class TestRemember:
    def test_returns_integer_id(self, conn: sqlite3.Connection):
        mid = remember(conn, "Dan prefers SQLite over Postgres", type="preference", source="manual")
        assert isinstance(mid, int)
        assert mid > 0

    def test_stores_content_and_type(self, conn: sqlite3.Connection):
        mid = remember(conn, "Always use WAL mode", type="procedure", source="docs")
        row = conn.execute(
            "SELECT content, type, source FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row == ("Always use WAL mode", "procedure", "docs")

    def test_stores_tags_as_json(self, conn: sqlite3.Connection):
        mid = remember(conn, "Tag test", type="fact", tags=["alpha", "beta"])
        row = conn.execute("SELECT tags FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert row[0] == '["alpha", "beta"]'

    def test_default_confidence(self, conn: sqlite3.Connection):
        mid = remember(conn, "Default confidence", type="fact")
        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert row[0] == 1.0

    def test_custom_confidence(self, conn: sqlite3.Connection):
        mid = remember(conn, "Low confidence", type="fact", confidence=0.5)
        row = conn.execute("SELECT confidence FROM curated_memories WHERE id = ?", (mid,)).fetchone()
        assert row[0] == 0.5

    def test_invalid_type_raises(self, conn: sqlite3.Connection):
        with pytest.raises(sqlite3.IntegrityError):
            remember(conn, "bad type", type="invalid")


class TestRecallCurated:
    def test_basic_search(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite over Postgres", type="preference", source="manual")
        results = recall_curated(conn, "database preference")
        assert len(results) >= 1
        assert any("SQLite" in r["content"] for r in results)

    def test_result_has_rank_score(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite over Postgres", type="preference", source="manual")
        results = recall_curated(conn, "SQLite")
        assert len(results) == 1
        assert "rank" in results[0]
        assert isinstance(results[0]["rank"], float)

    def test_result_dict_keys(self, conn: sqlite3.Connection):
        remember(conn, "Test memory", type="fact", source="test", tags=["a", "b"])
        results = recall_curated(conn, "Test memory")
        assert len(results) == 1
        expected_keys = {"id", "content", "type", "source", "tags", "confidence", "rank", "created_at"}
        assert set(results[0].keys()) == expected_keys

    def test_tags_returned_as_list(self, conn: sqlite3.Connection):
        remember(conn, "Tagged memory", type="fact", tags=["x", "y"])
        results = recall_curated(conn, "Tagged")
        assert results[0]["tags"] == ["x", "y"]

    def test_type_filter(self, conn: sqlite3.Connection):
        remember(conn, "A preference about databases", type="preference")
        remember(conn, "A fact about databases", type="fact")
        results = recall_curated(conn, "databases", type="preference")
        assert len(results) == 1
        assert results[0]["type"] == "preference"

    def test_limit(self, conn: sqlite3.Connection):
        for i in range(5):
            remember(conn, f"Memory number {i} about testing", type="fact")
        results = recall_curated(conn, "testing", limit=1)
        assert len(results) == 1

    def test_soft_deleted_excluded(self, conn: sqlite3.Connection):
        mid = remember(conn, "This will be deleted", type="fact")
        # Soft-delete
        conn.execute(
            "UPDATE curated_memories SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (mid,),
        )
        conn.commit()
        results = recall_curated(conn, "deleted")
        assert len(results) == 0

    def test_superseded_excluded(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Old database preference", type="preference")
        _new_id = remember(
            conn, "New database preference", type="preference", supersedes_id=old_id
        )
        results = recall_curated(conn, "database preference")
        # Only the new memory should appear; the old one is superseded
        assert len(results) == 1
        assert "New" in results[0]["content"]

    def test_prefix_matching(self, conn: sqlite3.Connection):
        remember(conn, "SQLite databases are lightweight", type="fact")
        # "data" should match "databases" via prefix query
        results = recall_curated(conn, "data")
        assert len(results) >= 1
        assert any("databases" in r["content"] for r in results)

    def test_search_by_tags(self, conn: sqlite3.Connection):
        remember(conn, "Some memory", type="fact", tags=["infrastructure", "servers"])
        results = recall_curated(conn, "infrastructure")
        assert len(results) >= 1

    def test_no_results(self, conn: sqlite3.Connection):
        results = recall_curated(conn, "nonexistent gibberish xyz")
        assert results == []
