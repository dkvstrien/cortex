"""Extraction pipeline: promote raw chunks to curated memories via LLM prompts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from cortex.curated import remember, recall_curated, supersede


VALID_TYPES = {"decision", "preference", "procedure", "entity", "fact", "idea", "insight"}

EXTRACTION_PROMPT_TEMPLATE = """\
You are a memory extraction agent for Dan's long-term memory. The raw text
chunks below are from past Claude Code sessions. Your job is to extract
DURABLE, REUSABLE memories a future Claude would actually want to retrieve.

## What makes a good memory

Extract things that will still be true and useful weeks or months from now:
- Decisions Dan made (with the reason, not just the outcome)
- Preferences Dan stated or that correction patterns implied
- Procedures/how-tos for recurring tasks (specific enough to follow)
- Entities: named projects, people, tools, services, with a one-line purpose
- Durable facts: API endpoints, file paths, credentials locations, hard numbers
- Ideas Dan is actively considering (captured in his own framing when possible)

Each memory MUST be:
- Self-contained — readable without the original context
- Specific — names the thing, the path, the number, the "why"
- Non-obvious — worth the retrieval cost (skip platitudes)

## Hard rules (do not violate)

1. NEVER invent numbers, thresholds, quantities, dates, or names that are
   not explicitly stated in the chunks. If Dan didn't say "50+", don't say
   "50+". Prefer omitting a number to guessing one.
2. DO NOT extract ephemeral state: "X has 44 memories", "widget shows 52%",
   "currently 3 pending jobs", "process is running". These change hourly
   and poison retrieval. Extract the durable fact BEHIND the snapshot
   ("Cortex tracks memory count via status endpoint") not the snapshot itself.
3. DO NOT extract universal platitudes: "Dan prefers simpler solutions",
   "Dan values reliability". True of everyone; adds no signal.
4. DO NOT conflate concurrent topics. If Dan mentions a tutor bot AND Cortex
   in the same session, do not say "Cortex includes a tutor bot" unless the
   chunks explicitly make that link.
5. DO NOT extract the same memory twice with different wording. If chunks 2
   and 7 both describe the same idea, emit ONE memory linking both chunk IDs.
6. If Dan corrects Claude ("no, use trash not rm"), that correction IS the
   memory — extract it as a preference, in Dan's own framing.

## Tags

Every memory MUST include 2–4 lowercase tags in a "tags" array. Tags enable
faceted retrieval. Examples: ["cortex", "extraction", "haiku"],
["russian", "lute", "tts"], ["farm", "sebastian", "tractor"],
["leseraum", "api", "deployment"]. Use domain names Dan uses in conversation.

## Output format

Return ONLY a JSON array (no markdown fences, no prose, no explanation):
[
  {{
    "raw_chunk_ids": [1, 3],
    "content": "Dan uses uv to manage Python environments for Mac projects; never pip install globally",
    "type": "preference",
    "tags": ["python", "uv", "mac"]
  }},
  {{
    "raw_chunk_ids": [2],
    "content": "Daimon is the Telegram bot running as a bare process on ThinkPad (not the Docker telegram-bot container)",
    "type": "entity",
    "tags": ["daimon", "telegram", "thinkpad"]
  }}
]

Valid types: decision, preference, procedure, entity, fact, idea.
If no useful memories can be extracted from these chunks, return: []

{existing_section}--- RAW CHUNKS ---

{chunks}
"""

EXISTING_MEMORIES_SECTION = """\
--- EXISTING RELATED MEMORIES (for contradiction detection) ---

{existing_memories}
If any new memory you extract DIRECTLY CONTRADICTS an existing memory listed above,
add "supersedes": <existing_id> to that item. Only use supersedes for direct
contradictions, not minor updates.

Example with supersedes:
[
  {{"raw_chunk_ids": [5], "content": "Dan switched to SQLite exclusively", "type": "preference", "supersedes": 12}}
]

"""


def _get_unextracted_chunks(
    conn: sqlite3.Connection,
    scope: str = "recent",
    limit: int | None = None,
    skip_tried: bool = False,
) -> list[dict[str, Any]]:
    """Return raw chunks that have no entry in the extractions table.

    Parameters
    ----------
    scope:
        'recent' — only chunks from the last 24 hours.
        'all' — all unextracted chunks.
    limit:
        Maximum number of chunks to return. None = no limit.
    skip_tried:
        If True, also exclude chunks that have already been offered to the
        extractor (tried_at IS NOT NULL). Prevents the backfill loop from
        re-picking the same chunks when a batch produces no memories.
    """
    base_query = """
        SELECT rc.id, rc.content, rc.source, rc.source_type, rc.created_at
        FROM raw_chunks rc
        WHERE rc.id NOT IN (SELECT DISTINCT raw_chunk_id FROM extractions)
    """
    params: list[Any] = []

    if skip_tried:
        base_query += " AND rc.tried_at IS NULL"

    if scope == "recent":
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        base_query += " AND rc.created_at >= ?"
        params.append(cutoff)

    base_query += " ORDER BY rc.created_at ASC"

    if limit is not None:
        base_query += " LIMIT ?"
        params.append(limit)

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


def _get_similar_existing_memories(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return up to *limit* existing curated memories most similar to *query*.

    Uses FTS5 search via recall_curated.  Returns an empty list if the query
    produces no results or if the FTS index is empty.
    """
    if not query.strip():
        return []
    try:
        return recall_curated(conn, query, limit=limit)
    except Exception:
        return []


def extract_prompt(
    conn: sqlite3.Connection,
    scope: str = "recent",
    limit: int | None = None,
    mark_tried: bool = False,
) -> str | None:
    """Generate a prompt listing unextracted raw chunks for an LLM.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    scope:
        'recent' (default) — only chunks from last 24 hours.
        'all' — all unextracted chunks.
    limit:
        Maximum number of chunks to include in the prompt. None = all.
    mark_tried:
        If True, exclude chunks that have already been tried, and mark the
        returned chunks with tried_at=now before returning the prompt. Use
        this in batched backfill loops so a batch that yields no memories
        does not get re-selected on the next iteration.

    Returns
    -------
    The prompt string, or None if there are no unextracted chunks.
    """
    chunks = _get_unextracted_chunks(
        conn, scope=scope, limit=limit, skip_tried=mark_tried
    )
    if not chunks:
        return None

    if mark_tried:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        chunk_ids = [c["id"] for c in chunks]
        placeholders = ",".join("?" for _ in chunk_ids)
        conn.execute(
            f"UPDATE raw_chunks SET tried_at = ? WHERE id IN ({placeholders})",
            [now, *chunk_ids],
        )
        conn.commit()

    chunk_lines = []
    for chunk in chunks:
        chunk_lines.append(
            f"[ID {chunk['id']}] ({chunk['source_type']}, {chunk['created_at']})\n"
            f"{chunk['content']}\n"
        )

    chunks_text = "\n---\n".join(chunk_lines)

    # Gather top-5 similar existing curated memories for contradiction detection.
    # Build a combined query from the chunk contents (up to 500 chars to avoid huge queries).
    combined_content = " ".join(c["content"] for c in chunks)[:500]
    existing_memories = _get_similar_existing_memories(conn, combined_content, limit=5)

    if existing_memories:
        existing_lines = "\n".join(
            f"[EXISTING #{m['id']}] {m['content']}" for m in existing_memories
        )
        existing_section = EXISTING_MEMORIES_SECTION.format(existing_memories=existing_lines)
    else:
        existing_section = ""

    return EXTRACTION_PROMPT_TEMPLATE.format(chunks=chunks_text, existing_section=existing_section)


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
        # Strip markdown code fences if present (e.g. ```json ... ```)
        text = extraction_json.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
            text = text.rsplit("```", 1)[0].strip()
        data = json.loads(text)
    else:
        data = extraction_json

    if not isinstance(data, list):
        raise ValueError("Extraction JSON must be a list of objects")

    memories_created = 0
    extractions_linked = 0

    for item in data:
        raw_chunk_ids = item.get("raw_chunk_ids", [])

        # Derive session_id from the first referenced raw chunk's source.
        # raw_chunks.source format: "staging:2026-04-09.jsonl:SESSION_ID"
        session_id = "extraction"  # fallback for non-session sources
        if raw_chunk_ids:
            chunk_row = conn.execute(
                "SELECT source FROM raw_chunks WHERE id = ?", (raw_chunk_ids[0],)
            ).fetchone()
            if chunk_row and chunk_row[0]:
                parts = chunk_row[0].split(":")
                if len(parts) >= 3:
                    session_id = parts[-1]

        content = item.get("content", "").strip()
        mem_type = item.get("type", "fact")

        if not content:
            continue

        # Validate type
        if mem_type not in VALID_TYPES:
            mem_type = "fact"

        # Validate tags — must be a list of non-empty strings. Silently
        # drop malformed tags rather than failing the whole batch.
        raw_tags = item.get("tags", [])
        tags = [
            t.strip().lower()
            for t in raw_tags
            if isinstance(t, str) and t.strip()
        ] if isinstance(raw_tags, list) else []

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

        # Create curated memory — either superseding an existing one or fresh.
        supersedes_id = item.get("supersedes")
        if supersedes_id is not None:
            try:
                memory_id = supersede(
                    conn,
                    int(supersedes_id),
                    content,
                    type=mem_type,
                    source=session_id,
                    tags=tags,
                )
            except KeyError:
                # Old memory doesn't exist — fall back to remember()
                memory_id = remember(
                    conn,
                    content,
                    type=mem_type,
                    source=session_id,
                    tags=tags,
                )
        else:
            memory_id = remember(
                conn,
                content,
                type=mem_type,
                source=session_id,
                tags=tags,
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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of chunks to include in one extraction batch",
    )
    parser.add_argument(
        "--mark-tried",
        action="store_true",
        help="Mark selected chunks as tried so empty batches don't recycle",
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
        prompt = extract_prompt(
            conn,
            scope=args.scope,
            limit=args.limit,
            mark_tried=args.mark_tried,
        )
        if prompt is None:
            print("No unextracted chunks found.", file=sys.stderr)
            sys.exit(0)
        print(prompt)

    conn.close()


if __name__ == "__main__":
    main()
