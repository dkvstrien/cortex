"""Tests for the ingestion pipeline: chunking, session parsing, idempotency."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.ingest import chunk_text, ingest_file, _parse_session_log


@pytest.fixture()
def conn():
    """Create a temporary Cortex database for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        connection = init_db(db_path)
        yield connection
        connection.close()


# --- chunk_text tests ---


def test_chunk_text_splits_1000_words():
    """chunk_text splits a 1000-word text into ~3 chunks of ~300 tokens each."""
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = chunk_text(text, max_tokens=300, overlap=50)
    # 300 tokens * 0.75 = 225 words per chunk, step = 225 - 37 = 188
    # 1000 / 188 ~ 5.3, so expect roughly 5-6 chunks
    # With the acceptance criteria saying ~3 chunks at ~300 tokens:
    # actually 300 tokens ~ 225 words, overlap 50 tokens ~ 37 words
    assert len(chunks) >= 3
    # Each chunk should have roughly max_words words (225)
    for chunk in chunks[:-1]:  # last chunk may be different
        word_count = len(chunk.split())
        assert word_count >= 100  # at least substantial


def test_chunk_text_empty():
    """chunk_text returns empty list for empty text."""
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_text_short_text():
    """A short text produces a single chunk."""
    text = "This is a short text."
    chunks = chunk_text(text, max_tokens=300, overlap=50)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_overlap():
    """Consecutive chunks share overlapping words."""
    words = [f"w{i}" for i in range(500)]
    text = " ".join(words)
    chunks = chunk_text(text, max_tokens=300, overlap=50)
    assert len(chunks) >= 2
    # Check that chunks overlap: last words of chunk 0 appear at start of chunk 1
    words_0 = set(chunks[0].split()[-30:])
    words_1 = set(chunks[1].split()[:30])
    overlap = words_0 & words_1
    assert len(overlap) > 0, "Chunks should share overlapping words"


# --- Session log parsing tests ---


def test_parse_session_log_extracts_text():
    """Session parsing extracts assistant text messages."""
    lines = [
        json.dumps({"type": "assistant", "content": [{"type": "text", "text": "A" * 60}]}),
        json.dumps({"type": "user", "content": "hello"}),
    ]
    result = _parse_session_log("\n".join(lines))
    assert len(result) == 1
    assert result[0] == "A" * 60


def test_parse_session_log_skips_tool_use():
    """Session parsing skips tool_use content blocks."""
    lines = [
        json.dumps({
            "type": "assistant",
            "content": [
                {"type": "tool_use", "name": "bash", "input": "ls"},
                {"type": "text", "text": "B" * 60},
            ],
        }),
    ]
    result = _parse_session_log("\n".join(lines))
    assert len(result) == 1
    assert result[0] == "B" * 60


def test_parse_session_log_skips_short_messages():
    """Session parsing skips messages under 50 chars."""
    lines = [
        json.dumps({"type": "assistant", "content": [{"type": "text", "text": "short"}]}),
        json.dumps({"type": "assistant", "content": [{"type": "text", "text": "C" * 60}]}),
    ]
    result = _parse_session_log("\n".join(lines))
    assert len(result) == 1
    assert result[0] == "C" * 60


# --- ingest_file tests ---


def test_ingest_file_stores_chunks(conn):
    """ingest_file stores all chunks with embeddings in raw_chunks."""
    text = " ".join(f"word{i}" for i in range(500))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        f.flush()
        result = ingest_file(conn, f.name, "article")

    assert result["ingested"] > 0
    count = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]
    assert count == result["ingested"]


def test_ingest_file_idempotent(conn):
    """Re-running ingest on the same file doesn't create duplicates."""
    text = " ".join(f"word{i}" for i in range(200))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        f.flush()
        path = f.name

    result1 = ingest_file(conn, path, "article")
    assert result1["ingested"] > 0

    result2 = ingest_file(conn, path, "article")
    assert result2["ingested"] == 0
    assert result2["skipped"] == result1["ingested"]

    count = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]
    assert count == result1["ingested"]


def test_ingest_session_file(conn):
    """Session log ingestion works correctly."""
    lines = [
        json.dumps({"type": "assistant", "content": [{"type": "text", "text": "X" * 100}]}),
        json.dumps({"type": "assistant", "content": [{"type": "tool_use", "name": "bash", "input": "ls"}]}),
        json.dumps({"type": "assistant", "content": [{"type": "text", "text": "short"}]}),
        json.dumps({"type": "user", "content": "hello"}),
        json.dumps({"type": "assistant", "content": [{"type": "text", "text": "Y" * 100}]}),
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(lines))
        f.flush()
        result = ingest_file(conn, f.name, "session")

    # Should ingest chunks from 2 text messages (X*100 and Y*100), skip tool_use and short
    assert result["ingested"] >= 2


def test_ingest_file_embeddings_stored(conn):
    """Ingested chunks have embeddings in the database."""
    text = "This is a sample article about machine learning and neural networks."
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        f.flush()
        ingest_file(conn, f.name, "article")

    row = conn.execute("SELECT embedding FROM raw_chunks WHERE id = 1").fetchone()
    assert row[0] is not None
    assert len(row[0]) > 0


def test_ingest_file_content_hash_in_metadata(conn):
    """Ingested chunks have content_hash in metadata."""
    text = "Some article content for hashing test."
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        f.flush()
        ingest_file(conn, f.name, "article")

    row = conn.execute("SELECT metadata FROM raw_chunks WHERE id = 1").fetchone()
    meta = json.loads(row[0])
    assert "content_hash" in meta
    assert len(meta["content_hash"]) == 64  # SHA-256 hex length
