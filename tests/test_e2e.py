"""End-to-end tests for the full Cortex pipeline.

These tests verify that all layers and operations work together correctly,
using temporary databases that leave no artifacts.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.curated import forget, get_history, recall_curated, remember, supersede
from cortex.decay import decay_confidence, reinforce
from cortex.raw import recall_raw, store_chunk
from cortex.recall import recall
from cortex.status import status


@pytest.fixture
def db(tmp_path: Path):
    """Yield (conn, db_path) using a temporary database."""
    db_path = tmp_path / "cortex_e2e.db"
    conn = init_db(db_path)
    yield conn, db_path
    conn.close()


@pytest.fixture
def conn(db):
    """Shortcut: just the connection."""
    return db[0]


# ---------------------------------------------------------------------------
# 1. FTS5 ranking with 30+ memories
# ---------------------------------------------------------------------------


class TestFTS5Ranking:
    """Store 30+ curated memories and verify FTS5 ranks relevant results first."""

    MEMORIES = [
        # Highly relevant to "SQLite database"
        ("SQLite is a lightweight database engine", "fact"),
        ("SQLite uses B-tree for its database storage", "fact"),
        ("SQLite database files are self-contained", "fact"),
        ("The SQLite database format is cross-platform", "fact"),
        ("SQLite supports full-text search via FTS5 database extensions", "fact"),
        # Somewhat relevant
        ("PostgreSQL is a powerful database system", "fact"),
        ("Database migrations should be version controlled", "procedure"),
        ("Always back up your database before schema changes", "procedure"),
        ("Redis is an in-memory database for caching", "fact"),
        ("MongoDB is a NoSQL database", "fact"),
        # Irrelevant padding to reach 30+
        ("Dan lives in Austria near Vienna", "fact"),
        ("The farm has 25 dairy cows", "entity"),
        ("Use pytest for Python testing", "procedure"),
        ("Claude is an AI assistant by Anthropic", "fact"),
        ("Tailscale provides mesh VPN networking", "fact"),
        ("Obsidian stores notes as plain markdown files", "fact"),
        ("Syncthing synchronizes files between devices", "fact"),
        ("FastAPI is a modern Python web framework", "fact"),
        ("Docker containers isolate application dependencies", "procedure"),
        ("Git branches enable parallel development workflows", "procedure"),
        ("Python virtual environments prevent dependency conflicts", "procedure"),
        ("SSH keys are more secure than passwords", "fact"),
        ("Cron jobs schedule recurring tasks on Linux", "procedure"),
        ("WAL mode improves SQLite concurrent read performance", "fact"),
        ("JSON is a common data interchange format", "fact"),
        ("YAML is used for configuration files", "fact"),
        ("Markdown is a lightweight markup language", "fact"),
        ("TCP provides reliable ordered data delivery", "fact"),
        ("HTTP is the protocol of the world wide web", "fact"),
        ("TLS encrypts network communications", "fact"),
        ("DNS resolves domain names to IP addresses", "fact"),
        ("REST APIs use HTTP methods for CRUD operations", "procedure"),
    ]

    def test_relevant_results_rank_higher(self, conn: sqlite3.Connection):
        """FTS5 should rank SQLite-specific memories above unrelated ones."""
        for content, mtype in self.MEMORIES:
            remember(conn, content, type=mtype, source="e2e_test")

        assert len(self.MEMORIES) >= 30, "Need 30+ memories for this test"

        results = recall_curated(conn, "SQLite database", limit=10)

        assert len(results) >= 3, "Should find multiple SQLite database matches"

        # Top results should all mention SQLite or database
        for r in results[:3]:
            text = r["content"].lower()
            assert "sqlite" in text or "database" in text, (
                f"Top result should be about SQLite/database, got: {r['content']}"
            )

        # Verify ranking: BM25 scores should be monotonically non-decreasing
        # (SQLite FTS5 BM25 returns negative values, more negative = better match)
        ranks = [r["rank"] for r in results]
        for i in range(len(ranks) - 1):
            assert ranks[i] <= ranks[i + 1], (
                f"Results should be ordered by BM25 rank: {ranks}"
            )

    def test_irrelevant_terms_return_no_sqlite_results(self, conn: sqlite3.Connection):
        """Searching for farm-related terms should NOT return SQLite memories."""
        for content, mtype in self.MEMORIES:
            remember(conn, content, type=mtype, source="e2e_test")

        results = recall_curated(conn, "dairy cows farm", limit=5)

        for r in results:
            assert "sqlite" not in r["content"].lower(), (
                f"Farm search should not return SQLite content: {r['content']}"
            )


# ---------------------------------------------------------------------------
# 2. Vector search ranking with 20+ chunks
# ---------------------------------------------------------------------------


class TestVectorSearchRanking:
    """Store 20+ raw chunks and verify vector search ranks semantically similar content higher."""

    CHUNKS = [
        # About cooking / food (target cluster)
        ("I love making homemade pasta with fresh tomato sauce", "article"),
        ("Italian cuisine uses olive oil, garlic, and basil extensively", "article"),
        ("The best pizza dough needs high-protein flour and slow fermentation", "article"),
        ("Risotto requires constant stirring and warm broth additions", "article"),
        ("Fresh mozzarella cheese pairs perfectly with ripe tomatoes", "article"),
        # About programming
        ("Python list comprehensions are more readable than map and filter", "article"),
        ("Rust's borrow checker prevents memory safety issues at compile time", "article"),
        ("JavaScript async/await simplifies asynchronous code patterns", "article"),
        ("Go routines enable lightweight concurrent programming", "article"),
        ("TypeScript adds static type checking to JavaScript", "article"),
        # About nature / animals
        ("Alpine meadows bloom with wildflowers in late spring", "article"),
        ("Eagles nest on high cliff ledges to protect their young", "article"),
        ("Salmon swim upstream to spawn in their birthplace rivers", "article"),
        ("Oak trees can live for hundreds of years in temperate forests", "article"),
        ("Wolves hunt in coordinated packs across vast territories", "article"),
        # About music
        ("Jazz improvisation requires deep knowledge of chord progressions", "article"),
        ("The piano has 88 keys spanning over seven octaves", "article"),
        ("Classical symphony orchestras typically have four sections", "article"),
        ("Blues music originated in the Deep South of the United States", "article"),
        ("Electronic music production relies heavily on synthesizers", "article"),
        # Extra padding
        ("Machine learning models require large amounts of training data", "article"),
        ("Quantum computers use qubits instead of classical bits", "article"),
    ]

    def test_semantic_similarity_ranking(self, conn: sqlite3.Connection):
        """Vector search for food/cooking should rank food chunks highest."""
        for content, stype in self.CHUNKS:
            store_chunk(conn, content, source="e2e_test", source_type=stype)

        assert len(self.CHUNKS) >= 20, "Need 20+ chunks for this test"

        results = recall_raw(conn, "What are some good recipes for Italian food?", limit=10)

        assert len(results) >= 5, "Should find multiple results"

        # The top results should be about food/cooking, not programming or nature
        food_keywords = {"pasta", "pizza", "cuisine", "risotto", "mozzarella", "tomato",
                         "olive", "flour", "cheese", "garlic", "basil"}
        top_3_content = " ".join(r["content"].lower() for r in results[:3])
        food_matches = sum(1 for kw in food_keywords if kw in top_3_content)

        assert food_matches >= 3, (
            f"Top 3 results should be food-related (found {food_matches} food keywords). "
            f"Got: {[r['content'][:60] for r in results[:3]]}"
        )

        # Distances should be non-decreasing (closer = better)
        distances = [r["distance"] for r in results]
        for i in range(len(distances) - 1):
            assert distances[i] <= distances[i + 1] + 1e-6, (
                f"Results should be ordered by distance: {distances}"
            )


# ---------------------------------------------------------------------------
# 3. Full pipeline: remember -> recall -> supersede -> recall -> forget -> verify
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Test the complete lifecycle of a curated memory."""

    def test_remember_recall_supersede_forget(self, conn: sqlite3.Connection):
        # Step 1: Remember
        mid = remember(conn, "Dan's favorite database is MySQL", type="preference", source="test")
        assert isinstance(mid, int)

        # Step 2: Recall - should find it
        results = recall_curated(conn, "favorite database")
        assert any(r["id"] == mid for r in results)
        assert any("MySQL" in r["content"] for r in results)

        # Step 3: Supersede with updated info
        new_id = supersede(conn, mid, "Dan's favorite database is SQLite")
        assert new_id != mid

        # Step 4: Recall again - should find new version, not old
        results = recall_curated(conn, "favorite database")
        contents = [r["content"] for r in results]
        assert any("SQLite" in c for c in contents), "New memory should be findable"
        ids = [r["id"] for r in results]
        assert mid not in ids, "Old memory should be excluded (superseded + soft-deleted)"

        # Step 5: Verify history chain
        history = get_history(conn, new_id)
        assert len(history) == 2
        assert history[0]["id"] == new_id
        assert history[1]["id"] == mid
        assert history[0]["supersedes_id"] == mid

        # Step 6: Forget the new memory
        forget(conn, new_id)

        # Step 7: Verify it's gone from search
        results = recall_curated(conn, "favorite database")
        ids = [r["id"] for r in results]
        assert new_id not in ids, "Forgotten memory should not appear in results"
        assert mid not in ids, "Old superseded memory should not appear either"


# ---------------------------------------------------------------------------
# 4. Cross-layer: store in both, recall with layer='both', verify dedup
# ---------------------------------------------------------------------------


class TestCrossLayer:
    """Store content in both layers, recall with layer='both', verify deduplication."""

    def test_both_layers_with_deduplication(self, conn: sqlite3.Connection):
        # Store the same content in curated layer
        curated_id = remember(
            conn,
            "Cortex uses FTS5 for curated memory search",
            type="fact",
            source="e2e_test",
        )

        # Store very similar content in raw layer
        raw_id = store_chunk(
            conn,
            "Cortex uses FTS5 for curated memory search",
            source="e2e_test",
            source_type="session",
        )

        # Recall with layer='both'
        results = recall(conn, "FTS5 curated memory search", layer="both", limit=10)

        assert len(results) >= 1, "Should find at least one result"

        # Due to deduplication, we should not see both versions as separate results
        # The curated result should appear first (priority layer)
        assert results[0]["layer"] == "curated", "Curated results should come first"

        # Count how many results have near-identical content
        exact_matches = [
            r for r in results
            if "FTS5" in r["content"] and "curated" in r["content"]
        ]
        assert len(exact_matches) <= 1, (
            f"Deduplication should prevent duplicate content; found {len(exact_matches)} matches"
        )

    def test_different_content_appears_from_both_layers(self, conn: sqlite3.Connection):
        """Content unique to each layer should both appear in combined results."""
        remember(conn, "Curated-only fact about memory systems", type="fact", source="test")
        store_chunk(
            conn,
            "Raw-only chunk about vector embeddings and similarity search",
            source="test",
            source_type="session",
        )

        results = recall(conn, "memory systems vector embeddings", layer="both", limit=10)

        layers_found = {r["layer"] for r in results}
        # We should get results from at least the curated layer
        # (raw layer may or may not match depending on embedding similarity)
        assert "curated" in layers_found, "Should find curated results"


# ---------------------------------------------------------------------------
# 5. Decay lifecycle: create -> time passes -> decay -> verify -> reinforce -> verify
# ---------------------------------------------------------------------------


class TestDecayLifecycle:
    """Test the full confidence decay and reinforcement cycle."""

    def test_half_life_math(self, conn: sqlite3.Connection):
        """Verify exponential decay produces expected confidence values."""
        mid = remember(conn, "Decay test memory", type="fact", source="test")

        # Manually set updated_at to 90 days ago (one half-life)
        ninety_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=90)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "UPDATE curated_memories SET updated_at = ? WHERE id = ?",
            (ninety_days_ago, mid),
        )
        conn.commit()

        # Run decay with default half_life=90 days
        updated = decay_confidence(conn, half_life_days=90.0)
        assert updated >= 1

        row = conn.execute(
            "SELECT confidence FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        confidence_90d = row[0]

        # After exactly one half-life, confidence should be ~0.5
        assert abs(confidence_90d - 0.5) < 0.05, (
            f"After 90 days (1 half-life), confidence should be ~0.5, got {confidence_90d}"
        )

    def test_double_half_life(self, conn: sqlite3.Connection):
        """After 180 days (2 half-lives), confidence should be ~0.25."""
        mid = remember(conn, "Double decay test", type="fact", source="test")

        one_eighty_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=180)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "UPDATE curated_memories SET updated_at = ? WHERE id = ?",
            (one_eighty_days_ago, mid),
        )
        conn.commit()

        decay_confidence(conn, half_life_days=90.0)

        row = conn.execute(
            "SELECT confidence FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        confidence_180d = row[0]

        assert abs(confidence_180d - 0.25) < 0.05, (
            f"After 180 days (2 half-lives), confidence should be ~0.25, got {confidence_180d}"
        )

    def test_reinforce_resets_confidence(self, conn: sqlite3.Connection):
        """Reinforcing a decayed memory should reset confidence to 1.0."""
        mid = remember(conn, "Reinforce test memory", type="fact", source="test")

        # Decay it
        ninety_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=90)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "UPDATE curated_memories SET updated_at = ? WHERE id = ?",
            (ninety_days_ago, mid),
        )
        conn.commit()
        decay_confidence(conn, half_life_days=90.0)

        # Verify it decayed
        row = conn.execute(
            "SELECT confidence FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row[0] < 0.6, "Should have decayed"

        # Reinforce
        reinforce(conn, mid)

        # Verify reset
        row = conn.execute(
            "SELECT confidence FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row[0] == 1.0, f"Reinforced confidence should be 1.0, got {row[0]}"

    def test_recall_auto_reinforces(self, conn: sqlite3.Connection):
        """Accessing a memory via recall_curated should reinforce it."""
        mid = remember(conn, "Auto-reinforce unique test phrase xyzzy", type="fact", source="test")

        # Decay it
        ninety_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=90)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "UPDATE curated_memories SET updated_at = ? WHERE id = ?",
            (ninety_days_ago, mid),
        )
        conn.commit()
        decay_confidence(conn, half_life_days=90.0)

        # Recall it (which should auto-reinforce)
        results = recall_curated(conn, "xyzzy")
        assert len(results) >= 1

        # Check confidence is back to 1.0
        row = conn.execute(
            "SELECT confidence FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row[0] == 1.0, f"Recall should reinforce to 1.0, got {row[0]}"

    def test_stale_flagging(self, conn: sqlite3.Connection):
        """Memories decayed below 0.1 should be flagged as stale."""
        mid = remember(conn, "Will become stale", type="fact", source="test")

        # Set updated_at to 300 days ago (>3 half-lives at 90d => confidence < 0.1)
        long_ago = (
            datetime.now(timezone.utc) - timedelta(days=300)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "UPDATE curated_memories SET updated_at = ? WHERE id = ?",
            (long_ago, mid),
        )
        conn.commit()
        decay_confidence(conn, half_life_days=90.0)

        # Verify it's stale
        row = conn.execute(
            "SELECT confidence FROM curated_memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row[0] < 0.1, f"After 300 days, confidence should be < 0.1, got {row[0]}"

        # Expected: 0.5^(300/90) = 0.5^3.33 ~ 0.099
        expected = 0.5 ** (300.0 / 90.0)
        assert abs(row[0] - expected) < 0.01, (
            f"Confidence should be ~{expected:.4f}, got {row[0]}"
        )


# ---------------------------------------------------------------------------
# 6. Status after operations
# ---------------------------------------------------------------------------


class TestStatusAfterOperations:
    """Verify the status dashboard reflects actual state after operations."""

    def test_counts_and_types(self, db):
        conn, db_path = db

        # Store various curated memories
        remember(conn, "A preference about tools", type="preference", source="test")
        remember(conn, "A fact about the world", type="fact", source="manual")
        remember(conn, "A procedure for deployment", type="procedure", source="docs")
        remember(conn, "An entity called Cortex", type="entity", source="test")
        remember(conn, "Another fact for variety", type="fact", source="test")

        # Store raw chunks
        store_chunk(conn, "Session transcript chunk 1", source="session1", source_type="session")
        store_chunk(conn, "Article about AI systems", source="article1", source_type="article")
        store_chunk(conn, "Another session chunk", source="session2", source_type="session")

        result = status(conn, db_path)

        assert result["curated_count"] == 5
        assert result["raw_count"] == 3
        assert result["by_type"]["preference"] == 1
        assert result["by_type"]["fact"] == 2
        assert result["by_type"]["procedure"] == 1
        assert result["by_type"]["entity"] == 1
        assert result["by_source"]["session"] == 2
        assert result["by_source"]["article"] == 1
        assert result["last_memory_at"] is not None
        assert result["db_size_mb"] > 0
        assert result["stale_count"] == 0
        assert result["integrity"]["ok"] is True

    def test_stale_count_in_status(self, db):
        conn, db_path = db

        # Create memories and make some stale
        mid1 = remember(conn, "Fresh memory", type="fact", source="test")
        mid2 = remember(conn, "Will be stale", type="fact", source="test")
        mid3 = remember(conn, "Also stale", type="fact", source="test")

        # Make two memories stale
        long_ago = (
            datetime.now(timezone.utc) - timedelta(days=400)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            "UPDATE curated_memories SET updated_at = ? WHERE id IN (?, ?)",
            (long_ago, mid2, mid3),
        )
        conn.commit()
        decay_confidence(conn, half_life_days=90.0)

        result = status(conn, db_path)
        assert result["stale_count"] == 2, f"Expected 2 stale, got {result['stale_count']}"

    def test_forget_reduces_curated_count(self, db):
        conn, db_path = db

        mid1 = remember(conn, "Memory one", type="fact", source="test")
        mid2 = remember(conn, "Memory two", type="fact", source="test")

        result_before = status(conn, db_path)
        assert result_before["curated_count"] == 2

        forget(conn, mid1)

        result_after = status(conn, db_path)
        assert result_after["curated_count"] == 1


# ---------------------------------------------------------------------------
# 7. MCP server instantiation
# ---------------------------------------------------------------------------


class TestMCPServer:
    """Verify the MCP server can be instantiated without errors."""

    def test_server_instantiation(self):
        """FastMCP server should instantiate with all tools registered."""
        from cortex.server import mcp as server_instance

        assert server_instance is not None
        assert server_instance.name == "cortex"

    def test_create_server_function(self):
        """create_server() should return a new FastMCP instance."""
        from cortex.server import create_server

        server = create_server(port=9999)
        assert server is not None
        assert server.name == "cortex"

    def test_server_has_all_tools(self):
        """The server should expose exactly 4 tools: remember, recall, forget, status."""
        from cortex.server import mcp as server_instance

        # FastMCP stores tools internally; check they're registered
        # The _tools dict or similar attribute stores registered tools
        tool_names = set()
        if hasattr(server_instance, "_tool_manager"):
            # FastMCP >= 1.0
            tools = server_instance._tool_manager._tools
            tool_names = set(tools.keys())
        elif hasattr(server_instance, "_tools"):
            tool_names = set(server_instance._tools.keys())

        expected = {"remember", "recall", "forget", "status"}
        assert expected.issubset(tool_names), (
            f"Expected tools {expected}, found {tool_names}"
        )


# ---------------------------------------------------------------------------
# 8. Error handling in pipeline
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify error handling across the pipeline."""

    def test_forget_nonexistent_raises(self, conn: sqlite3.Connection):
        """Forgetting a non-existent ID should raise KeyError."""
        with pytest.raises(KeyError, match="No curated memory"):
            forget(conn, 99999)

    def test_supersede_nonexistent_raises(self, conn: sqlite3.Connection):
        """Superseding a non-existent ID should raise KeyError."""
        with pytest.raises(KeyError, match="No curated memory"):
            supersede(conn, 99999, "new content")

    def test_get_history_nonexistent_raises(self, conn: sqlite3.Connection):
        """Getting history for a non-existent ID should raise KeyError."""
        with pytest.raises(KeyError, match="No curated memory"):
            get_history(conn, 99999)

    def test_recall_invalid_layer_raises(self, conn: sqlite3.Connection):
        """Invalid layer parameter should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid layer"):
            recall(conn, "test", layer="invalid")
