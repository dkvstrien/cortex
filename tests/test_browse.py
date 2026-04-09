"""Tests for cortex browse commands: list, search, show."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import remember, supersede
from cortex.browse import (
    list_memories,
    print_list,
    search_memories,
    print_search,
    print_show,
)


@pytest.fixture
def conn(tmp_path: Path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn_with_path(db_path: Path):
    c = init_db(db_path)
    yield c, db_path
    c.close()


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------

class TestListMemories:
    def test_returns_recent_memories(self, conn):
        remember(conn, "Fact one", type="fact", source="test")
        remember(conn, "Preference one", type="preference", source="test")
        results = list_memories(conn)
        assert len(results) == 2

    def test_filters_by_type(self, conn):
        remember(conn, "Fact one", type="fact")
        remember(conn, "Pref one", type="preference")
        remember(conn, "Fact two", type="fact")
        facts = list_memories(conn, type="fact")
        assert len(facts) == 2
        assert all(m["type"] == "fact" for m in facts)

    def test_respects_limit(self, conn):
        for i in range(10):
            remember(conn, f"Memory {i}", type="fact")
        results = list_memories(conn, limit=5)
        assert len(results) == 5

    def test_excludes_deleted(self, conn):
        mid = remember(conn, "To be deleted", type="fact")
        remember(conn, "Active memory", type="fact")
        # Soft-delete first memory
        from cortex.curated import forget
        forget(conn, mid)
        results = list_memories(conn)
        assert len(results) == 1
        assert results[0]["content"] == "Active memory"

    def test_order_recent_first(self, conn):
        import time
        a = remember(conn, "First stored", type="fact")
        # Force a distinct timestamp by updating the row directly
        conn.execute(
            "UPDATE curated_memories SET created_at = '2026-01-01T00:00:00.000000Z' WHERE id = ?",
            (a,),
        )
        conn.commit()
        b = remember(conn, "Second stored", type="fact")
        results = list_memories(conn)
        # Most recent should be first
        ids = [m["id"] for m in results]
        assert ids.index(b) < ids.index(a)

    def test_result_has_expected_keys(self, conn):
        remember(conn, "Test memory", type="fact", source="test", tags=["x"])
        results = list_memories(conn)
        assert len(results) == 1
        m = results[0]
        assert set(m.keys()) == {"id", "content", "type", "source", "tags", "confidence", "created_at"}

    def test_empty_db_returns_empty_list(self, conn):
        results = list_memories(conn)
        assert results == []


# ---------------------------------------------------------------------------
# search_memories
# ---------------------------------------------------------------------------

class TestSearchMemories:
    def test_returns_relevant_results(self, conn):
        remember(conn, "Dan prefers SQLite over Postgres", type="preference")
        remember(conn, "The farm has 42 cows", type="fact")
        results = search_memories(conn, "SQLite database")
        assert len(results) >= 1
        assert any("SQLite" in r["content"] for r in results)

    def test_returns_rank_score(self, conn):
        remember(conn, "Dan likes coffee in the morning", type="preference")
        results = search_memories(conn, "coffee")
        assert len(results) >= 1
        assert "rank" in results[0]
        assert isinstance(results[0]["rank"], float)

    def test_respects_limit(self, conn):
        for i in range(10):
            remember(conn, f"Searchable memory number {i} with keyword", type="fact")
        results = search_memories(conn, "keyword", limit=3)
        assert len(results) <= 3

    def test_no_results_for_unknown_query(self, conn):
        remember(conn, "Normal memory content", type="fact")
        results = search_memories(conn, "zzzzunlikelytermzzzz")
        assert results == []


# ---------------------------------------------------------------------------
# print_list output (smoke test via capsys)
# ---------------------------------------------------------------------------

class TestPrintList:
    def test_prints_table_header(self, conn, capsys):
        remember(conn, "Some content", type="fact")
        memories = list_memories(conn)
        print_list(memories)
        out = capsys.readouterr().out
        assert "ID" in out
        assert "TYPE" in out
        assert "CONF" in out
        assert "CONTENT" in out

    def test_prints_memory_row(self, conn, capsys):
        remember(conn, "Dan prefers SQLite", type="preference")
        memories = list_memories(conn)
        print_list(memories)
        out = capsys.readouterr().out
        assert "preference" in out
        assert "Dan prefers SQLite" in out

    def test_empty_prints_message(self, conn, capsys):
        print_list([])
        out = capsys.readouterr().out
        assert "No memories" in out

    def test_long_content_truncated(self, conn, capsys):
        long_text = "A" * 200
        remember(conn, long_text, type="fact")
        memories = list_memories(conn)
        print_list(memories)
        out = capsys.readouterr().out
        # Should not print all 200 chars
        assert "A" * 200 not in out
        assert "..." in out


# ---------------------------------------------------------------------------
# print_search output
# ---------------------------------------------------------------------------

class TestPrintSearch:
    def test_prints_results(self, conn, capsys):
        remember(conn, "Dan uses SQLite for projects", type="preference")
        results = search_memories(conn, "SQLite")
        print_search(results, "SQLite")
        out = capsys.readouterr().out
        assert "SQLite" in out
        assert "score=" in out

    def test_no_results_message(self, conn, capsys):
        print_search([], "noresults")
        out = capsys.readouterr().out
        assert "No results" in out


# ---------------------------------------------------------------------------
# print_show output
# ---------------------------------------------------------------------------

class TestPrintShow:
    def test_shows_memory_details(self, conn, capsys):
        mid = remember(conn, "Dan works at Maxlerhof farm", type="fact", source="manual", tags=["farm"])
        print_show(conn, mid)
        out = capsys.readouterr().out
        assert "Dan works at Maxlerhof farm" in out
        assert "fact" in out
        assert "manual" in out
        assert "farm" in out

    def test_shows_supersession_chain(self, conn, capsys):
        old_id = remember(conn, "Dan uses Mac Mini", type="fact")
        new_id = supersede(conn, old_id, "Dan uses MacBook M4", type="fact")
        print_show(conn, new_id)
        out = capsys.readouterr().out
        assert "Dan uses MacBook M4" in out
        assert "Dan uses Mac Mini" in out or str(old_id) in out

    def test_shows_superseded_by(self, conn, capsys):
        old_id = remember(conn, "Old preference", type="preference")
        new_id = supersede(conn, old_id, "New preference", type="preference")
        # Show the old (deleted) memory — it should show what superseded it
        print_show(conn, old_id)
        out = capsys.readouterr().out
        # The old memory is shown, and the newer memory that replaced it is listed
        assert "Old preference" in out
        assert "New preference" in out or str(new_id) in out

    def test_returns_false_for_missing_id(self, conn, capsys):
        result = print_show(conn, 99999)
        assert result is False
        out = capsys.readouterr().out
        assert "No memory" in out

    def test_returns_true_for_found_id(self, conn):
        mid = remember(conn, "Test memory", type="fact")
        result = print_show(conn, mid)
        assert result is True


# ---------------------------------------------------------------------------
# CLI integration via subprocess
# ---------------------------------------------------------------------------

class TestCLISubcommands:
    """Smoke-test the subcommands through the CLI via subprocess."""

    def test_list_subcommand(self, conn_with_path):
        conn, db = conn_with_path
        remember(conn, "CLI test memory", type="fact")
        conn.commit()
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "list", "--db", str(db)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "fact" in result.stdout

    def test_list_with_type_filter(self, conn_with_path):
        conn, db = conn_with_path
        remember(conn, "A fact", type="fact")
        remember(conn, "A preference", type="preference")
        conn.commit()
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "list", "--type", "fact", "--db", str(db)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "fact" in result.stdout
        assert "preference" not in result.stdout

    def test_list_with_limit(self, conn_with_path):
        conn, db = conn_with_path
        for i in range(5):
            remember(conn, f"Memory {i}", type="fact")
        conn.commit()
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "list", "--limit", "3", "--db", str(db)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Should show 3 numbered rows (lines starting with a number)
        rows = [l for l in result.stdout.splitlines() if l.strip() and l.strip()[0].isdigit()]
        assert len(rows) == 3

    def test_search_subcommand(self, conn_with_path):
        conn, db = conn_with_path
        remember(conn, "Dan prefers SQLite over Postgres", type="preference")
        conn.commit()
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "search", "SQLite", "--db", str(db)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "SQLite" in result.stdout
        assert "score=" in result.stdout

    def test_show_subcommand(self, conn_with_path):
        conn, db = conn_with_path
        mid = remember(conn, "Testable memory content", type="fact", source="test")
        conn.commit()
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "show", str(mid), "--db", str(db)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Testable memory content" in result.stdout
        assert "fact" in result.stdout

    def test_show_nonexistent_exits_1(self, conn_with_path):
        conn, db = conn_with_path
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "show", "99999", "--db", str(db)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
