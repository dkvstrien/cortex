"""Tests for cortex export and import (port.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import remember, forget
from cortex.port import export_memories, import_memories


@pytest.fixture
def conn(tmp_path: Path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def conn_a(tmp_path: Path):
    c = init_db(tmp_path / "a.db")
    yield c
    c.close()


@pytest.fixture
def conn_b(tmp_path: Path):
    c = init_db(tmp_path / "b.db")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# export_memories
# ---------------------------------------------------------------------------

def test_export_empty_db(conn):
    """Export of a fresh DB returns an empty list."""
    assert export_memories(conn) == []


def test_export_returns_non_deleted(conn):
    """Export includes only non-deleted memories."""
    id1 = remember(conn, "keep this", type="fact")
    id2 = remember(conn, "delete this", type="fact")
    forget(conn, id2)

    exported = export_memories(conn)
    assert len(exported) == 1
    assert exported[0]["content"] == "keep this"


def test_export_fields(conn):
    """Each exported object includes the required fields."""
    remember(conn, "Dan uses uv", type="preference", source="manual", tags=["python", "tools"])
    exported = export_memories(conn)
    assert len(exported) == 1
    mem = exported[0]
    required_fields = {"id", "content", "type", "source", "tags", "confidence", "created_at", "updated_at", "supersedes_id"}
    assert required_fields.issubset(mem.keys())
    assert mem["content"] == "Dan uses uv"
    assert mem["type"] == "preference"
    assert mem["source"] == "manual"
    assert mem["tags"] == ["python", "tools"]
    assert mem["confidence"] == 1.0
    assert mem["supersedes_id"] is None


def test_export_skips_deleted_at_field(conn):
    """Exported dicts should not include the deleted_at field."""
    remember(conn, "some memory", type="fact")
    exported = export_memories(conn)
    assert "deleted_at" not in exported[0]


def test_export_multiple_memories_ordered_by_id(conn):
    """Export returns memories ordered by id ascending."""
    id1 = remember(conn, "first", type="fact")
    id2 = remember(conn, "second", type="fact")
    id3 = remember(conn, "third", type="fact")
    exported = export_memories(conn)
    ids = [m["id"] for m in exported]
    assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# import_memories
# ---------------------------------------------------------------------------

def test_import_basic(conn):
    """Import inserts memories from a list of dicts."""
    memories = [
        {"content": "Dan lives in Vienna", "type": "fact", "source": "manual",
         "tags": ["location"], "confidence": 1.0, "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "supersedes_id": None},
    ]
    result = import_memories(conn, memories)
    assert result["imported"] == 1
    assert result["skipped"] == 0

    rows = conn.execute(
        "SELECT content, type, source FROM curated_memories WHERE deleted_at IS NULL"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Dan lives in Vienna"


def test_import_idempotent(conn):
    """Importing the same list twice creates no duplicates."""
    memories = [
        {"content": "Dan prefers dark mode", "type": "preference", "source": "manual",
         "tags": [], "confidence": 1.0, "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "supersedes_id": None},
    ]
    result1 = import_memories(conn, memories)
    result2 = import_memories(conn, memories)

    assert result1["imported"] == 1
    assert result1["skipped"] == 0
    assert result2["imported"] == 0
    assert result2["skipped"] == 1

    count = conn.execute(
        "SELECT COUNT(*) FROM curated_memories WHERE deleted_at IS NULL"
    ).fetchone()[0]
    assert count == 1


def test_import_same_content_different_type_not_skipped(conn):
    """Same content but different type is treated as a distinct memory."""
    memories_a = [
        {"content": "shared content", "type": "fact", "source": "manual",
         "tags": [], "confidence": 1.0, "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "supersedes_id": None},
    ]
    memories_b = [
        {"content": "shared content", "type": "preference", "source": "manual",
         "tags": [], "confidence": 1.0, "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "supersedes_id": None},
    ]
    result_a = import_memories(conn, memories_a)
    result_b = import_memories(conn, memories_b)
    assert result_a["imported"] == 1
    assert result_b["imported"] == 1


def test_import_skips_count(conn):
    """Import correctly counts skipped entries."""
    memories = [
        {"content": "memory one", "type": "fact", "source": None,
         "tags": [], "confidence": 1.0, "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "supersedes_id": None},
        {"content": "memory two", "type": "fact", "source": None,
         "tags": [], "confidence": 1.0, "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "supersedes_id": None},
        {"content": "memory three", "type": "fact", "source": None,
         "tags": [], "confidence": 1.0, "created_at": "2026-01-01T00:00:00Z",
         "updated_at": "2026-01-01T00:00:00Z", "supersedes_id": None},
    ]
    import_memories(conn, memories)
    # Import again — all 3 should be skipped
    result = import_memories(conn, memories)
    assert result["imported"] == 0
    assert result["skipped"] == 3


# ---------------------------------------------------------------------------
# Round-trip test: export from A, import into B
# ---------------------------------------------------------------------------

def test_round_trip(conn_a, conn_b):
    """Export from DB A, import into DB B — all memories present and identical."""
    remember(conn_a, "Dan prefers SQLite", type="preference", source="manual", tags=["db"])
    remember(conn_a, "Dan uses uv for Python", type="procedure", source="manual", tags=["python"])
    remember(conn_a, "Farm has 42 cows", type="fact", source="manual")

    exported = export_memories(conn_a)
    assert len(exported) == 3

    result = import_memories(conn_b, exported)
    assert result["imported"] == 3
    assert result["skipped"] == 0

    imported_in_b = export_memories(conn_b)
    assert len(imported_in_b) == 3

    # Content and types match (IDs may differ)
    contents_a = {(m["content"], m["type"]) for m in exported}
    contents_b = {(m["content"], m["type"]) for m in imported_in_b}
    assert contents_a == contents_b


def test_round_trip_excludes_deleted(conn_a, conn_b):
    """Deleted memories in A are not exported and therefore not present in B."""
    id1 = remember(conn_a, "active memory", type="fact")
    id2 = remember(conn_a, "deleted memory", type="fact")
    forget(conn_a, id2)

    exported = export_memories(conn_a)
    assert len(exported) == 1

    import_memories(conn_b, exported)
    in_b = export_memories(conn_b)
    assert len(in_b) == 1
    assert in_b[0]["content"] == "active memory"


def test_round_trip_idempotent(conn_a, conn_b):
    """Importing the same export twice into B produces no duplicates."""
    remember(conn_a, "idempotency check", type="fact", source="test")
    exported = export_memories(conn_a)

    import_memories(conn_b, exported)
    result2 = import_memories(conn_b, exported)
    assert result2["imported"] == 0
    assert result2["skipped"] == 1

    count = conn_b.execute(
        "SELECT COUNT(*) FROM curated_memories WHERE deleted_at IS NULL"
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

def test_cli_export(tmp_path: Path):
    """CLI export command outputs valid JSON array."""
    db = tmp_path / "cli.db"
    conn = init_db(str(db))
    remember(conn, "CLI test memory", type="fact", source="test")
    conn.close()

    result = subprocess.run(
        [sys.executable, "-m", "cortex", "export", "--db", str(db)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["content"] == "CLI test memory"


def test_cli_import(tmp_path: Path):
    """CLI import command reads JSON from stdin and inserts memories."""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    conn_a = init_db(str(db_a))
    remember(conn_a, "CLI import test", type="fact", source="test")
    conn_a.close()

    # Export from A
    export_result = subprocess.run(
        [sys.executable, "-m", "cortex", "export", "--db", str(db_a)],
        capture_output=True, text=True,
    )
    assert export_result.returncode == 0

    # Import into B
    import_result = subprocess.run(
        [sys.executable, "-m", "cortex", "import", "--db", str(db_b)],
        input=export_result.stdout,
        capture_output=True, text=True,
    )
    assert import_result.returncode == 0
    assert "1 imported" in import_result.stdout
    assert "0 skipped" in import_result.stdout

    conn_b = init_db(str(db_b))
    in_b = export_memories(conn_b)
    conn_b.close()
    assert len(in_b) == 1
    assert in_b[0]["content"] == "CLI import test"


def test_cli_import_idempotent(tmp_path: Path):
    """CLI import twice reports skipped on second run."""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    conn_a = init_db(str(db_a))
    remember(conn_a, "idempotent CLI test", type="fact")
    conn_a.close()

    export_result = subprocess.run(
        [sys.executable, "-m", "cortex", "export", "--db", str(db_a)],
        capture_output=True, text=True,
    )

    # First import
    subprocess.run(
        [sys.executable, "-m", "cortex", "import", "--db", str(db_b)],
        input=export_result.stdout,
        capture_output=True, text=True,
    )
    # Second import
    import_result2 = subprocess.run(
        [sys.executable, "-m", "cortex", "import", "--db", str(db_b)],
        input=export_result.stdout,
        capture_output=True, text=True,
    )
    assert import_result2.returncode == 0
    assert "0 imported" in import_result2.stdout
    assert "1 skipped" in import_result2.stdout
