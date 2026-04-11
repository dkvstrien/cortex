"""Reflect pipeline: synthesize higher-level insights from curated memories.

Usage (without --process): generate a reflection prompt and print to stdout.
    python -m cortex reflect --db <path>

Usage (with --process): read Haiku's JSON output from stdin and store insights.
    python -m cortex reflect --db <path> --process

Cron workflow (Sunday):
    python -m cortex reflect --db ~/.cortex/cortex.db | haiku | python -m cortex reflect --db ~/.cortex/cortex.db --process
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from cortex.curated import remember

logger = logging.getLogger("cortex")

# Meta table key for tracking already-reflected memory IDs
_META_KEY_REFLECTED_IDS = "reflected_ids"

REFLECTION_PROMPT_TEMPLATE = """\
You are a memory insight agent. Below are curated memories grouped by type.
Your job is to synthesize HIGH-CONFIDENCE patterns across the group.

These insights will be read by a future Claude instance working with the
user. Insights that are over-general, too literal, or thinly evidenced
cause real downstream harm: future Claude may interpret them as rules
and follow them rigidly when it shouldn't. Err strongly on the side of
fewer, stronger insights.

## What counts as a good insight

- **Observational, not prescriptive.** Describe patterns in how Dan works.
  Never frame as a directive for future Claude to follow.
  - GOOD: "Pattern observed: across multi-day projects, Dan tends to
    prefer shipping incrementally over planning exhaustively upfront."
  - BAD: "Systems should ship incrementally and avoid upfront planning."
- **Hedged language.** Use "tends to", "often", "in this sample",
  "observed pattern". Never "always", "never", "should", "must".
- **Well-evidenced.** Requires at least 5 source memories that clearly
  support the same pattern. Three memories is not enough — two could
  be coincidence, five is a trend.
- **Non-trivial.** Something a future Claude wouldn't figure out from
  any single memory or from general priors about software engineers.
  "Dan uses git" is not an insight.
- **Durable.** Still likely true in six months. Skip patterns that
  depend on the current state of one specific project.

## Hard rules

1. If fewer than 5 source memories clearly support a pattern, DO NOT
   emit it. Return a smaller array, or [].
2. Never invent themes that aren't directly supported by the listed
   memories. If the evidence isn't there, don't reach.
3. Quality over quantity. 3 strong insights beat 10 weak ones.
   Returning [] is a valid and correct answer when the sample is thin.
4. Never contradict a memory you cite. If memories disagree, either
   note the tension explicitly or skip the pattern entirely.

## Output format

Return ONLY a JSON array (no markdown fences, no prose):
[
  {{
    "content": "Pattern observed: Dan tends to prefer local-first tools over cloud services across infrastructure, note-taking, and media — often citing operational control and token/cost efficiency",
    "type": "insight",
    "source_ids": [12, 44, 87, 103, 156, 201]
  }}
]

- type must always be "insight"
- source_ids must reference IDs from the memories listed below
- Minimum 5 source_ids per insight
- If nothing meets the bar, return: []

--- CURATED MEMORIES BY TYPE ---

{memories_by_type}
"""


def _get_reflected_ids(conn: sqlite3.Connection) -> set[int]:
    """Return the set of curated memory IDs already processed by reflect."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?",
        (_META_KEY_REFLECTED_IDS,),
    ).fetchone()
    if row is None or not row[0]:
        return set()
    try:
        return set(json.loads(row[0]))
    except (json.JSONDecodeError, TypeError):
        return set()


def _save_reflected_ids(conn: sqlite3.Connection, ids: set[int]) -> None:
    """Persist the set of reflected memory IDs to the meta table."""
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (_META_KEY_REFLECTED_IDS, json.dumps(sorted(ids))),
    )
    conn.commit()


def _get_unreflected_memories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return curated memories not yet included in a reflection batch.

    Excludes soft-deleted memories, superseded memories, and memories that
    were themselves created by the reflect pipeline (type='insight',
    source='reflect').
    """
    already_reflected = _get_reflected_ids(conn)

    rows = conn.execute(
        """
        SELECT id, content, type, source, tags, confidence, created_at
        FROM curated_memories
        WHERE deleted_at IS NULL
          AND id NOT IN (
              SELECT supersedes_id FROM curated_memories
              WHERE supersedes_id IS NOT NULL
          )
          AND NOT (type = 'insight' AND source = 'reflect')
        ORDER BY type, created_at ASC
        """
    ).fetchall()

    result = []
    for row in rows:
        mem_id = row[0]
        if mem_id in already_reflected:
            continue
        result.append(
            {
                "id": mem_id,
                "content": row[1],
                "type": row[2],
                "source": row[3],
                "tags": json.loads(row[4]) if row[4] else [],
                "confidence": row[5],
                "created_at": row[6],
            }
        )
    return result


def reflect_prompt(conn: sqlite3.Connection) -> str | None:
    """Generate a reflection prompt grouping curated memories by type.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.

    Returns
    -------
    The prompt string, or None if there are no unreflected memories.
    """
    memories = _get_unreflected_memories(conn)
    if not memories:
        return None

    # Group by type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for mem in memories:
        mem_type = mem["type"]
        by_type.setdefault(mem_type, []).append(mem)

    # Build the memories section
    sections = []
    for mem_type, mems in sorted(by_type.items()):
        lines = [f"### {mem_type.upper()} ({len(mems)} memories)"]
        for mem in mems:
            tags_str = ", ".join(mem["tags"]) if mem["tags"] else ""
            tag_note = f" [tags: {tags_str}]" if tags_str else ""
            lines.append(f"[ID {mem['id']}] {mem['content']}{tag_note}")
        sections.append("\n".join(lines))

    memories_by_type_text = "\n\n".join(sections)
    return REFLECTION_PROMPT_TEMPLATE.format(memories_by_type=memories_by_type_text)


def process_reflection(
    conn: sqlite3.Connection,
    reflection_json: str | list[dict[str, Any]],
) -> dict[str, int]:
    """Parse LLM reflection output and create insight memories.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    reflection_json:
        Either a JSON string or already-parsed list of insight dicts.
        Each dict must have: content (str), type (str, always 'insight'),
        source_ids (list[int]).

    Returns
    -------
    Dict with keys: insights_created, source_ids_tracked.
    """
    if isinstance(reflection_json, str):
        # Strip markdown code fences if present (```json ... ```)
        text = reflection_json.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
            text = text.rsplit("```", 1)[0].strip()
        data = json.loads(text)
    else:
        data = reflection_json

    if not isinstance(data, list):
        raise ValueError("Reflection JSON must be a list of objects")

    insights_created = 0
    insights_skipped_low_evidence = 0
    all_source_ids: set[int] = set()

    for item in data:
        content = item.get("content", "").strip()
        source_ids = [int(i) for i in item.get("source_ids", [])]

        if not content:
            continue

        # Enforce the ≥5 source-memory evidence bar. The prompt asks for
        # it, but an LLM can drift — back-stop in code.
        if len(source_ids) < 5:
            insights_skipped_low_evidence += 1
            logger.debug(
                "Skipping insight with only %d source memories: %r",
                len(source_ids), content[:80],
            )
            continue

        # Store source_ids as JSON array in the tags field
        tags = [f"source:{sid}" for sid in source_ids]

        memory_id = remember(
            conn,
            content,
            type="insight",
            source="reflect",
            tags=tags,
        )
        insights_created += 1
        all_source_ids.update(source_ids)

        logger.debug(
            "Created insight memory id=%d from source_ids=%s", memory_id, source_ids
        )

    # Track all source IDs so they won't be re-reflected
    if all_source_ids:
        existing = _get_reflected_ids(conn)
        existing.update(all_source_ids)
        _save_reflected_ids(conn, existing)

    return {
        "insights_created": insights_created,
        "source_ids_tracked": len(all_source_ids),
        "insights_skipped_low_evidence": insights_skipped_low_evidence,
    }


def main() -> None:
    """CLI entry point for reflect pipeline.

    Cron comment — add to Sunday crontab on ThinkPad:
    # 0 3 * * 0 python -m cortex reflect --db ~/.cortex/cortex.db | haiku | python -m cortex reflect --db ~/.cortex/cortex.db --process
    """
    import argparse
    import sys

    from cortex.db import init_db

    parser = argparse.ArgumentParser(
        description="Cortex reflect pipeline: synthesize insights from curated memories.",
    )
    parser.add_argument(
        "--db",
        default="cortex.db",
        help="Path to the Cortex database (default: cortex.db)",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Read reflection JSON from stdin and process it into insight memories",
    )
    args = parser.parse_args()

    conn = init_db(args.db)

    if args.process:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            print("No input received on stdin", file=sys.stderr)
            sys.exit(1)
        result = process_reflection(conn, raw_input)
        print(
            f"{result['insights_created']} insights created, "
            f"{result['source_ids_tracked']} source IDs tracked"
        )
    else:
        prompt = reflect_prompt(conn)
        if prompt is None:
            print("No unreflected memories found.", file=sys.stderr)
            sys.exit(0)
        print(prompt)

    conn.close()


if __name__ == "__main__":
    main()
