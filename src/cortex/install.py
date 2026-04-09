"""One-command installer for Cortex.

Sets up everything a new user needs:
  - Creates ~/.cortex/ and initializes the DB
  - Copies shell scripts to ~/scripts/
  - Adds Stop hook (cortex-capture.sh) to ~/.claude/settings.json
  - Adds SessionStart hook (cortex-session-start.sh) to ~/.claude/settings.json
  - Adds cortex MCP entry to ~/.claude/.mcp.json

Non-destructive and idempotent — running twice is safe.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

# The MCP entry to add to .mcp.json
MCP_ENTRY = {
    "type": "sse",
    "url": "http://100.108.198.107:8765/sse",
}

# Hook commands
CAPTURE_CMD = "bash ~/scripts/cortex-capture.sh"
SESSION_START_CMD = "bash ~/scripts/cortex-session-start.sh"

# Source scripts (relative to this file's package root)
_PACKAGE_DIR = Path(__file__).parent
_PROJECT_ROOT = _PACKAGE_DIR.parent.parent  # src/cortex -> src -> project_root
_SCRIPTS_SRC = _PROJECT_ROOT / "scripts"


def _print_step(label: str, status: str, detail: str = "") -> None:
    """Print a formatted step line."""
    marker = "[done]" if status == "done" else "[skip]" if status == "skip" else "[info]"
    line = f"  {marker} {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def _ensure_cortex_dir(cortex_dir: Path) -> str:
    """Create ~/.cortex/ if it doesn't exist. Returns 'done' or 'skip'."""
    if cortex_dir.exists():
        return "skip"
    cortex_dir.mkdir(parents=True, exist_ok=True)
    return "done"


def _init_db(db_path: Path) -> str:
    """Initialize the Cortex DB. Returns 'done' or 'skip'."""
    if db_path.exists():
        return "skip"
    # Import init_db here so install can be imported without heavy deps
    from cortex.db import init_db

    conn = init_db(str(db_path))
    conn.close()
    return "done"


def _copy_scripts(scripts_dest: Path) -> list[tuple[str, str]]:
    """Copy cortex-capture.sh and cortex-session-start.sh to ~/scripts/.

    Returns a list of (script_name, status) tuples.
    """
    scripts_dest.mkdir(parents=True, exist_ok=True)
    results = []

    for script_name in ("cortex-capture.sh", "cortex-session-start.sh"):
        dest = scripts_dest / script_name
        src = _SCRIPTS_SRC / script_name

        if dest.exists():
            results.append((script_name, "skip"))
            continue

        if src.exists():
            shutil.copy2(src, dest)
            dest.chmod(0o755)
            results.append((script_name, "done"))
        else:
            # Script source not found — create a placeholder with a clear message
            results.append((script_name, f"WARN: source not found at {src}"))

    return results


def _hook_command_present(hooks_list: list[dict], command: str) -> bool:
    """Check whether a hook entry with the given command already exists."""
    for group in hooks_list:
        for hook in group.get("hooks", []):
            if hook.get("command") == command:
                return True
    return False


def _add_hook(settings_path: Path, hook_type: str, command: str) -> str:
    """Add a hook to ~/.claude/settings.json non-destructively.

    Returns 'done' or 'skip'.
    """
    # Load or create settings
    if settings_path.exists():
        with settings_path.open() as f:
            settings = json.load(f)
    else:
        settings = {}

    if "hooks" not in settings:
        settings["hooks"] = {}

    hooks = settings["hooks"]
    if hook_type not in hooks:
        hooks[hook_type] = []

    if _hook_command_present(hooks[hook_type], command):
        return "skip"

    # Append a new hook group entry
    hooks[hook_type].append({"hooks": [{"type": "command", "command": command}]})

    with settings_path.open("w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    return "done"


def _add_mcp_entry(mcp_path: Path, key: str, entry: dict) -> str:
    """Add the cortex MCP entry to ~/.claude/.mcp.json non-destructively.

    Returns 'done' or 'skip'.
    """
    if mcp_path.exists():
        with mcp_path.open() as f:
            mcp = json.load(f)
    else:
        mcp = {}

    # Support both top-level and nested under "mcpServers"
    servers = mcp.get("mcpServers", mcp)

    if key in servers:
        return "skip"

    # Add to mcpServers if that key exists, else top-level
    if "mcpServers" in mcp:
        mcp["mcpServers"][key] = entry
    else:
        mcp[key] = entry

    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    with mcp_path.open("w") as f:
        json.dump(mcp, f, indent=2)
        f.write("\n")

    return "done"


def main(
    cortex_dir: Path | None = None,
    scripts_dir: Path | None = None,
    settings_path: Path | None = None,
    mcp_path: Path | None = None,
) -> None:
    """Run the Cortex installer.

    All path arguments default to the standard locations. Override for testing.
    """
    home = Path.home()
    cortex_dir = cortex_dir or home / ".cortex"
    scripts_dir = scripts_dir or home / "scripts"
    settings_path = settings_path or home / ".claude" / "settings.json"
    mcp_path = mcp_path or home / ".claude" / ".mcp.json"

    db_path = cortex_dir / "cortex.db"

    print("Cortex installer")
    print("=" * 40)

    # 1. Create ~/.cortex/
    status = _ensure_cortex_dir(cortex_dir)
    _print_step(
        f"Create {cortex_dir}",
        status,
        "created" if status == "done" else "already exists",
    )

    # 2. Initialize DB
    status = _init_db(db_path)
    _print_step(
        f"Initialize DB at {db_path}",
        status,
        "initialized" if status == "done" else "already exists",
    )

    # 3. Copy shell scripts
    script_results = _copy_scripts(scripts_dir)
    for script_name, status in script_results:
        if status == "done":
            _print_step(f"Copy {script_name} to {scripts_dir}", "done", "installed")
        elif status == "skip":
            _print_step(f"Copy {script_name} to {scripts_dir}", "skip", "already present")
        else:
            _print_step(f"Copy {script_name} to {scripts_dir}", "info", status)

    # 4. Add Stop hook
    status = _add_hook(settings_path, "Stop", CAPTURE_CMD)
    _print_step(
        "Add Stop hook (cortex-capture.sh) to settings.json",
        status,
        "added" if status == "done" else "already present",
    )

    # 5. Add SessionStart hook
    status = _add_hook(settings_path, "SessionStart", SESSION_START_CMD)
    _print_step(
        "Add SessionStart hook (cortex-session-start.sh) to settings.json",
        status,
        "added" if status == "done" else "already present",
    )

    # 6. Add MCP entry
    status = _add_mcp_entry(mcp_path, "cortex", MCP_ENTRY)
    _print_step(
        "Add cortex MCP entry to .mcp.json",
        status,
        "added" if status == "done" else "already present",
    )

    print("=" * 40)
    print("Done. Run `python -m cortex status` to verify.")
