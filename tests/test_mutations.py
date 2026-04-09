"""Tests for forget, supersede, and get_history operations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import forget, get_history, recall_curated, remember, supersede


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


class TestForget:
    def test_sets_deleted_at(self, conn: sqlite3.Connection):
        mid = remember(conn, "To be forgotten", type="fact")
        forget(conn, mid)
        row = conn.execute(
            "SELECT deleted_at FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row[0] is not None

    def test_row_still_exists(self, conn: sqlite3.Connection):
        """forget() must NOT physically delete the row."""
        mid = remember(conn, "Still here after forget", type="fact")
        forget(conn, mid)
        row = conn.execute(
            "SELECT id, content FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row[1] == "Still here after forget"

    def test_excluded_from_recall(self, conn: sqlite3.Connection):
        mid = remember(conn, "Invisible after forget", type="fact")
        forget(conn, mid)
        results = recall_curated(conn, "Invisible")
        assert len(results) == 0

    def test_nonexistent_id_raises(self, conn: sqlite3.Connection):
        with pytest.raises(KeyError, match="No curated memory with id=99999"):
            forget(conn, 99999)

    def test_forget_does_not_physically_delete(self, conn: sqlite3.Connection):
        """Verify the row count stays the same after forget."""
        mid = remember(conn, "Count check", type="fact")
        count_before = conn.execute("SELECT COUNT(*) FROM curated_memories").fetchone()[0]
        forget(conn, mid)
        count_after = conn.execute("SELECT COUNT(*) FROM curated_memories").fetchone()[0]
        assert count_before == count_after


class TestSupersede:
    def test_creates_new_memory(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Old fact", type="fact", source="manual", tags=["alpha"])
        new_id = supersede(conn, old_id, "Updated fact")
        assert new_id != old_id
        assert new_id > old_id

    def test_new_memory_points_to_old(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Old fact", type="fact")
        new_id = supersede(conn, old_id, "New fact")
        row = conn.execute(
            "SELECT supersedes_id FROM curated_memories WHERE id = ?", (new_id,)
        ).fetchone()
        assert row[0] == old_id

    def test_old_memory_soft_deleted(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Will be superseded", type="preference")
        supersede(conn, old_id, "Replacement preference")
        row = conn.execute(
            "SELECT deleted_at FROM curated_memories WHERE id = ?", (old_id,)
        ).fetchone()
        assert row[0] is not None

    def test_inherits_type_source_tags(self, conn: sqlite3.Connection):
        old_id = remember(
            conn, "Original", type="procedure", source="docs", tags=["infra", "db"]
        )
        new_id = supersede(conn, old_id, "Updated procedure")
        row = conn.execute(
            "SELECT type, source, tags FROM curated_memories WHERE id = ?", (new_id,)
        ).fetchone()
        assert row[0] == "procedure"
        assert row[1] == "docs"
        assert row[2] == '["infra", "db"]'

    def test_override_type_source_tags(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Original", type="fact", source="old_src", tags=["a"])
        new_id = supersede(
            conn, old_id, "Changed", type="preference", source="new_src", tags=["b"]
        )
        row = conn.execute(
            "SELECT type, source, tags FROM curated_memories WHERE id = ?", (new_id,)
        ).fetchone()
        assert row[0] == "preference"
        assert row[1] == "new_src"
        assert row[2] == '["b"]'

    def test_nonexistent_old_id_raises(self, conn: sqlite3.Connection):
        with pytest.raises(KeyError):
            supersede(conn, 99999, "No such memory")

    def test_new_memory_appears_in_recall(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Old database preference", type="preference")
        new_id = supersede(conn, old_id, "New database preference")
        results = recall_curated(conn, "database preference")
        ids = [r["id"] for r in results]
        assert new_id in ids
        assert old_id not in ids


class TestGetHistory:
    def test_single_memory_no_chain(self, conn: sqlite3.Connection):
        mid = remember(conn, "Standalone memory", type="fact")
        history = get_history(conn, mid)
        assert len(history) == 1
        assert history[0]["id"] == mid
        assert history[0]["content"] == "Standalone memory"

    def test_two_level_chain(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Version 1", type="fact")
        new_id = supersede(conn, old_id, "Version 2")
        history = get_history(conn, new_id)
        assert len(history) == 2
        assert history[0]["id"] == new_id
        assert history[0]["content"] == "Version 2"
        assert history[1]["id"] == old_id
        assert history[1]["content"] == "Version 1"

    def test_three_level_chain(self, conn: sqlite3.Connection):
        v1 = remember(conn, "Version 1", type="fact")
        v2 = supersede(conn, v1, "Version 2")
        v3 = supersede(conn, v2, "Version 3")
        history = get_history(conn, v3)
        assert len(history) == 3
        assert [h["id"] for h in history] == [v3, v2, v1]

    def test_history_includes_deleted_at(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Old", type="fact")
        new_id = supersede(conn, old_id, "New")
        history = get_history(conn, new_id)
        # The old memory should show deleted_at set
        assert history[1]["deleted_at"] is not None
        # The new memory should not be deleted
        assert history[0]["deleted_at"] is None

    def test_history_includes_supersedes_id(self, conn: sqlite3.Connection):
        old_id = remember(conn, "Old", type="fact")
        new_id = supersede(conn, old_id, "New")
        history = get_history(conn, new_id)
        assert history[0]["supersedes_id"] == old_id
        assert history[1]["supersedes_id"] is None

    def test_nonexistent_id_raises(self, conn: sqlite3.Connection):
        with pytest.raises(KeyError, match="No curated memory with id=99999"):
            get_history(conn, 99999)
