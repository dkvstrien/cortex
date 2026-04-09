"""Tests for the reflect pipeline: insight synthesis from curated memories."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import remember
from cortex.reflect import (
    reflect_prompt,
    process_reflection,
    _get_reflected_ids,
    _save_reflected_ids,
)


@pytest.fixture()
def conn():
    """Create a temporary Cortex database for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        connection = init_db(db_path)
        yield connection
        connection.close()


def _store_memory(conn, content, mem_type="preference", source="manual", tags=None):
    """Helper: store a curated memory and return its ID."""
    return remember(conn, content, type=mem_type, source=source, tags=tags)


# --- reflect_prompt tests ---


def test_reflect_prompt_no_memories(conn):
    """reflect_prompt returns None when there are no curated memories."""
    result = reflect_prompt(conn)
    assert result is None


def test_reflect_prompt_generates_prompt_with_memories(conn):
    """reflect_prompt generates a prompt that includes the stored memories."""
    _store_memory(conn, "Dan prefers SQLite over PostgreSQL", "preference")
    _store_memory(conn, "Dan uses uv for Python projects", "preference")
    _store_memory(conn, "Maxlerhof is Dan's dairy farm", "entity")

    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "Dan prefers SQLite over PostgreSQL" in prompt
    assert "Dan uses uv for Python projects" in prompt
    assert "Maxlerhof is Dan's dairy farm" in prompt


def test_reflect_prompt_groups_by_type(conn):
    """reflect_prompt groups memories under their type headings."""
    _store_memory(conn, "Dan prefers local tools", "preference")
    _store_memory(conn, "Dan decided to use ThinkPad as server", "decision")

    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "PREFERENCE" in prompt
    assert "DECISION" in prompt


def test_reflect_prompt_includes_memory_ids(conn):
    """reflect_prompt includes IDs so the LLM can reference them in source_ids."""
    id1 = _store_memory(conn, "First memory", "fact")
    id2 = _store_memory(conn, "Second memory", "fact")

    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert f"[ID {id1}]" in prompt
    assert f"[ID {id2}]" in prompt


def test_reflect_prompt_three_related_memories_appear(conn):
    """AC: store 3 related memories, run reflect prompt, confirm they appear."""
    _store_memory(conn, "Dan prefers SQLite for simplicity", "preference")
    _store_memory(conn, "Dan chose uv over pip for speed", "decision")
    _store_memory(conn, "Dan runs services locally instead of cloud", "preference")

    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "Dan prefers SQLite for simplicity" in prompt
    assert "Dan chose uv over pip for speed" in prompt
    assert "Dan runs services locally instead of cloud" in prompt


def test_reflect_prompt_excludes_already_reflected_ids(conn):
    """Memories already in reflected_ids meta are excluded from prompt."""
    id1 = _store_memory(conn, "Old preference already reflected", "preference")
    _store_memory(conn, "New preference not yet reflected", "preference")

    # Mark id1 as already reflected
    _save_reflected_ids(conn, {id1})

    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "Old preference already reflected" not in prompt
    assert "New preference not yet reflected" in prompt


def test_reflect_prompt_excludes_insight_memories(conn):
    """Memories created by reflect (type=insight, source=reflect) are not re-reflected."""
    _store_memory(conn, "Dan values simplicity", "preference")
    # Simulate an existing insight
    remember(conn, "Existing insight memory", type="insight", source="reflect")

    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "Existing insight memory" not in prompt
    assert "Dan values simplicity" in prompt


def test_reflect_prompt_excludes_soft_deleted_memories(conn):
    """Soft-deleted memories are not included in reflect prompt."""
    from cortex.curated import forget

    id1 = _store_memory(conn, "This memory will be deleted", "fact")
    _store_memory(conn, "This memory stays", "fact")

    forget(conn, id1)

    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "This memory will be deleted" not in prompt
    assert "This memory stays" in prompt


def test_reflect_prompt_returns_none_all_reflected(conn):
    """reflect_prompt returns None when all memories are already reflected."""
    id1 = _store_memory(conn, "Memory one", "preference")
    id2 = _store_memory(conn, "Memory two", "fact")

    _save_reflected_ids(conn, {id1, id2})

    result = reflect_prompt(conn)
    assert result is None


# --- process_reflection tests ---


def test_process_reflection_creates_insight_memories(conn):
    """process_reflection creates memories with type='insight' and source='reflect'."""
    id1 = _store_memory(conn, "Dan prefers SQLite", "preference")
    id2 = _store_memory(conn, "Dan uses local tools", "preference")

    reflection = [
        {
            "content": "Dan consistently chooses simplicity over scalability",
            "type": "insight",
            "source_ids": [id1, id2],
        }
    ]

    result = process_reflection(conn, reflection)
    assert result["insights_created"] == 1
    assert result["source_ids_tracked"] == 2

    row = conn.execute(
        "SELECT content, type, source FROM curated_memories WHERE type = 'insight'"
    ).fetchone()
    assert row is not None
    assert row[0] == "Dan consistently chooses simplicity over scalability"
    assert row[1] == "insight"
    assert row[2] == "reflect"


def test_process_reflection_stores_source_ids_in_tags(conn):
    """Source IDs are stored in the tags field as source:<id> entries."""
    id1 = _store_memory(conn, "Memory A", "fact")
    id2 = _store_memory(conn, "Memory B", "fact")

    reflection = [
        {
            "content": "Pattern from A and B",
            "type": "insight",
            "source_ids": [id1, id2],
        }
    ]

    process_reflection(conn, reflection)

    row = conn.execute(
        "SELECT tags FROM curated_memories WHERE type = 'insight'"
    ).fetchone()
    assert row is not None
    tags = json.loads(row[0])
    assert f"source:{id1}" in tags
    assert f"source:{id2}" in tags


def test_process_reflection_tracks_source_ids_in_meta(conn):
    """process_reflection records source_ids in the meta table."""
    id1 = _store_memory(conn, "Memory A", "preference")
    id2 = _store_memory(conn, "Memory B", "decision")

    reflection = [
        {
            "content": "Insight from A and B",
            "type": "insight",
            "source_ids": [id1, id2],
        }
    ]

    process_reflection(conn, reflection)

    reflected = _get_reflected_ids(conn)
    assert id1 in reflected
    assert id2 in reflected


def test_process_reflection_from_json_string(conn):
    """process_reflection accepts a JSON string as input."""
    id1 = _store_memory(conn, "Some memory", "fact")

    json_str = json.dumps([
        {
            "content": "Insight from string input",
            "type": "insight",
            "source_ids": [id1],
        }
    ])

    result = process_reflection(conn, json_str)
    assert result["insights_created"] == 1


def test_process_reflection_skips_empty_content(conn):
    """Items with empty content are skipped."""
    id1 = _store_memory(conn, "Memory", "fact")

    reflection = [
        {"content": "", "type": "insight", "source_ids": [id1]},
        {"content": "   ", "type": "insight", "source_ids": [id1]},
    ]

    result = process_reflection(conn, reflection)
    assert result["insights_created"] == 0


def test_process_reflection_empty_list(conn):
    """Processing an empty list creates nothing."""
    result = process_reflection(conn, [])
    assert result["insights_created"] == 0
    assert result["source_ids_tracked"] == 0


def test_process_reflection_invalid_json_raises(conn):
    """Invalid JSON string raises an error."""
    with pytest.raises((json.JSONDecodeError, ValueError)):
        process_reflection(conn, "not valid json")


def test_process_reflection_multiple_insights(conn):
    """Multiple insights are all created."""
    id1 = _store_memory(conn, "Memory 1", "preference")
    id2 = _store_memory(conn, "Memory 2", "preference")
    id3 = _store_memory(conn, "Memory 3", "decision")

    reflection = [
        {
            "content": "Insight about preferences",
            "type": "insight",
            "source_ids": [id1, id2],
        },
        {
            "content": "Insight about decisions",
            "type": "insight",
            "source_ids": [id3],
        },
    ]

    result = process_reflection(conn, reflection)
    assert result["insights_created"] == 2
    assert result["source_ids_tracked"] == 3


# --- meta table tracking tests ---


def test_reflected_ids_persist_across_calls(conn):
    """reflected_ids accumulate across multiple process_reflection calls."""
    id1 = _store_memory(conn, "Memory 1", "fact")
    id2 = _store_memory(conn, "Memory 2", "fact")
    id3 = _store_memory(conn, "Memory 3", "fact")

    process_reflection(conn, [
        {"content": "Insight 1", "type": "insight", "source_ids": [id1]},
    ])
    process_reflection(conn, [
        {"content": "Insight 2", "type": "insight", "source_ids": [id2, id3]},
    ])

    reflected = _get_reflected_ids(conn)
    assert id1 in reflected
    assert id2 in reflected
    assert id3 in reflected


def test_reflected_ids_exclude_from_next_prompt(conn):
    """After process_reflection, reflected source memories are excluded from future prompts."""
    id1 = _store_memory(conn, "Already reflected memory", "preference")
    id2 = _store_memory(conn, "Not yet reflected memory", "preference")

    # Reflect the first one
    process_reflection(conn, [
        {"content": "Insight", "type": "insight", "source_ids": [id1]},
    ])

    # id2 not yet reflected, should appear in prompt
    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "Already reflected memory" not in prompt
    assert "Not yet reflected memory" in prompt


def test_get_reflected_ids_empty_when_no_meta(conn):
    """_get_reflected_ids returns empty set when meta table has no entry."""
    result = _get_reflected_ids(conn)
    assert result == set()


def test_save_and_get_reflected_ids_round_trip(conn):
    """_save_reflected_ids and _get_reflected_ids are consistent."""
    ids = {1, 5, 42, 100}
    _save_reflected_ids(conn, ids)
    result = _get_reflected_ids(conn)
    assert result == ids


# --- full round-trip test ---


def test_full_round_trip(conn):
    """End-to-end: store memories, generate prompt, process reflection, verify tracking."""
    id1 = _store_memory(conn, "Dan prefers SQLite over Postgres", "preference")
    id2 = _store_memory(conn, "Dan uses uv not pip", "preference")
    id3 = _store_memory(conn, "Dan chose ThinkPad as home server", "decision")

    # Generate prompt
    prompt = reflect_prompt(conn)
    assert prompt is not None
    assert "Dan prefers SQLite" in prompt
    assert "Dan uses uv" in prompt
    assert "Dan chose ThinkPad" in prompt

    # Simulate Haiku output
    haiku_output = [
        {
            "content": "Dan consistently prefers simple, local, self-hosted solutions",
            "type": "insight",
            "source_ids": [id1, id2, id3],
        }
    ]

    result = process_reflection(conn, haiku_output)
    assert result["insights_created"] == 1
    assert result["source_ids_tracked"] == 3

    # Verify insight was stored
    insight = conn.execute(
        "SELECT content, type, source FROM curated_memories WHERE type = 'insight'"
    ).fetchone()
    assert insight is not None
    assert insight[1] == "insight"
    assert insight[2] == "reflect"

    # Verify source IDs are tracked
    reflected = _get_reflected_ids(conn)
    assert {id1, id2, id3}.issubset(reflected)

    # Now those memories shouldn't appear in the next prompt
    prompt2 = reflect_prompt(conn)
    assert prompt2 is None  # all memories reflected
