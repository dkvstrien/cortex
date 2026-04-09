"""Cortex health checker and diagnostics.

Runs a series of checks and prints a PASS/FAIL/WARN checklist.
Exit code 0 if all checks pass or only WARNs, 1 if any FAIL.

Usage:
    python -m cortex doctor [--db PATH] [--remote <ssh-host>]
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

Status = Literal["PASS", "FAIL", "WARN"]


class CheckResult:
    def __init__(self, label: str, status: Status, detail: str = "", hint: str = "") -> None:
        self.label = label
        self.status = status
        self.detail = detail
        self.hint = hint  # Only shown on FAIL

    def __repr__(self) -> str:
        return f"CheckResult({self.label!r}, {self.status!r})"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_db(db_path: Path) -> tuple[CheckResult, sqlite3.Connection | None]:
    """Check that the DB file exists and opens without error."""
    if not db_path.exists():
        return (
            CheckResult(
                f"DB at {db_path}",
                "FAIL",
                "file not found",
                hint=f"Run: python -m cortex install",
            ),
            None,
        )

    try:
        conn = sqlite3.connect(str(db_path))
        # Quick sanity: read the schema version
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        # Get counts for display
        curated = conn.execute(
            "SELECT COUNT(*) FROM curated_memories WHERE deleted_at IS NULL"
        ).fetchone()[0]
        raw = conn.execute("SELECT COUNT(*) FROM raw_chunks").fetchone()[0]
        return (
            CheckResult(
                f"DB at {db_path}",
                "PASS",
                f"{curated} curated memories, {raw} raw chunks",
            ),
            conn,
        )
    except Exception as exc:
        return (
            CheckResult(
                f"DB at {db_path}",
                "FAIL",
                str(exc),
                hint="Run: python -m cortex install",
            ),
            None,
        )


def check_fts5(conn: sqlite3.Connection | None) -> CheckResult:
    """Check that FTS5 full-text search works."""
    if conn is None:
        return CheckResult("FTS5 full-text search", "FAIL", "DB unavailable")

    try:
        conn.execute(
            "SELECT rowid FROM curated_memories_fts WHERE curated_memories_fts MATCH 'test*' LIMIT 1"
        ).fetchall()
        return CheckResult("FTS5 full-text search", "PASS")
    except Exception as exc:
        return CheckResult(
            "FTS5 full-text search",
            "FAIL",
            str(exc),
            hint="Run: python -m cortex install  (DB may need re-initializing)",
        )


def check_sqlite_vec(conn: sqlite3.Connection | None) -> CheckResult:
    """Check that the sqlite-vec extension loads. WARN if not available."""
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return CheckResult(
            "sqlite-vec vector extension",
            "WARN",
            "not installed",
            hint="Run: pip install sqlite-vec",
        )

    if conn is None:
        return CheckResult(
            "sqlite-vec vector extension",
            "WARN",
            "DB unavailable — cannot verify extension load",
        )

    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return CheckResult("sqlite-vec vector extension", "PASS")
    except Exception as exc:
        return CheckResult(
            "sqlite-vec vector extension",
            "WARN",
            str(exc),
            hint="Run: pip install sqlite-vec",
        )


def check_fastembed() -> CheckResult:
    """Check that fastembed is importable. WARN if not available."""
    try:
        from fastembed import TextEmbedding  # noqa: F401

        return CheckResult("fastembed (importable)", "PASS")
    except ImportError:
        return CheckResult(
            "fastembed (importable)",
            "WARN",
            "not installed — vector search unavailable",
            hint="Run: pip install fastembed",
        )


def check_staging_dir(staging_dir: Path) -> CheckResult:
    """Check that the staging directory exists."""
    if not staging_dir.exists():
        return CheckResult(
            f"Staging dir {staging_dir}",
            "FAIL",
            "directory not found",
            hint="Run: python -m cortex install",
        )
    if not staging_dir.is_dir():
        return CheckResult(
            f"Staging dir {staging_dir}",
            "FAIL",
            "path exists but is not a directory",
            hint=f"Remove the file at {staging_dir} and run: python -m cortex install",
        )
    return CheckResult(f"Staging dir {staging_dir}", "PASS")


def check_stop_hook(settings_path: Path) -> CheckResult:
    """Check that the cortex-capture Stop hook is registered."""
    if not settings_path.exists():
        return CheckResult(
            "Stop hook registered in settings.json",
            "FAIL",
            f"{settings_path} not found",
            hint="Run: python -m cortex install",
        )
    try:
        with settings_path.open() as f:
            settings = json.load(f)
        stop_hooks = settings.get("hooks", {}).get("Stop", [])
        for group in stop_hooks:
            for hook in group.get("hooks", []):
                if "cortex-capture" in hook.get("command", ""):
                    return CheckResult("Stop hook registered in settings.json", "PASS")
        return CheckResult(
            "Stop hook registered in settings.json",
            "FAIL",
            "cortex-capture hook not found",
            hint="Run: python -m cortex install",
        )
    except Exception as exc:
        return CheckResult(
            "Stop hook registered in settings.json",
            "FAIL",
            str(exc),
            hint="Run: python -m cortex install",
        )


def check_mcp_config(mcp_path: Path) -> CheckResult:
    """Check that the cortex MCP entry is in .mcp.json."""
    if not mcp_path.exists():
        return CheckResult(
            "MCP server in .mcp.json",
            "FAIL",
            f"{mcp_path} not found",
            hint="Run: python -m cortex install",
        )
    try:
        with mcp_path.open() as f:
            mcp = json.load(f)
        # Support both top-level and nested under "mcpServers"
        servers = mcp.get("mcpServers", mcp)
        if "cortex" in servers:
            return CheckResult("MCP server in .mcp.json", "PASS")
        return CheckResult(
            "MCP server in .mcp.json",
            "FAIL",
            "cortex entry not found",
            hint="Run: python -m cortex install",
        )
    except Exception as exc:
        return CheckResult(
            "MCP server in .mcp.json",
            "FAIL",
            str(exc),
            hint="Run: python -m cortex install",
        )


def check_remote_mcp(ssh_host: str) -> CheckResult:
    """Check that the MCP server on the remote host is reachable via SSH + HTTP.

    WARN (not FAIL) since this is optional infrastructure.
    """
    try:
        result = subprocess.run(
            [
                "ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                ssh_host,
                "curl -s --max-time 3 http://localhost:8765/health || echo FAIL",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip()
        if result.returncode != 0 or output == "FAIL" or not output:
            return CheckResult(
                f"Remote MCP server on {ssh_host}:8765",
                "WARN",
                f"unreachable (ssh rc={result.returncode}, output={output!r})",
                hint=f"Start the server on {ssh_host}: python -m cortex server --transport sse --port 8765",
            )
        return CheckResult(
            f"Remote MCP server on {ssh_host}:8765",
            "PASS",
            "HTTP health check responded",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            f"Remote MCP server on {ssh_host}:8765",
            "WARN",
            "SSH connection timed out",
            hint=f"Check that {ssh_host} is reachable via Tailscale",
        )
    except FileNotFoundError:
        return CheckResult(
            f"Remote MCP server on {ssh_host}:8765",
            "WARN",
            "ssh command not found",
        )
    except Exception as exc:
        return CheckResult(
            f"Remote MCP server on {ssh_host}:8765",
            "WARN",
            str(exc),
        )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_result(r: CheckResult) -> str:
    line = f"[{r.status}] {r.label}"
    if r.detail:
        line += f" ({r.detail})"
    if r.status == "FAIL" and r.hint:
        line += f"\n       → {r.hint}"
    return line


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_doctor(
    db_path: Path | None = None,
    remote: str | None = None,
    staging_dir: Path | None = None,
    settings_path: Path | None = None,
    mcp_path: Path | None = None,
) -> int:
    """Run all doctor checks and print results.

    Returns exit code: 0 if all PASS/WARN, 1 if any FAIL.

    All path arguments default to the standard locations. Override for testing.
    """
    home = Path.home()
    db_path = db_path or home / ".cortex" / "cortex.db"
    staging_dir = staging_dir or home / ".cortex" / "staging"
    settings_path = settings_path or home / ".claude" / "settings.json"
    mcp_path = mcp_path or home / ".claude" / ".mcp.json"

    # Run checks
    db_result, conn = check_db(db_path)
    results: list[CheckResult] = [
        db_result,
        check_fts5(conn),
        check_sqlite_vec(conn),
        check_fastembed(),
        check_staging_dir(staging_dir),
        check_stop_hook(settings_path),
        check_mcp_config(mcp_path),
    ]

    if remote:
        results.append(check_remote_mcp(remote))

    if conn:
        conn.close()

    # Print
    for r in results:
        print(_render_result(r))

    # Exit code
    has_fail = any(r.status == "FAIL" for r in results)
    return 1 if has_fail else 0
