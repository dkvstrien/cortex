"""Tests for the raw chunks layer: store_chunk and recall_raw."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.raw import recall_raw, store_chunk


@pytest.fixture()
def conn():
    """Create a temporary Cortex database for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        connection = init_db(db_path)
        yield connection
        connection.close()


def test_store_chunk_returns_id(conn):
    """store_chunk stores content with embedding and returns an ID."""
    chunk_id = store_chunk(
        conn, "Dan prefers SQLite", source="manual", source_type="session"
    )
    assert isinstance(chunk_id, int)
    assert chunk_id > 0


def test_store_chunk_persists_content(conn):
    """Stored chunk content is retrievable from the database."""
    store_chunk(conn, "Hello world", source="test", source_type="article")
    row = conn.execute("SELECT content FROM raw_chunks WHERE id = 1").fetchone()
    assert row[0] == "Hello world"


def test_store_chunk_stores_embedding(conn):
    """Stored chunk has a non-null embedding BLOB."""
    store_chunk(conn, "Embedding test", source="test", source_type="book")
    row = conn.execute("SELECT embedding FROM raw_chunks WHERE id = 1").fetchone()
    assert row[0] is not None
    assert len(row[0]) > 0


def test_recall_raw_finds_similar(conn):
    """recall_raw('database preference') finds semantically similar chunks."""
    store_chunk(
        conn,
        "Dan prefers SQLite over Postgres for personal projects",
        source="manual",
        source_type="session",
    )
    store_chunk(
        conn,
        "The weather in Vienna is sunny today",
        source="manual",
        source_type="session",
    )
    results = recall_raw(conn, "database preference")
    assert len(results) >= 1
    assert "SQLite" in results[0]["content"]


def test_recall_raw_source_type_filter(conn):
    """recall_raw with source_type filter only returns matching source types."""
    store_chunk(conn, "Book about databases", source="lib", source_type="book")
    store_chunk(conn, "Podcast about databases", source="pod", source_type="podcast")
    results = recall_raw(conn, "databases", source_type="book")
    assert len(results) == 1
    assert results[0]["source_type"] == "book"


def test_recall_raw_respects_limit(conn):
    """recall_raw respects the limit parameter."""
    for i in range(5):
        store_chunk(conn, f"Chunk number {i}", source="test", source_type="article")
    results = recall_raw(conn, "chunk", limit=2)
    assert len(results) == 2


def test_semantic_search_pizza(conn):
    """Semantic search works: store 'I love pizza', search 'favorite food' returns it."""
    store_chunk(conn, "I love pizza", source="chat", source_type="session")
    store_chunk(
        conn,
        "The Eiffel Tower is in Paris",
        source="wiki",
        source_type="article",
    )
    results = recall_raw(conn, "favorite food")
    assert len(results) >= 1
    assert "pizza" in results[0]["content"].lower()


def test_sqlite_vec_loads(conn):
    """sqlite-vec extension loads on the current platform without errors."""
    # If we got this far with a valid conn from init_db, sqlite-vec loaded.
    # Verify the virtual table exists.
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_chunks_vec'"
    ).fetchone()
    assert row is not None


def test_store_chunk_with_metadata(conn):
    """store_chunk correctly stores and retrieves metadata."""
    meta = {"page": 42, "chapter": "intro"}
    chunk_id = store_chunk(
        conn, "Some content", source="book.pdf", source_type="book", metadata=meta
    )
    results = recall_raw(conn, "Some content", limit=1)
    assert results[0]["metadata"] == meta


def test_recall_raw_result_shape(conn):
    """Results have the expected dict keys."""
    store_chunk(conn, "Shape test", source="test", source_type="session")
    results = recall_raw(conn, "shape test")
    assert len(results) == 1
    result = results[0]
    expected_keys = {"id", "content", "source", "source_type", "metadata", "distance", "created_at"}
    assert set(result.keys()) == expected_keys
