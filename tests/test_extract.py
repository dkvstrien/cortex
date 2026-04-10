"""Tests for the extraction pipeline: raw chunks to curated memories."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import remember
from cortex.extract import extract_prompt, process_extraction, _get_unextracted_chunks


@pytest.fixture()
def conn():
    """Create a temporary Cortex database for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        connection = init_db(db_path)
        yield connection
        connection.close()


def _insert_raw_chunk(conn, content, source="test", source_type="article", created_at=None):
    """Insert a raw chunk directly (bypassing embeddings for speed)."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cursor = conn.execute(
        "INSERT INTO raw_chunks (content, source, source_type, created_at) VALUES (?, ?, ?, ?)",
        (content, source, source_type, created_at),
    )
    conn.commit()
    return cursor.lastrowid


# --- extract_prompt tests ---


def test_extract_prompt_no_chunks(conn):
    """extract_prompt returns None when there are no raw chunks."""
    result = extract_prompt(conn)
    assert result is None


def test_extract_prompt_generates_valid_prompt(conn):
    """extract_prompt generates a prompt listing raw chunks with IDs."""
    _insert_raw_chunk(conn, "Dan uses SQLite for everything")
    _insert_raw_chunk(conn, "Daimon is the Telegram bot running on ThinkPad")

    prompt = extract_prompt(conn, scope="all")
    assert prompt is not None
    assert "[ID 1]" in prompt
    assert "[ID 2]" in prompt
    assert "Dan uses SQLite" in prompt
    assert "Daimon is the Telegram bot" in prompt


def test_extract_prompt_instructs_json_output(conn):
    """The prompt instructs the LLM to output JSON with typed memories."""
    _insert_raw_chunk(conn, "Some content to extract from")

    prompt = extract_prompt(conn, scope="all")
    assert "raw_chunk_ids" in prompt
    assert "content" in prompt
    assert '"type"' in prompt
    assert "JSON" in prompt
    assert "decision" in prompt
    assert "preference" in prompt
    assert "entity" in prompt


def test_extract_prompt_scope_recent(conn):
    """scope='recent' only returns chunks from last 24 hours."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    new_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    _insert_raw_chunk(conn, "Old chunk", created_at=old_time)
    _insert_raw_chunk(conn, "New chunk", created_at=new_time)

    prompt = extract_prompt(conn, scope="recent")
    assert prompt is not None
    assert "New chunk" in prompt
    assert "Old chunk" not in prompt


def test_extract_prompt_scope_all(conn):
    """scope='all' returns all unextracted chunks regardless of age."""
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    _insert_raw_chunk(conn, "Old chunk", created_at=old_time)
    _insert_raw_chunk(conn, "New chunk")

    prompt = extract_prompt(conn, scope="all")
    assert prompt is not None
    assert "Old chunk" in prompt
    assert "New chunk" in prompt


def test_extract_prompt_skips_already_extracted(conn):
    """Already-extracted chunks are not included in the prompt."""
    chunk_id = _insert_raw_chunk(conn, "Already extracted content")
    _insert_raw_chunk(conn, "Not yet extracted content")

    # Simulate extraction: create a curated memory and link it
    conn.execute(
        "INSERT INTO curated_memories (content, type) VALUES (?, ?)",
        ("Extracted memory", "fact"),
    )
    memory_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO extractions (raw_chunk_id, curated_memory_id) VALUES (?, ?)",
        (chunk_id, memory_id),
    )
    conn.commit()

    prompt = extract_prompt(conn, scope="all")
    assert prompt is not None
    assert "Already extracted content" not in prompt
    assert "Not yet extracted content" in prompt


# --- process_extraction tests ---


def test_process_extraction_creates_memories(conn):
    """process_extraction creates curated memories from extraction JSON."""
    chunk_id = _insert_raw_chunk(conn, "Dan uses SQLite for everything")

    extraction = [
        {
            "raw_chunk_ids": [chunk_id],
            "content": "Dan prefers SQLite over PostgreSQL",
            "type": "preference",
        }
    ]

    result = process_extraction(conn, extraction)
    assert result["memories_created"] == 1
    assert result["extractions_linked"] == 1

    # Verify curated memory was created
    row = conn.execute(
        "SELECT content, type, source FROM curated_memories WHERE source = 'extraction'"
    ).fetchone()
    assert row is not None
    assert row[0] == "Dan prefers SQLite over PostgreSQL"
    assert row[1] == "preference"
    assert row[2] == "extraction"


def test_process_extraction_creates_links(conn):
    """Each extraction links a raw_chunk_id to a curated_memory_id."""
    c1 = _insert_raw_chunk(conn, "Chunk one")
    c2 = _insert_raw_chunk(conn, "Chunk two")

    extraction = [
        {
            "raw_chunk_ids": [c1, c2],
            "content": "Combined memory from two chunks",
            "type": "fact",
        }
    ]

    result = process_extraction(conn, extraction)
    assert result["extractions_linked"] == 2

    links = conn.execute(
        "SELECT raw_chunk_id, curated_memory_id FROM extractions ORDER BY raw_chunk_id"
    ).fetchall()
    assert len(links) == 2
    assert links[0][0] == c1
    assert links[1][0] == c2
    # Both should point to the same curated memory
    assert links[0][1] == links[1][1]


def test_process_extraction_from_json_string(conn):
    """process_extraction accepts a JSON string as input."""
    chunk_id = _insert_raw_chunk(conn, "Some content")

    json_str = json.dumps([
        {
            "raw_chunk_ids": [chunk_id],
            "content": "A memory from JSON string",
            "type": "entity",
        }
    ])

    result = process_extraction(conn, json_str)
    assert result["memories_created"] == 1


def test_process_extraction_skips_already_extracted(conn):
    """Already-extracted chunks are skipped during processing."""
    chunk_id = _insert_raw_chunk(conn, "Already processed content")

    # First extraction
    extraction = [
        {
            "raw_chunk_ids": [chunk_id],
            "content": "First extraction",
            "type": "fact",
        }
    ]
    result1 = process_extraction(conn, extraction)
    assert result1["memories_created"] == 1

    # Second extraction referencing same chunk — should be skipped
    extraction2 = [
        {
            "raw_chunk_ids": [chunk_id],
            "content": "Duplicate extraction",
            "type": "fact",
        }
    ]
    result2 = process_extraction(conn, extraction2)
    assert result2["memories_created"] == 0
    assert result2["extractions_linked"] == 0


def test_process_extraction_invalid_type_defaults_to_fact(conn):
    """Invalid memory types are defaulted to 'fact'."""
    chunk_id = _insert_raw_chunk(conn, "Content")

    extraction = [
        {
            "raw_chunk_ids": [chunk_id],
            "content": "Memory with bad type",
            "type": "invalid_type",
        }
    ]

    result = process_extraction(conn, extraction)
    assert result["memories_created"] == 1

    row = conn.execute(
        "SELECT type FROM curated_memories WHERE content = 'Memory with bad type'"
    ).fetchone()
    assert row[0] == "fact"


def test_process_extraction_skips_empty_content(conn):
    """Extraction items with empty content are skipped."""
    chunk_id = _insert_raw_chunk(conn, "Content")

    extraction = [
        {"raw_chunk_ids": [chunk_id], "content": "", "type": "fact"},
        {"raw_chunk_ids": [chunk_id], "content": "   ", "type": "fact"},
    ]

    result = process_extraction(conn, extraction)
    assert result["memories_created"] == 0


def test_process_extraction_empty_list(conn):
    """Processing an empty list creates nothing."""
    result = process_extraction(conn, [])
    assert result["memories_created"] == 0
    assert result["extractions_linked"] == 0


def test_process_extraction_invalid_json_raises(conn):
    """Invalid JSON string raises ValueError."""
    with pytest.raises((json.JSONDecodeError, ValueError)):
        process_extraction(conn, "not valid json")


def test_extract_prompt_includes_existing_memories_section(conn):
    """extract_prompt includes EXISTING RELATED MEMORIES section when curated memories exist."""
    # Store an existing curated memory
    remember(conn, "Dan prefers Postgres for all databases", type="preference")

    # Add a raw chunk
    _insert_raw_chunk(conn, "Dan switched to SQLite exclusively")

    prompt = extract_prompt(conn, scope="all")
    assert prompt is not None
    assert "EXISTING RELATED MEMORIES" in prompt
    assert "[EXISTING #" in prompt
    assert "Dan prefers Postgres" in prompt


def test_extract_prompt_omits_existing_section_when_no_matches(conn):
    """extract_prompt omits EXISTING section when no curated memories exist."""
    _insert_raw_chunk(conn, "Some completely unrelated chunk content here")

    prompt = extract_prompt(conn, scope="all")
    assert prompt is not None
    # No curated memories stored, so no EXISTING section
    assert "EXISTING RELATED MEMORIES" not in prompt
    assert "[EXISTING #" not in prompt


def test_extract_prompt_includes_supersedes_instructions(conn):
    """When existing memories are present, the prompt mentions the supersedes field."""
    remember(conn, "Dan prefers Postgres for all databases", type="preference")
    _insert_raw_chunk(conn, "Dan switched to SQLite exclusively")

    prompt = extract_prompt(conn, scope="all")
    assert "supersedes" in prompt


def test_process_extraction_supersedes_old_memory(conn):
    """process_extraction calls supersede() when the supersedes field is present.

    Scenario: store 'Dan prefers Postgres', then process an extraction with a
    chunk saying 'Dan switched to SQLite exclusively'. The old memory should be
    soft-deleted and a new one created.
    """
    # Store existing curated memory
    old_id = remember(conn, "Dan prefers Postgres", type="preference")

    # Store a raw chunk that contradicts it
    chunk_id = _insert_raw_chunk(conn, "Dan switched to SQLite exclusively")

    # Simulate LLM extraction output with supersedes field
    extraction = [
        {
            "raw_chunk_ids": [chunk_id],
            "content": "Dan switched to SQLite exclusively",
            "type": "preference",
            "supersedes": old_id,
        }
    ]

    result = process_extraction(conn, extraction)
    assert result["memories_created"] == 1

    # Old memory should be soft-deleted
    old_row = conn.execute(
        "SELECT deleted_at FROM curated_memories WHERE id = ?", (old_id,)
    ).fetchone()
    assert old_row is not None
    assert old_row[0] is not None, "Old memory should have deleted_at set"

    # New memory should exist and point back to old one
    new_row = conn.execute(
        "SELECT content, supersedes_id FROM curated_memories WHERE supersedes_id = ?",
        (old_id,),
    ).fetchone()
    assert new_row is not None
    assert "SQLite" in new_row[0]
    assert new_row[1] == old_id


def test_process_extraction_supersedes_missing_id_falls_back_to_remember(conn):
    """If the supersedes ID doesn't exist, fall back to creating a normal memory."""
    chunk_id = _insert_raw_chunk(conn, "Dan switched to SQLite exclusively")

    extraction = [
        {
            "raw_chunk_ids": [chunk_id],
            "content": "Dan uses SQLite now",
            "type": "preference",
            "supersedes": 99999,  # non-existent
        }
    ]

    result = process_extraction(conn, extraction)
    assert result["memories_created"] == 1

    row = conn.execute(
        "SELECT content FROM curated_memories WHERE content = 'Dan uses SQLite now'"
    ).fetchone()
    assert row is not None


def test_process_extraction_uses_session_id_as_source(conn):
    """process_extraction sets curated_memories.source to session_id, not 'extraction'."""
    # Insert a raw chunk with a session source
    conn.execute(
        """INSERT INTO raw_chunks (id, content, source, source_type)
           VALUES (999, 'Test content for memory extraction', 'staging:2026-04-09.jsonl:my-session-id', 'session')"""
    )
    conn.commit()

    extraction_json = json.dumps([{
        "raw_chunk_ids": [999],
        "content": "Test memory content that is long enough",
        "type": "fact"
    }])
    process_extraction(conn, extraction_json)

    row = conn.execute(
        "SELECT source FROM curated_memories WHERE content = 'Test memory content that is long enough'"
    ).fetchone()
    assert row is not None
    assert row[0] == "my-session-id"


def test_full_round_trip(conn):
    """End-to-end: insert chunks, generate prompt, process extraction, verify skipped."""
    # Insert some chunks
    c1 = _insert_raw_chunk(conn, "Dan runs a dairy farm called Maxlerhof")
    c2 = _insert_raw_chunk(conn, "The ThinkPad is the home server running services")
    c3 = _insert_raw_chunk(conn, "Syncthing syncs files between Mac and ThinkPad")

    # Generate prompt
    prompt = extract_prompt(conn, scope="all")
    assert prompt is not None
    assert "[ID" in prompt

    # Simulate LLM output
    extraction = [
        {
            "raw_chunk_ids": [c1],
            "content": "Maxlerhof is Dan's dairy farm",
            "type": "entity",
        },
        {
            "raw_chunk_ids": [c2, c3],
            "content": "ThinkPad serves as home server; Syncthing keeps files in sync with Mac",
            "type": "fact",
        },
    ]

    result = process_extraction(conn, extraction)
    assert result["memories_created"] == 2
    assert result["extractions_linked"] == 3

    # Now those chunks should not appear in a new prompt
    prompt2 = extract_prompt(conn, scope="all")
    assert prompt2 is None  # All chunks extracted

    # Verify extraction entries
    count = conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0]
    assert count == 3
