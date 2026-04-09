"""Tests for cortex.status health dashboard."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.status import status


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    c = init_db(db_path)
    yield c
    c.close()


class TestStatusKeys:
    """status() returns a dict with all expected keys."""

    def test_returns_all_keys(self, conn, db_path):
        result = status(conn, db_path)
        expected_keys = {
            "curated_count", "raw_count", "by_type", "by_source",
            "last_memory_at", "last_consolidation_at", "db_size_mb",
            "stale_count", "integrity",
        }
        assert set(result.keys()) == expected_keys

    def test_empty_db_defaults(self, conn, db_path):
        result = status(conn, db_path)
        assert result["curated_count"] == 0
        assert result["raw_count"] == 0
        assert result["by_type"] == {}
        assert result["by_source"] == {}
        assert result["last_memory_at"] is None
        assert result["last_consolidation_at"] is None
        assert result["stale_count"] == 0
        assert result["db_size_mb"] > 0


class TestCounts:
    def test_curated_count_excludes_deleted(self, conn, db_path):
        conn.execute(
            "INSERT INTO curated_memories (content, type) VALUES ('a', 'fact')"
        )
        conn.execute(
            "INSERT INTO curated_memories (content, type, deleted_at) "
            "VALUES ('b', 'fact', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["curated_count"] == 1

    def test_raw_count(self, conn, db_path):
        conn.execute(
            "INSERT INTO raw_chunks (content, source_type) VALUES ('x', 'book')"
        )
        conn.execute(
            "INSERT INTO raw_chunks (content, source_type) VALUES ('y', 'article')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["raw_count"] == 2


class TestByType:
    def test_by_type_groups_correctly(self, conn, db_path):
        for t in ["fact", "fact", "preference", "idea"]:
            conn.execute(
                "INSERT INTO curated_memories (content, type) VALUES (?, ?)",
                (f"mem {t}", t),
            )
        conn.commit()
        result = status(conn, db_path)
        assert result["by_type"] == {"fact": 2, "preference": 1, "idea": 1}

    def test_by_type_excludes_deleted(self, conn, db_path):
        conn.execute(
            "INSERT INTO curated_memories (content, type) VALUES ('a', 'fact')"
        )
        conn.execute(
            "INSERT INTO curated_memories (content, type, deleted_at) "
            "VALUES ('b', 'fact', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["by_type"] == {"fact": 1}


class TestBySource:
    def test_by_source_groups_correctly(self, conn, db_path):
        for st in ["book", "book", "podcast", "article"]:
            conn.execute(
                "INSERT INTO raw_chunks (content, source_type) VALUES (?, ?)",
                (f"chunk {st}", st),
            )
        conn.commit()
        result = status(conn, db_path)
        assert result["by_source"] == {"book": 2, "podcast": 1, "article": 1}


class TestTimestamps:
    def test_last_memory_at(self, conn, db_path):
        conn.execute(
            "INSERT INTO curated_memories (content, type) VALUES ('a', 'fact')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["last_memory_at"] is not None

    def test_last_consolidation_at_from_meta(self, conn, db_path):
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('last_consolidation_at', '2026-04-01T12:00:00Z')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["last_consolidation_at"] == "2026-04-01T12:00:00Z"

    def test_last_consolidation_at_missing(self, conn, db_path):
        result = status(conn, db_path)
        assert result["last_consolidation_at"] is None


class TestStaleCount:
    def test_stale_count(self, conn, db_path):
        # Non-stale
        conn.execute(
            "INSERT INTO curated_memories (content, type, confidence) "
            "VALUES ('fresh', 'fact', 0.8)"
        )
        # Stale
        conn.execute(
            "INSERT INTO curated_memories (content, type, confidence) "
            "VALUES ('old', 'fact', 0.05)"
        )
        conn.execute(
            "INSERT INTO curated_memories (content, type, confidence) "
            "VALUES ('ancient', 'fact', 0.01)"
        )
        # Stale but deleted — should not count
        conn.execute(
            "INSERT INTO curated_memories (content, type, confidence, deleted_at) "
            "VALUES ('gone', 'fact', 0.01, '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["stale_count"] == 2


class TestDbSize:
    def test_db_size_mb_positive(self, conn, db_path):
        result = status(conn, db_path)
        assert isinstance(result["db_size_mb"], float)
        assert result["db_size_mb"] > 0


class TestIntegrity:
    def test_integrity_ok_empty_db(self, conn, db_path):
        result = status(conn, db_path)
        assert result["integrity"]["ok"] is True
        assert result["integrity"]["issues"] == []

    def test_integrity_ok_with_data(self, conn, db_path):
        # Insert via normal path (triggers keep FTS in sync)
        conn.execute(
            "INSERT INTO curated_memories (content, type) VALUES ('x', 'fact')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["integrity"]["ok"] is True

    def test_fts_mismatch_detected(self, conn, db_path):
        # Insert two curated memories normally
        conn.execute(
            "INSERT INTO curated_memories (content, type) VALUES ('x', 'fact')"
        )
        conn.execute(
            "INSERT INTO curated_memories (content, type) VALUES ('y', 'idea')"
        )
        conn.commit()
        # Manually delete one from FTS index to create desync
        conn.execute(
            "INSERT INTO curated_memories_fts(curated_memories_fts, rowid, content, type, tags) "
            "VALUES ('delete', 1, 'x', 'fact', '[]')"
        )
        conn.commit()
        result = status(conn, db_path)
        assert result["integrity"]["ok"] is False
        assert any("FTS5 count" in issue for issue in result["integrity"]["issues"])

    def test_vec_mismatch_detected(self, conn, db_path):
        # Insert a raw chunk but skip vec index
        conn.execute(
            "INSERT INTO raw_chunks (content, source_type) VALUES ('x', 'book')"
        )
        conn.commit()
        # raw_chunks has 1 row, raw_chunks_vec has 0
        result = status(conn, db_path)
        assert result["integrity"]["ok"] is False
        assert any("Vec index count" in issue for issue in result["integrity"]["issues"])
