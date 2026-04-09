"""Tests for the Cortex MCP server."""

from __future__ import annotations

import os
import tempfile

import pytest


def test_server_imports():
    """Server module can be imported without errors."""
    from cortex.server import mcp, remember, recall, forget, supersede, status


def test_server_has_exactly_five_tools():
    """Server exposes exactly 5 tools: remember, recall, forget, supersede, status."""
    from cortex.server import mcp

    # FastMCP stores tools internally; list them
    tools = mcp._tool_manager._tools
    tool_names = sorted(tools.keys())
    assert tool_names == ["forget", "recall", "remember", "status", "supersede"]


def test_remember_tool_curated(tmp_path):
    """remember tool stores a curated memory and returns its ID."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    result = srv.remember("test memory", type="fact", tags=["test"], layer="curated")
    assert result["status"] == "stored"
    assert result["layer"] == "curated"
    assert isinstance(result["id"], int)


def test_recall_tool(tmp_path):
    """recall tool retrieves stored memories."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    # Store something first
    srv.remember("SQLite is a great database", type="fact", layer="curated")

    # Recall it
    result = srv.recall("database", layer="curated")
    assert result["count"] >= 1
    assert len(result["results"]) >= 1


def test_forget_tool(tmp_path):
    """forget tool soft-deletes a memory."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    # Store and forget
    stored = srv.remember("temporary memory", type="fact", layer="curated")
    memory_id = stored["id"]

    result = srv.forget(memory_id)
    assert result["status"] == "forgotten"
    assert result["id"] == memory_id


def test_forget_nonexistent(tmp_path):
    """forget tool returns error for nonexistent ID."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    # Init DB by doing a status call
    srv.status()

    result = srv.forget(99999)
    assert "error" in result


def test_status_tool(tmp_path):
    """status tool returns the health dashboard."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    result = srv.status()
    assert "curated_count" in result
    assert "raw_count" in result
    assert isinstance(result["curated_count"], int)


def test_remember_invalid_layer(tmp_path):
    """remember tool returns error for invalid layer."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    result = srv.remember("test", layer="invalid")
    assert "error" in result


def test_db_path_from_env(tmp_path, monkeypatch):
    """CORTEX_DB_PATH environment variable controls database location."""
    db_path = str(tmp_path / "env_test.db")
    monkeypatch.setenv("CORTEX_DB_PATH", db_path)

    # Re-import to pick up new env var
    import importlib
    import cortex.server as srv

    importlib.reload(srv)

    assert srv._db_path == db_path

    # Clean up: reload with original env
    monkeypatch.delenv("CORTEX_DB_PATH", raising=False)
    importlib.reload(srv)


def test_create_server():
    """create_server produces a working FastMCP instance with all 5 tools."""
    from cortex.server import create_server

    server = create_server(port=9999)
    tools = server._tool_manager._tools
    tool_names = sorted(tools.keys())
    assert tool_names == ["forget", "recall", "remember", "status", "supersede"]


def test_supersede_tool_end_to_end(tmp_path):
    """supersede tool replaces an old memory and returns old_id/new_id/status."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    # Store an initial memory
    stored = srv.remember("Dan prefers Postgres", type="preference", layer="curated")
    old_id = stored["id"]

    # Supersede it with updated content
    result = srv.supersede(old_id, "Dan prefers SQLite over Postgres")
    assert result["status"] == "superseded"
    assert result["old_id"] == old_id
    assert isinstance(result["new_id"], int)
    assert result["new_id"] != old_id

    # Old memory should no longer appear in recall
    recall_result = srv.recall("database preference", layer="curated")
    ids_returned = [r["id"] for r in recall_result["results"]]
    assert old_id not in ids_returned

    # New memory should appear
    assert result["new_id"] in ids_returned


def test_supersede_tool_nonexistent(tmp_path):
    """supersede returns an error for a nonexistent old_id."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    # Init DB
    srv.status()

    result = srv.supersede(99999, "some new content")
    assert "error" in result


def test_supersede_tool_type_override(tmp_path):
    """supersede with explicit type stores the new memory with the given type."""
    import cortex.server as srv

    db_path = str(tmp_path / "test.db")
    srv._db_path = db_path

    stored = srv.remember("Dan uses Vienna timezone", type="fact", layer="curated")
    old_id = stored["id"]

    result = srv.supersede(old_id, "Dan lives in Vienna, Austria", type="preference")
    assert result["status"] == "superseded"

    # Verify new memory has correct type via recall with type filter
    recall_result = srv.recall("Vienna Austria", type="preference", layer="curated")
    ids_returned = [r["id"] for r in recall_result["results"]]
    assert result["new_id"] in ids_returned
