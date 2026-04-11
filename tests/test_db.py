"""Tests for cortex.db schema initialization."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from cortex.db import init_db


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path) -> sqlite3.Connection:
    c = init_db(db_path)
    yield c
    c.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
    ).fetchall()
    return {r[0] for r in rows}


def _vtable_names(conn: sqlite3.Connection) -> set[str]:
    """Return names of virtual tables (FTS5, etc.)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE sql LIKE '%VIRTUAL TABLE%'"
    ).fetchall()
    return {r[0] for r in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


class TestInitDb:
    def test_creates_db_file(self, db_path: Path):
        init_db(db_path).close()
        assert db_path.exists()

    def test_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "test.db"
        init_db(nested).close()
        assert nested.exists()

    def test_wal_mode_enabled(self, conn: sqlite3.Connection):
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_curated_memories_table_exists(self, conn: sqlite3.Connection):
        assert "curated_memories" in _table_names(conn)

    def test_curated_memories_columns(self, conn: sqlite3.Connection):
        cols = _column_names(conn, "curated_memories")
        expected = [
            "id", "content", "type", "source", "tags", "confidence",
            "created_at", "updated_at", "supersedes_id", "deleted_at",
        ]
        assert cols == expected

    def test_curated_memories_type_check(self, conn: sqlite3.Connection):
        valid_types = ["decision", "preference", "procedure", "entity", "fact", "idea"]
        for t in valid_types:
            conn.execute(
                "INSERT INTO curated_memories (content, type) VALUES (?, ?)",
                (f"test {t}", t),
            )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO curated_memories (content, type) VALUES ('bad', 'invalid')"
            )

    def test_curated_memories_fts_exists(self, conn: sqlite3.Connection):
        # FTS5 tables show up in sqlite_master
        names = _vtable_names(conn)
        assert "curated_memories_fts" in names

    def test_fts_sync(self, conn: sqlite3.Connection):
        """Inserting into curated_memories should be searchable via FTS."""
        conn.execute(
            "INSERT INTO curated_memories (content, type, tags) VALUES (?, ?, ?)",
            ("Claude is helpful", "fact", '["ai", "tools"]'),
        )
        conn.commit()
        results = conn.execute(
            "SELECT content FROM curated_memories_fts WHERE curated_memories_fts MATCH 'helpful'"
        ).fetchall()
        assert len(results) == 1
        assert results[0][0] == "Claude is helpful"

    def test_raw_chunks_table(self, conn: sqlite3.Connection):
        assert "raw_chunks" in _table_names(conn)
        cols = _column_names(conn, "raw_chunks")
        expected = [
            "id", "content", "embedding", "source", "source_type",
            "metadata", "created_at", "tried_at",
        ]
        assert cols == expected

    def test_raw_chunks_source_type_check(self, conn: sqlite3.Connection):
        for st in ["book", "podcast", "session", "article"]:
            conn.execute(
                "INSERT INTO raw_chunks (content, source_type) VALUES (?, ?)",
                (f"chunk from {st}", st),
            )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO raw_chunks (content, source_type) VALUES ('bad', 'tweet')"
            )

    def test_extractions_table(self, conn: sqlite3.Connection):
        assert "extractions" in _table_names(conn)
        cols = _column_names(conn, "extractions")
        assert cols == ["id", "raw_chunk_id", "curated_memory_id", "created_at"]

    def test_meta_table(self, conn: sqlite3.Connection):
        assert "meta" in _table_names(conn)
        conn.execute("INSERT INTO meta (key, value) VALUES ('version', '0.1.0')")
        conn.commit()
        row = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        assert row[0] == "0.1.0"

    def test_idempotent(self, db_path: Path):
        """Calling init_db twice on the same path should not fail."""
        c1 = init_db(db_path)
        c1.close()
        c2 = init_db(db_path)
        c2.close()

    def test_sessions_table_exists(self, conn: sqlite3.Connection):
        """sessions table is created by init_db."""
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        assert row is not None, "sessions table not found"

    def test_sessions_table_schema(self, conn: sqlite3.Connection):
        """sessions table has the required columns."""
        rows = conn.execute("PRAGMA table_info(sessions)").fetchall()
        cols = {r[1] for r in rows}
        assert cols == {
            "id", "date", "title", "summary", "status",
            "tags", "chunk_count", "first_seen_at", "classified_at"
        }

    def test_sessions_status_constraint(self, conn: sqlite3.Connection):
        """sessions.status only accepts open, closed, unprocessed."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions (id, date, status) VALUES ('x', '2026-01-01', 'invalid')"
            )
