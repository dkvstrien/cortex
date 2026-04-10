"""Classification pipeline: generate titles and open/closed status for sessions."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("cortex")

CLASSIFY_PROMPT_TEMPLATE = """\
You are classifying conversation sessions to make them searchable.
For each session below, return a JSON array with one object per session.

Return ONLY a JSON array (no markdown, no explanation):
[
  {{
    "session_id": "<id>",
    "title": "3-6 word descriptive title",
    "summary": "1-2 sentence description of what was discussed",
    "status": "open or closed",
    "tags": ["tag1", "tag2"]
  }}
]

"open" = a question went unanswered, a task was left unfinished, or the
conversation ended mid-thought without resolution.
"closed" = the topic reached a natural conclusion.

Use 2-4 lowercase tags describing the topic (e.g. "farm", "cortex", "russian", "lely").

If no sessions need classifying, return: []

--- SESSIONS ---

{sessions}
"""


def _get_unclassified_sessions(
    conn: sqlite3.Connection,
    limit: int = 20,
) -> list[dict]:
    """Return sessions with status='unprocessed', with their raw chunk content."""
    rows = conn.execute(
        """
        SELECT s.id, s.date, GROUP_CONCAT(rc.content, '\n\n') as content
        FROM sessions s
        LEFT JOIN raw_chunks rc
            ON rc.source LIKE '%:' || s.id
           AND rc.source_type = 'session'
        WHERE s.status = 'unprocessed'
        GROUP BY s.id
        ORDER BY s.date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {"session_id": row[0], "date": row[1], "content": row[2] or ""}
        for row in rows
    ]


def classify_prompt(conn: sqlite3.Connection) -> str | None:
    """Generate the Haiku classification prompt for unprocessed sessions.

    Returns None if there are no unprocessed sessions.
    """
    sessions = _get_unclassified_sessions(conn)
    if not sessions:
        return None

    session_blocks = []
    for s in sessions:
        block = f"SESSION {s['session_id']} ({s['date']}):\n{s['content'][:2000]}"
        session_blocks.append(block)

    return CLASSIFY_PROMPT_TEMPLATE.format(sessions="\n\n---\n\n".join(session_blocks))


def process_classification(conn: sqlite3.Connection, raw_input: str) -> dict[str, int]:
    """Parse Haiku's classification output and update the sessions table.

    Returns dict with keys: classified, skipped.
    """
    # Strip markdown code fences if present
    text = raw_input.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        items = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse classification output: %s", exc)
        return {"classified": 0, "skipped": 0}

    if not isinstance(items, list):
        logger.warning("Expected JSON array, got %s", type(items))
        return {"classified": 0, "skipped": 0}

    classified = 0
    skipped = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for item in items:
        session_id = item.get("session_id", "")
        existing = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        if not existing:
            logger.debug("Skipping unknown session_id: %s", session_id)
            skipped += 1
            continue

        conn.execute(
            """
            UPDATE sessions
            SET title = ?, summary = ?, status = ?, tags = ?, classified_at = ?
            WHERE id = ?
            """,
            (
                item.get("title", ""),
                item.get("summary", ""),
                item.get("status", "closed"),
                json.dumps(item.get("tags", [])),
                now,
                session_id,
            ),
        )
        classified += 1

    conn.commit()
    return {"classified": classified, "skipped": skipped}
