"""Tests for cortex.doctor health checker."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cortex.db import init_db
from cortex.doctor import (
    CheckResult,
    check_db,
    check_fastembed,
    check_fts5,
    check_mcp_config,
    check_remote_mcp,
    check_staging_dir,
    check_stop_hook,
    check_sqlite_vec,
    run_doctor,
)


# ---------------------------------------------------------------------------
# check_db
# ---------------------------------------------------------------------------


class TestCheckDb:
    def test_pass_when_db_exists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.close()

        result, opened_conn = check_db(db_path)
        assert result.status == "PASS"
        assert "cortex.db" in result.label
        opened_conn.close()

    def test_fail_when_db_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nonexistent.db"
        result, conn = check_db(db_path)
        assert result.status == "FAIL"
        assert conn is None
        assert result.hint != ""

    def test_pass_includes_counts(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.execute("INSERT INTO curated_memories (content, type) VALUES ('x', 'fact')")
        conn.commit()
        conn.close()

        result, opened_conn = check_db(db_path)
        assert result.status == "PASS"
        assert "1" in result.detail  # 1 curated memory
        opened_conn.close()

    def test_returns_open_connection_on_pass(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.close()

        result, opened_conn = check_db(db_path)
        assert result.status == "PASS"
        assert isinstance(opened_conn, sqlite3.Connection)
        opened_conn.close()


# ---------------------------------------------------------------------------
# check_fts5
# ---------------------------------------------------------------------------


class TestCheckFts5:
    def test_pass_with_valid_conn(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        result = check_fts5(conn)
        conn.close()
        assert result.status == "PASS"

    def test_fail_when_conn_is_none(self) -> None:
        result = check_fts5(None)
        assert result.status == "FAIL"

    def test_fts5_works_with_data(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.execute("INSERT INTO curated_memories (content, type) VALUES ('hello world', 'fact')")
        conn.commit()
        result = check_fts5(conn)
        conn.close()
        assert result.status == "PASS"


# ---------------------------------------------------------------------------
# check_sqlite_vec
# ---------------------------------------------------------------------------


class TestCheckSqliteVec:
    def test_warn_when_import_fails(self) -> None:
        with patch.dict("sys.modules", {"sqlite_vec": None}):
            # Force ImportError by removing from sys.modules
            import sys
            original = sys.modules.pop("sqlite_vec", None)
            try:
                result = check_sqlite_vec(None)
                # If sqlite_vec isn't installed, we get WARN
                # If it is installed but conn=None, it still tries import first
                assert result.status in ("WARN", "PASS")
            finally:
                if original is not None:
                    sys.modules["sqlite_vec"] = original

    def test_fail_when_conn_none_but_import_ok(self) -> None:
        """If sqlite_vec imports but conn is None, we get WARN."""
        try:
            import sqlite_vec  # noqa: F401
            result = check_sqlite_vec(None)
            assert result.status == "WARN"
        except ImportError:
            pytest.skip("sqlite-vec not installed")

    def test_pass_with_valid_conn(self, tmp_path: Path) -> None:
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        result = check_sqlite_vec(conn)
        conn.close()
        assert result.status == "PASS"


# ---------------------------------------------------------------------------
# check_fastembed
# ---------------------------------------------------------------------------


class TestCheckFastembed:
    def test_pass_when_importable(self) -> None:
        try:
            from fastembed import TextEmbedding  # noqa: F401
            result = check_fastembed()
            assert result.status == "PASS"
        except ImportError:
            pytest.skip("fastembed not installed")

    def test_warn_when_not_importable(self) -> None:
        import sys

        original = sys.modules.pop("fastembed", None)
        # Also block it from importing
        sys.modules["fastembed"] = None  # type: ignore[assignment]
        try:
            result = check_fastembed()
            assert result.status == "WARN"
            assert result.hint != ""
        finally:
            if original is not None:
                sys.modules["fastembed"] = original
            else:
                sys.modules.pop("fastembed", None)


# ---------------------------------------------------------------------------
# check_staging_dir
# ---------------------------------------------------------------------------


class TestCheckStagingDir:
    def test_pass_when_dir_exists(self, tmp_path: Path) -> None:
        staging = tmp_path / "staging"
        staging.mkdir()
        result = check_staging_dir(staging)
        assert result.status == "PASS"

    def test_fail_when_missing(self, tmp_path: Path) -> None:
        staging = tmp_path / "staging_missing"
        result = check_staging_dir(staging)
        assert result.status == "FAIL"
        assert result.hint != ""

    def test_fail_when_file_not_dir(self, tmp_path: Path) -> None:
        staging = tmp_path / "staging_file"
        staging.write_text("not a dir")
        result = check_staging_dir(staging)
        assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# check_stop_hook
# ---------------------------------------------------------------------------


class TestCheckStopHook:
    def test_pass_when_hook_present(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/scripts/cortex-capture.sh"}]}
                ]
            }
        }))
        result = check_stop_hook(settings)
        assert result.status == "PASS"

    def test_fail_when_settings_missing(self, tmp_path: Path) -> None:
        settings = tmp_path / "missing_settings.json"
        result = check_stop_hook(settings)
        assert result.status == "FAIL"
        assert result.hint != ""

    def test_fail_when_hook_absent(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {"Stop": []}}))
        result = check_stop_hook(settings)
        assert result.status == "FAIL"

    def test_fail_when_different_hook_only(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "bash ~/scripts/other.sh"}]}
                ]
            }
        }))
        result = check_stop_hook(settings)
        assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# check_mcp_config
# ---------------------------------------------------------------------------


class TestCheckMcpConfig:
    def test_pass_when_cortex_entry_present(self, tmp_path: Path) -> None:
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({
            "cortex": {"type": "sse", "url": "http://100.108.198.107:8765/sse"}
        }))
        result = check_mcp_config(mcp_path)
        assert result.status == "PASS"

    def test_pass_when_nested_under_mcp_servers(self, tmp_path: Path) -> None:
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({
            "mcpServers": {
                "cortex": {"type": "sse", "url": "http://100.108.198.107:8765/sse"}
            }
        }))
        result = check_mcp_config(mcp_path)
        assert result.status == "PASS"

    def test_fail_when_file_missing(self, tmp_path: Path) -> None:
        mcp_path = tmp_path / "missing.mcp.json"
        result = check_mcp_config(mcp_path)
        assert result.status == "FAIL"
        assert result.hint != ""

    def test_fail_when_cortex_entry_absent(self, tmp_path: Path) -> None:
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({
            "other-server": {"type": "sse", "url": "http://example.com/sse"}
        }))
        result = check_mcp_config(mcp_path)
        assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# check_remote_mcp
# ---------------------------------------------------------------------------


class TestCheckRemoteMcp:
    def test_pass_when_ssh_and_http_ok(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"status":"ok"}\n',
                stderr="",
            )
            result = check_remote_mcp("thinkpad")
        assert result.status == "PASS"

    def test_warn_when_output_is_fail(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="FAIL\n",
                stderr="",
            )
            result = check_remote_mcp("thinkpad")
        assert result.status == "WARN"

    def test_warn_when_ssh_fails(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=255,
                stdout="",
                stderr="ssh: connect to host thinkpad port 22: Connection refused",
            )
            result = check_remote_mcp("thinkpad")
        assert result.status == "WARN"

    def test_warn_on_timeout(self) -> None:
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 15)):
            result = check_remote_mcp("thinkpad")
        assert result.status == "WARN"
        assert "timed out" in result.detail


# ---------------------------------------------------------------------------
# run_doctor integration
# ---------------------------------------------------------------------------


def _make_full_env(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Helper: create staging dir, settings.json, .mcp.json in tmp_path."""
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "bash ~/scripts/cortex-capture.sh"}]}
            ]
        }
    }))

    mcp_path = tmp_path / ".mcp.json"
    mcp_path.write_text(json.dumps({
        "cortex": {"type": "sse", "url": "http://100.108.198.107:8765/sse"}
    }))

    return staging, settings, mcp_path


class TestRunDoctor:
    def test_exit_zero_when_all_pass(self, tmp_path: Path) -> None:
        """Exit code 0 when all required checks pass."""
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.close()

        staging, settings, mcp_path = _make_full_env(tmp_path)

        exit_code = run_doctor(
            db_path=db_path,
            staging_dir=staging,
            settings_path=settings,
            mcp_path=mcp_path,
        )

        assert exit_code == 0

    def test_exit_one_when_db_missing(self, tmp_path: Path) -> None:
        """Exit code 1 when DB doesn't exist (FAIL)."""
        db_path = tmp_path / "nonexistent.db"
        staging, settings, mcp_path = _make_full_env(tmp_path)

        exit_code = run_doctor(
            db_path=db_path,
            staging_dir=staging,
            settings_path=settings,
            mcp_path=mcp_path,
        )

        assert exit_code == 1

    def test_remote_check_included_when_specified(self, tmp_path: Path, capsys) -> None:
        """--remote triggers the remote MCP check."""
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.close()

        staging, settings, mcp_path = _make_full_env(tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"status":"ok"}\n',
                stderr="",
            )
            exit_code = run_doctor(
                db_path=db_path,
                remote="thinkpad",
                staging_dir=staging,
                settings_path=settings,
                mcp_path=mcp_path,
            )

        captured = capsys.readouterr()
        assert "thinkpad" in captured.out
        # Remote is WARN/PASS — should not change exit code to 1
        assert exit_code == 0

    def test_output_labels_present(self, tmp_path: Path, capsys) -> None:
        """Key labels appear in printed output."""
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.close()

        staging, settings, mcp_path = _make_full_env(tmp_path)

        run_doctor(
            db_path=db_path,
            staging_dir=staging,
            settings_path=settings,
            mcp_path=mcp_path,
        )

        captured = capsys.readouterr()
        assert "DB at" in captured.out
        assert "FTS5" in captured.out
        assert "sqlite-vec" in captured.out
        assert "fastembed" in captured.out
        assert "Staging dir" in captured.out
        assert "Stop hook" in captured.out
        assert "MCP server" in captured.out

    def test_fail_includes_remediation_hint(self, tmp_path: Path, capsys) -> None:
        """FAIL lines include a remediation hint."""
        db_path = tmp_path / "missing.db"
        staging, settings, mcp_path = _make_full_env(tmp_path)

        run_doctor(
            db_path=db_path,
            staging_dir=staging,
            settings_path=settings,
            mcp_path=mcp_path,
        )

        captured = capsys.readouterr()
        assert "[FAIL]" in captured.out
        assert "python -m cortex install" in captured.out

    def test_warn_does_not_cause_exit_one(self, tmp_path: Path) -> None:
        """WARN-only results yield exit code 0."""
        db_path = tmp_path / "cortex.db"
        conn = init_db(db_path)
        conn.close()

        staging, settings, mcp_path = _make_full_env(tmp_path)

        # Force sqlite-vec and fastembed to be unavailable (WARN not FAIL)
        import sys
        saved_vec = sys.modules.get("sqlite_vec")
        saved_fe = sys.modules.get("fastembed")

        sys.modules["sqlite_vec"] = None  # type: ignore[assignment]
        sys.modules["fastembed"] = None  # type: ignore[assignment]

        try:
            exit_code = run_doctor(
                db_path=db_path,
                staging_dir=staging,
                settings_path=settings,
                mcp_path=mcp_path,
            )
        finally:
            if saved_vec is not None:
                sys.modules["sqlite_vec"] = saved_vec
            else:
                sys.modules.pop("sqlite_vec", None)
            if saved_fe is not None:
                sys.modules["fastembed"] = saved_fe
            else:
                sys.modules.pop("fastembed", None)

        # Even with WARN, exit code should be 0 (no FAIL)
        assert exit_code == 0
