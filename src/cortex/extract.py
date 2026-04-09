"""Extraction pipeline: promote raw chunks to curated memories via LLM prompts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from cortex.curated import remember


VALID_TYPES = {"decision", "preference", "procedure", "entity", "fact", "idea", "insight"}

EXTRACTION_PROMPT_TEMPLATE = """\
You are a memory extraction agent. Below are raw text chunks from various sources.
Your job is to extract distinct, reusable memories from them.

Each memory should be a concise, standalone statement of knowledge — something
worth remembering long-term. Categorize each as one of: decision, preference,
procedure, entity, fact, idea.

Link each memory back to the raw chunk IDs it was derived from.

Return ONLY a JSON array (no markdown, no explanation) in this format:
[
  {{"raw_chunk_ids": [1, 3], "content": "Dan prefers SQLite over PostgreSQL", "type": "preference"}},
  {{"raw_chunk_ids": [2], "content": "Daimon is the Telegram bot", "type": "entity"}}
]

Valid types: decision, preference, procedure, entity, fact, idea.
If no useful memories can be extracted, return an empty array: []

--- RAW CHUNKS ---

{chunks}
"""


def _get_unextracted_chunks(
    conn: sqlite3.Connection,
    scope: str = "recent",
) -> list[dict[str, Any]]:
    """Return raw chunks that have no entry in the extractions table.

    Parameters
    ----------
    scope:
        'recent' — only chunks from the last 24 hours.
        'all' — all unextracted chunks.
    """
    base_query = """
        SELECT rc.id, rc.content, rc.source, rc.source_type, rc.created_at
        FROM raw_chunks rc
        WHERE rc.id NOT IN (SELECT DISTINCT raw_chunk_id FROM extractions)
    """
    params: list[Any] = []

    if scope == "recent":
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        base_query += " AND rc.created_at >= ?"
        params.append(cutoff)

    base_query += " ORDER BY rc.created_at ASC"

    rows = conn.execute(base_query, params).fetchall()
    return [
        {
            "id": row[0],
            "content": row[1],
            "source": row[2],
            "source_type": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def extract_prompt(
    conn: sqlite3.Connection,
    scope: str = "recent",
) -> str | None:
    """Generate a prompt listing unextracted raw chunks for an LLM.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    scope:
        'recent' (default) — only chunks from last 24 hours.
        'all' — all unextracted chunks.

    Returns
    -------
    The prompt string, or None if there are no unextracted chunks.
    """
    chunks = _get_unextracted_chunks(conn, scope=scope)
    if not chunks:
        return None

    chunk_lines = []
    for chunk in chunks:
        chunk_lines.append(
            f"[ID {chunk['id']}] ({chunk['source_type']}, {chunk['created_at']})\n"
            f"{chunk['content']}\n"
        )

    chunks_text = "\n---\n".join(chunk_lines)
    return EXTRACTION_PROMPT_TEMPLATE.format(chunks=chunks_text)


def process_extraction(
    conn: sqlite3.Connection,
    extraction_json: str | list[dict[str, Any]],
) -> dict[str, int]:
    """Parse LLM extraction output and create curated memories + extraction links.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    extraction_json:
        Either a JSON string or already-parsed list of extraction dicts.
        Each dict must have: raw_chunk_ids (list[int]), content (str), type (str).

    Returns
    -------
    Dict with keys: memories_created, extractions_linked.
    """
    if isinstance(extraction_json, str):
        data = json.loads(extraction_json)
    else:
        data = extraction_json

    if not isinstance(data, list):
        raise ValueError("Extraction JSON must be a list of objects")

    memories_created = 0
    extractions_linked = 0

    for item in data:
        raw_chunk_ids = item.get("raw_chunk_ids", [])
        content = item.get("content", "").strip()
        mem_type = item.get("type", "fact")

        if not content:
            continue

        # Validate type
        if mem_type not in VALID_TYPES:
            mem_type = "fact"

        # Skip if all referenced chunks are already extracted
        if raw_chunk_ids:
            placeholders = ",".join("?" for _ in raw_chunk_ids)
            already = conn.execute(
                f"SELECT COUNT(DISTINCT raw_chunk_id) FROM extractions "
                f"WHERE raw_chunk_id IN ({placeholders})",
                raw_chunk_ids,
            ).fetchone()[0]
            if already == len(raw_chunk_ids):
                continue

        # Create curated memory
        memory_id = remember(
            conn,
            content,
            type=mem_type,
            source="extraction",
        )
        memories_created += 1

        # Create extraction links
        for chunk_id in raw_chunk_ids:
            # Skip if this specific link already exists
            exists = conn.execute(
                "SELECT 1 FROM extractions WHERE raw_chunk_id = ? AND curated_memory_id = ?",
                (chunk_id, memory_id),
            ).fetchone()
            if exists:
                continue

            conn.execute(
                "INSERT INTO extractions (raw_chunk_id, curated_memory_id) VALUES (?, ?)",
                (chunk_id, memory_id),
            )
            extractions_linked += 1

        conn.commit()

    return {"memories_created": memories_created, "extractions_linked": extractions_linked}


def main() -> None:
    """CLI entry point for extraction pipeline."""
    import argparse
    import sys

    from cortex.db import init_db

    parser = argparse.ArgumentParser(
        description="Cortex extraction pipeline: raw chunks to curated memories.",
    )
    parser.add_argument(
        "--db",
        default="cortex.db",
        help="Path to the Cortex database (default: cortex.db)",
    )
    parser.add_argument(
        "--scope",
        default="recent",
        choices=["recent", "all"],
        help="Scope of chunks to extract: 'recent' (last 24h) or 'all' (default: recent)",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Read extraction JSON from stdin and process it",
    )
    args = parser.parse_args()

    conn = init_db(args.db)

    if args.process:
        # Read JSON from stdin and process
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            print("No input received on stdin", file=sys.stderr)
            sys.exit(1)
        result = process_extraction(conn, raw_input)
        print(
            f"{result['memories_created']} memories created, "
            f"{result['extractions_linked']} extractions linked"
        )
    else:
        # Generate prompt and output to stdout
        prompt = extract_prompt(conn, scope=args.scope)
        if prompt is None:
            print("No unextracted chunks found.", file=sys.stderr)
            sys.exit(0)
        print(prompt)

    conn.close()


if __name__ == "__main__":
    main()
