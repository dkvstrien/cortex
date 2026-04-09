"""MEMORY.md migration: import existing memory entries into curated layer."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


# Map section headers to curated memory types.
# The original MEMORY.md used Project/User/Feedback/Reference sections.
# Newer formats may use different names — we map common ones.
SECTION_TYPE_MAP: dict[str, str] = {
    "project": "entity",
    "active projects": "entity",
    "user": "preference",
    "dan": "preference",
    "feedback": "procedure",
    "tools & environments": "procedure",
    "reference": "fact",
    "areas": "entity",
}

SOURCE = "memory_md_migration"

# Pattern: - [title](file.md) — description
_ENTRY_RE = re.compile(
    r"^-\s+\[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)\s*(?:—|--|-)\s*(?P<desc>.+)$"
)


def _parse_memory_md(text: str) -> list[dict[str, Any]]:
    """Parse a MEMORY.md file into a list of entry dicts.

    Returns a list of dicts with keys: title, file, description, type.
    """
    entries: list[dict[str, Any]] = []
    current_type: str | None = None

    for line in text.splitlines():
        line = line.strip()

        # Section header
        if line.startswith("## "):
            section_name = line[3:].strip()
            current_type = SECTION_TYPE_MAP.get(section_name.lower())
            continue

        # Entry line
        if current_type is None:
            continue
        m = _ENTRY_RE.match(line)
        if m:
            entries.append(
                {
                    "title": m.group("title"),
                    "file": m.group("file"),
                    "description": m.group("desc").strip(),
                    "type": current_type,
                }
            )

    return entries


def _read_linked_file(memory_md_dir: Path, filename: str) -> str | None:
    """Read a linked .md file if it exists in the same directory."""
    path = memory_md_dir / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def _build_content(entry: dict[str, Any], linked_content: str | None) -> str:
    """Build the memory content string from an entry and its linked file."""
    parts = [f"{entry['title']}: {entry['description']}"]
    if linked_content:
        parts.append(f"\n---\n{linked_content.strip()}")
    return "\n".join(parts)


def _memory_exists(conn: sqlite3.Connection, content: str) -> bool:
    """Check if a memory with the same source and content already exists."""
    row = conn.execute(
        "SELECT 1 FROM curated_memories WHERE source = ? AND content = ? LIMIT 1",
        (SOURCE, content),
    ).fetchone()
    return row is not None


def migrate_memory_md(
    conn: sqlite3.Connection,
    path: str | Path,
) -> dict[str, int]:
    """Read a MEMORY.md file and import entries into the curated layer.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    path:
        Path to the MEMORY.md file.

    Returns
    -------
    Dict with keys: imported, skipped.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    entries = _parse_memory_md(text)
    memory_dir = path.parent

    imported = 0
    skipped = 0

    for entry in entries:
        linked_content = _read_linked_file(memory_dir, entry["file"])
        content = _build_content(entry, linked_content)

        if _memory_exists(conn, content):
            skipped += 1
            continue

        conn.execute(
            """
            INSERT INTO curated_memories (content, type, source, tags, confidence)
            VALUES (?, ?, ?, '[]', 1.0)
            """,
            (content, entry["type"], SOURCE),
        )
        imported += 1

    conn.commit()
    return {"imported": imported, "skipped": skipped}


def main() -> None:
    """CLI entry point: python -m cortex.migrate <path> --db <path>."""
    import argparse

    from cortex.db import init_db

    parser = argparse.ArgumentParser(
        description="Import MEMORY.md entries into Cortex curated layer"
    )
    parser.add_argument("path", help="Path to MEMORY.md file")
    parser.add_argument(
        "--db",
        default="cortex.db",
        help="Path to Cortex database (default: cortex.db)",
    )
    args = parser.parse_args()

    conn = init_db(args.db)
    result = migrate_memory_md(conn, args.path)
    conn.close()

    print(f"{result['imported']} memories imported, {result['skipped']} skipped (duplicates)")


if __name__ == "__main__":
    main()
