"""Tests for cortex.migrate: MEMORY.md migration ingestion."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cortex.db import init_db
from cortex.migrate import migrate_memory_md, _parse_memory_md, SOURCE


SAMPLE_MEMORY_MD = """\
# Memory Index

## Project
- [leseraum.md](./project_leseraum.md) — Language reader app, deployed on ThinkPad, 174 tests
- [tagtime.md](./project_tagtime.md) — Stochastic life tracker on ThinkPad

## User
- [russian_level.md](./user_russian_level.md) — Russian A1, passive comprehension details

## Feedback
- [code_is_docs.md](./feedback_code_is_docs.md) — Don't maintain docs; read code/scripts/configs directly
- [ssh_between_machines.md](./feedback_ssh.md) — SSH always available Mac-ThinkPad

## Reference
- [infrastructure.md](./reference_infra.md) — Mac + ThinkPad setup, Docker services, key paths
- [vikunja.md](./reference_vikunja.md) — Task manager at tasks.dkvs8001.org
"""

# Newer format with different section names
SAMPLE_MEMORY_MD_V2 = """\
# Memory Index

## Dan
- [profile.md](./profile.md) — Location, role, languages, key context

## Active Projects
- [leseraum.md](./project_leseraum.md) — Language reader app

## Tools & Environments
- [tools.md](./tools.md) — Where Whisper, TTS, ffmpeg, uv live

## Reference
- [infra.md](./reference_infra.md) — Mac + ThinkPad setup

## Areas
- [languages.md](./project_language_learning.md) — German B1, Russian A1
"""


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


class TestParseMemoryMd:
    def test_parses_all_entries(self):
        entries = _parse_memory_md(SAMPLE_MEMORY_MD)
        assert len(entries) == 7

    def test_project_entries_are_entity(self):
        entries = _parse_memory_md(SAMPLE_MEMORY_MD)
        project_entries = [e for e in entries if e["title"] == "leseraum.md"]
        assert len(project_entries) == 1
        assert project_entries[0]["type"] == "entity"

    def test_user_entries_are_preference(self):
        entries = _parse_memory_md(SAMPLE_MEMORY_MD)
        user_entries = [e for e in entries if e["type"] == "preference"]
        assert len(user_entries) == 1

    def test_feedback_entries_are_procedure(self):
        entries = _parse_memory_md(SAMPLE_MEMORY_MD)
        procedure_entries = [e for e in entries if e["type"] == "procedure"]
        assert len(procedure_entries) == 2

    def test_reference_entries_are_fact(self):
        entries = _parse_memory_md(SAMPLE_MEMORY_MD)
        fact_entries = [e for e in entries if e["type"] == "fact"]
        assert len(fact_entries) == 2

    def test_extracts_title_file_description(self):
        entries = _parse_memory_md(SAMPLE_MEMORY_MD)
        leseraum = [e for e in entries if e["title"] == "leseraum.md"][0]
        assert leseraum["file"] == "./project_leseraum.md"
        assert "Language reader app" in leseraum["description"]

    def test_newer_format_sections(self):
        entries = _parse_memory_md(SAMPLE_MEMORY_MD_V2)
        assert len(entries) == 5
        types = {e["title"]: e["type"] for e in entries}
        assert types["profile.md"] == "preference"  # Dan section
        assert types["leseraum.md"] == "entity"  # Active Projects
        assert types["tools.md"] == "procedure"  # Tools & Environments
        assert types["infra.md"] == "fact"  # Reference
        assert types["languages.md"] == "entity"  # Areas

    def test_skips_unknown_sections(self):
        text = "## Unknown Section\n- [foo.md](./foo.md) — something\n"
        entries = _parse_memory_md(text)
        assert len(entries) == 0

    def test_empty_file(self):
        entries = _parse_memory_md("")
        assert entries == []

    def test_header_only_no_entries(self):
        entries = _parse_memory_md("# Memory Index\n\n## Project\n\n## User\n")
        assert entries == []


class TestMigrateMemoryMd:
    def _write_memory_md(self, tmp_path: Path, content: str = SAMPLE_MEMORY_MD) -> Path:
        md_path = tmp_path / "memory" / "MEMORY.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(content, encoding="utf-8")
        return md_path

    def _write_linked_file(self, md_path: Path, filename: str, content: str) -> None:
        linked = md_path.parent / filename
        linked.write_text(content, encoding="utf-8")

    def test_imports_all_entries(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path)
        result = migrate_memory_md(conn, md_path)
        assert result["imported"] == 7
        assert result["skipped"] == 0

    def test_source_is_memory_md_migration(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path)
        migrate_memory_md(conn, md_path)
        rows = conn.execute(
            "SELECT DISTINCT source FROM curated_memories"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == SOURCE

    def test_type_mapping(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path)
        migrate_memory_md(conn, md_path)
        types = conn.execute(
            "SELECT type, COUNT(*) FROM curated_memories GROUP BY type ORDER BY type"
        ).fetchall()
        type_map = dict(types)
        assert type_map["entity"] == 2  # Project entries
        assert type_map["preference"] == 1  # User entries
        assert type_map["procedure"] == 2  # Feedback entries
        assert type_map["fact"] == 2  # Reference entries

    def test_idempotent(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path)
        result1 = migrate_memory_md(conn, md_path)
        result2 = migrate_memory_md(conn, md_path)
        assert result1["imported"] == 7
        assert result2["imported"] == 0
        assert result2["skipped"] == 7
        # Total count should still be 7
        count = conn.execute("SELECT COUNT(*) FROM curated_memories").fetchone()[0]
        assert count == 7

    def test_includes_linked_file_content(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path)
        self._write_linked_file(
            md_path, "project_leseraum.md", "Leseraum is a reading app for language learning."
        )
        migrate_memory_md(conn, md_path)
        row = conn.execute(
            "SELECT content FROM curated_memories WHERE content LIKE '%leseraum%Language reader%'"
        ).fetchone()
        assert row is not None
        assert "Leseraum is a reading app" in row[0]

    def test_works_without_linked_files(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path)
        # No linked files created — should still work
        result = migrate_memory_md(conn, md_path)
        assert result["imported"] == 7

    def test_content_includes_title_and_description(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path)
        migrate_memory_md(conn, md_path)
        row = conn.execute(
            "SELECT content FROM curated_memories WHERE content LIKE '%tagtime%'"
        ).fetchone()
        assert row is not None
        assert "tagtime.md" in row[0]
        assert "Stochastic life tracker" in row[0]

    def test_newer_format(self, conn: sqlite3.Connection, tmp_path: Path):
        md_path = self._write_memory_md(tmp_path, content=SAMPLE_MEMORY_MD_V2)
        result = migrate_memory_md(conn, md_path)
        assert result["imported"] == 5
        assert result["skipped"] == 0

    def test_summary_output(self, conn: sqlite3.Connection, tmp_path: Path, capsys):
        """Verify the main() prints the expected summary format."""
        md_path = self._write_memory_md(tmp_path)
        result = migrate_memory_md(conn, md_path)
        summary = f"{result['imported']} memories imported, {result['skipped']} skipped (duplicates)"
        assert "imported" in summary
        assert "skipped" in summary
