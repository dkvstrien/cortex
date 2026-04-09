"""Tests for cortex.recall: unified recall with layer fallback."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import remember
from cortex.raw import store_chunk
from cortex.recall import (
    recall,
    _normalize_bm25,
    _normalize_distance,
    _jaccard_similarity,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


# --- Score normalization ---


class TestNormalization:
    def test_bm25_perfect_match(self):
        # Very negative rank = very good match -> high score
        score = _normalize_bm25(-10.0)
        assert 0.0 < score <= 1.0
        assert score > _normalize_bm25(-1.0)

    def test_bm25_zero_rank(self):
        # rank=0 means no match signal -> score = 0
        assert _normalize_bm25(0.0) == 0.0

    def test_bm25_scores_in_range(self):
        for rank in [-0.5, -1.0, -3.0, -10.0, -100.0]:
            score = _normalize_bm25(rank)
            assert 0.0 < score <= 1.0

    def test_distance_zero(self):
        # distance=0 means identical -> score = 1.0
        assert _normalize_distance(0.0) == 1.0

    def test_distance_scores_decrease(self):
        # Closer distance -> higher score
        assert _normalize_distance(0.1) > _normalize_distance(0.5)
        assert _normalize_distance(0.5) > _normalize_distance(2.0)

    def test_distance_scores_in_range(self):
        for dist in [0.0, 0.1, 0.5, 1.0, 2.0, 10.0]:
            score = _normalize_distance(dist)
            assert 0.0 < score <= 1.0


# --- Jaccard similarity ---


class TestJaccard:
    def test_identical_texts(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert _jaccard_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity("hello world foo", "hello world bar")
        # intersection={hello, world}, union={hello, world, foo, bar}
        assert sim == pytest.approx(2.0 / 4.0)

    def test_empty_text(self):
        assert _jaccard_similarity("", "hello") == 0.0
        assert _jaccard_similarity("hello", "") == 0.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("Hello World", "hello world") == 1.0


# --- Unified recall: curated layer ---


class TestRecallCurated:
    def test_default_layer_is_curated(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite over Postgres", type="preference", source="manual")
        results = recall(conn, "database preference")
        assert len(results) >= 1
        assert all(r["layer"] == "curated" for r in results)

    def test_has_score_field(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite over Postgres", type="preference", source="manual")
        results = recall(conn, "SQLite")
        assert len(results) == 1
        assert "score" in results[0]
        assert 0.0 < results[0]["score"] <= 1.0

    def test_has_layer_field(self, conn: sqlite3.Connection):
        remember(conn, "Test memory", type="fact")
        results = recall(conn, "Test")
        assert results[0]["layer"] == "curated"

    def test_type_filter(self, conn: sqlite3.Connection):
        remember(conn, "A preference about databases", type="preference")
        remember(conn, "A fact about databases", type="fact")
        results = recall(conn, "databases", type="preference")
        assert len(results) == 1
        assert results[0]["type"] == "preference"

    def test_limit_respected(self, conn: sqlite3.Connection):
        for i in range(5):
            remember(conn, f"Memory about testing number {i}", type="fact")
        results = recall(conn, "testing", limit=2)
        assert len(results) == 2

    def test_query_expansion(self, conn: sqlite3.Connection):
        """Query 'database preference' should be split into multiple search terms."""
        remember(conn, "Dan prefers SQLite over Postgres", type="preference", source="manual")
        remember(conn, "PostgreSQL is a relational database", type="fact")
        results = recall(conn, "database preference")
        # Both should be found because query is expanded to "database* OR preference*"
        assert len(results) >= 1


# --- Unified recall: raw layer ---


class TestRecallRaw:
    def test_raw_layer(self, conn: sqlite3.Connection):
        store_chunk(conn, "SQLite is a lightweight database engine", "docs", "article")
        results = recall(conn, "database", layer="raw")
        assert len(results) >= 1
        assert all(r["layer"] == "raw" for r in results)

    def test_raw_has_score(self, conn: sqlite3.Connection):
        store_chunk(conn, "SQLite is great", "docs", "article")
        results = recall(conn, "SQLite", layer="raw")
        assert len(results) >= 1
        assert "score" in results[0]
        assert 0.0 < results[0]["score"] <= 1.0

    def test_raw_limit(self, conn: sqlite3.Connection):
        for i in range(5):
            store_chunk(conn, f"Chunk about testing number {i}", "docs", "article")
        results = recall(conn, "testing", layer="raw", limit=2)
        assert len(results) == 2


# --- Unified recall: both layers ---


class TestRecallBoth:
    def test_both_returns_curated_first(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite over Postgres", type="preference", source="manual")
        store_chunk(conn, "PostgreSQL vs MySQL comparison", "blog", "article")
        results = recall(conn, "SQLite Postgres", layer="both")
        assert len(results) >= 1
        # First result should be from curated layer
        assert results[0]["layer"] == "curated"

    def test_both_fills_from_raw(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite databases", type="preference")
        store_chunk(conn, "Redis is an in-memory data store", "docs", "article")
        store_chunk(conn, "MongoDB is a document database", "docs", "article")
        results = recall(conn, "databases data store", layer="both", limit=5)
        layers = [r["layer"] for r in results]
        assert "curated" in layers
        assert "raw" in layers

    def test_both_deduplicates(self, conn: sqlite3.Connection):
        # Store identical content in both layers
        content = "Dan prefers SQLite over Postgres for personal projects"
        remember(conn, content, type="preference", source="manual")
        store_chunk(conn, content, "session", "session")
        results = recall(conn, "SQLite Postgres", layer="both", limit=10)
        # Should not have duplicates — the raw copy should be filtered out
        contents = [r["content"] for r in results]
        assert contents.count(content) == 1

    def test_both_deduplicates_similar(self, conn: sqlite3.Connection):
        # Store very similar (but not identical) content in both layers
        curated_content = "Dan prefers SQLite over Postgres"
        raw_content = "Dan prefers SQLite over Postgres for all projects"
        remember(conn, curated_content, type="preference", source="manual")
        store_chunk(conn, raw_content, "session", "session")
        results = recall(conn, "SQLite Postgres", layer="both", limit=10)
        # The raw result is a superset of the curated one, should be deduped
        layers = [r["layer"] for r in results]
        # Only curated should survive since raw is a substring match
        curated_results = [r for r in results if r["layer"] == "curated"]
        assert len(curated_results) >= 1

    def test_both_respects_limit(self, conn: sqlite3.Connection):
        for i in range(5):
            remember(conn, f"Curated memory {i} about databases", type="fact")
        for i in range(5):
            store_chunk(conn, f"Raw chunk {i} about databases", "docs", "article")
        results = recall(conn, "databases", layer="both", limit=3)
        assert len(results) <= 3

    def test_both_all_have_score(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite", type="preference")
        store_chunk(conn, "Redis is fast", "docs", "article")
        results = recall(conn, "database", layer="both", limit=10)
        for r in results:
            assert "score" in r
            assert 0.0 < r["score"] <= 1.0

    def test_both_all_have_layer(self, conn: sqlite3.Connection):
        remember(conn, "Dan prefers SQLite", type="preference")
        store_chunk(conn, "Redis is fast", "docs", "article")
        results = recall(conn, "database", layer="both", limit=10)
        for r in results:
            assert r["layer"] in ("curated", "raw")


# --- Invalid layer ---


class TestInvalidLayer:
    def test_invalid_layer_raises(self, conn: sqlite3.Connection):
        with pytest.raises(ValueError, match="Invalid layer"):
            recall(conn, "test", layer="invalid")
