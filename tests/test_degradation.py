"""Tests for graceful degradation when sqlite-vec or fastembed are unavailable."""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
from unittest import mock

import pytest


class TestSqliteVecUnavailable:
    """Test behavior when sqlite-vec cannot be imported."""

    def test_init_db_works_without_vec(self, tmp_path):
        """Curated layer works even when sqlite-vec is unavailable."""
        import cortex.db as db_mod

        # Save originals
        orig_vec = db_mod.VEC_AVAILABLE

        try:
            db_mod.VEC_AVAILABLE = False
            db_path = tmp_path / "test.db"
            conn = db_mod.init_db(db_path)

            # Curated layer should work
            conn.execute(
                "INSERT INTO curated_memories (content, type) VALUES (?, ?)",
                ("test memory", "fact"),
            )
            conn.commit()

            row = conn.execute(
                "SELECT content FROM curated_memories WHERE id = 1"
            ).fetchone()
            assert row[0] == "test memory"

            # raw_chunks_vec should NOT exist
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'raw_chunks_vec'"
            ).fetchall()
            assert len(tables) == 0

            conn.close()
        finally:
            db_mod.VEC_AVAILABLE = orig_vec

    def test_recall_raw_returns_error_when_vec_unavailable(self, tmp_path):
        """recall(layer='raw') returns a clear error dict when vec is unavailable."""
        import cortex.db as db_mod
        import cortex.raw as raw_mod
        from cortex.recall import recall

        orig_vec_db = db_mod.VEC_AVAILABLE
        orig_vec_raw = raw_mod.VEC_AVAILABLE

        try:
            db_mod.VEC_AVAILABLE = False
            raw_mod.VEC_AVAILABLE = False

            db_path = tmp_path / "test.db"
            conn = db_mod.init_db(db_path)

            results = recall(conn, "test query", layer="raw")
            assert len(results) == 1
            assert "error" in results[0]
            assert results[0]["layer"] == "raw"

            conn.close()
        finally:
            db_mod.VEC_AVAILABLE = orig_vec_db
            raw_mod.VEC_AVAILABLE = orig_vec_raw

    def test_recall_both_skips_raw_when_unavailable(self, tmp_path):
        """recall(layer='both') silently skips raw layer when unavailable."""
        import cortex.db as db_mod
        import cortex.raw as raw_mod
        from cortex.curated import remember
        from cortex.recall import recall

        orig_vec_db = db_mod.VEC_AVAILABLE
        orig_vec_raw = raw_mod.VEC_AVAILABLE

        try:
            db_mod.VEC_AVAILABLE = False
            raw_mod.VEC_AVAILABLE = False

            db_path = tmp_path / "test.db"
            conn = db_mod.init_db(db_path)

            # Store a curated memory
            remember(conn, "Dan prefers SQLite", type="preference")

            # Search both layers — should get curated results without crashing
            results = recall(conn, "SQLite", layer="both")
            assert len(results) >= 1
            assert all(r.get("layer") == "curated" for r in results)

            conn.close()
        finally:
            db_mod.VEC_AVAILABLE = orig_vec_db
            raw_mod.VEC_AVAILABLE = orig_vec_raw


class TestFastembedUnavailable:
    """Test behavior when fastembed cannot be imported."""

    def test_embed_one_raises_clear_error(self):
        """embed_one raises RuntimeError when fastembed is not installed."""
        import cortex.embeddings as emb_mod

        orig = emb_mod.FASTEMBED_AVAILABLE
        try:
            emb_mod.FASTEMBED_AVAILABLE = False
            with pytest.raises(RuntimeError, match="fastembed is not installed"):
                emb_mod.embed_one("hello")
        finally:
            emb_mod.FASTEMBED_AVAILABLE = orig

    def test_embed_batch_raises_clear_error(self):
        """embed_batch raises RuntimeError when fastembed is not installed."""
        import cortex.embeddings as emb_mod

        orig = emb_mod.FASTEMBED_AVAILABLE
        try:
            emb_mod.FASTEMBED_AVAILABLE = False
            with pytest.raises(RuntimeError, match="fastembed is not installed"):
                emb_mod.embed_batch(["a", "b"])
        finally:
            emb_mod.FASTEMBED_AVAILABLE = orig

    def test_store_chunk_raises_without_fastembed(self, tmp_path):
        """store_chunk raises RuntimeError when fastembed is unavailable."""
        import cortex.db as db_mod
        import cortex.raw as raw_mod
        from cortex.embeddings import FASTEMBED_AVAILABLE as orig_fe

        orig_fe_raw = raw_mod.FASTEMBED_AVAILABLE

        try:
            raw_mod.FASTEMBED_AVAILABLE = False

            db_path = tmp_path / "test.db"
            conn = db_mod.init_db(db_path)

            with pytest.raises(RuntimeError, match="fastembed is not installed"):
                raw_mod.store_chunk(conn, "test", "src", "article")

            conn.close()
        finally:
            raw_mod.FASTEMBED_AVAILABLE = orig_fe_raw


class TestLogging:
    """Test CORTEX_LOG_LEVEL configuration."""

    def test_debug_logging_enabled(self):
        """CORTEX_LOG_LEVEL=DEBUG enables verbose logging on the cortex logger."""
        import cortex.__main__ as main_mod

        with mock.patch.dict("os.environ", {"CORTEX_LOG_LEVEL": "DEBUG"}):
            main_mod._configure_logging()
            logger = logging.getLogger("cortex")
            assert logger.level == logging.DEBUG

    def test_default_logging_is_warning(self):
        """Default log level is WARNING when CORTEX_LOG_LEVEL is not set."""
        import cortex.__main__ as main_mod

        env = dict()  # empty - no CORTEX_LOG_LEVEL
        with mock.patch.dict("os.environ", env, clear=True):
            main_mod._configure_logging()
            logger = logging.getLogger("cortex")
            assert logger.level == logging.WARNING


class TestCLI:
    """Test CLI dispatcher."""

    def test_version(self):
        """python -m cortex --version prints the version."""
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout

    def test_help(self):
        """python -m cortex --help shows subcommands."""
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        for subcmd in ["server", "ingest", "extract", "migrate", "status"]:
            assert subcmd in result.stdout

    def test_status_subcommand(self, tmp_path):
        """python -m cortex status runs without crashing."""
        db_path = tmp_path / "test.db"
        result = subprocess.run(
            [sys.executable, "-m", "cortex", "status", "--db", str(db_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "curated_count" in result.stdout

    def test_no_subcommand_shows_help(self):
        """python -m cortex with no args shows help and exits 1."""
        result = subprocess.run(
            [sys.executable, "-m", "cortex"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1


class TestMCPServerErrorHandling:
    """Test that MCP server tools return structured errors for invalid inputs."""

    def test_remember_invalid_layer(self):
        """remember with invalid layer returns error dict."""
        from cortex.server import remember

        result = remember(content="test", layer="invalid")
        assert "error" in result

    def test_recall_invalid_layer(self):
        """recall with invalid layer returns error dict instead of crashing."""
        from cortex.server import recall

        result = recall(query="test", layer="invalid")
        assert "error" in result

    def test_forget_nonexistent_id(self):
        """forget with non-existent ID returns error dict."""
        from cortex.server import forget

        result = forget(id=999999)
        assert "error" in result
