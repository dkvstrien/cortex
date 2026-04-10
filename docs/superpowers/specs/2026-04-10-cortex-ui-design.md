# Cortex UI — Design Spec
**Date:** 2026-04-10
**Status:** Approved

## Overview

A web UI extension of Cortex that surfaces session history and extracted memories as a navigable, scannable timeline. Solves two problems:

1. **Finding things** — "what did we talk about that one time?" with no good answer today
2. **Open loops** — conversations that ended mid-thought, visible and actionable

Lives in the Cortex repo as `web/` + `api/`. Deployed on ThinkPad, accessible via Tailscale (phone included). Same stack as Leseraum: FastAPI backend, SvelteKit frontend.

Graph view (Obsidian-style) is explicitly deferred to v2 — not enough data yet to make connections interesting.

---

## Data Model

### New table: `sessions`

Added to `cortex.db` alongside existing tables.

```sql
CREATE TABLE sessions (
    id            TEXT PRIMARY KEY,  -- session_id from staging JSONL
    date          TEXT NOT NULL,     -- YYYY-MM-DD from staging filename
    title         TEXT,              -- Haiku: "Lely robot alarm debugging"
    summary       TEXT,              -- Haiku: 1-2 sentence description
    status        TEXT NOT NULL DEFAULT 'unprocessed'
                      CHECK(status IN ('open', 'closed', 'unprocessed')),
    tags          TEXT DEFAULT '[]', -- JSON array: ["farm","lely","hardware"]
    chunk_count   INTEGER DEFAULT 0, -- number of raw_chunks in this session
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    classified_at TEXT               -- NULL until Haiku has processed it
);
```

### Fix: `curated_memories.source`

Going forward, the extract pipeline sets `source` = session_id (e.g. `f0ba4edd-39ee-4c87-...`). Historical memories (currently showing "claude-code", "extraction") get a one-time migration setting `source = NULL` — the provenance link cannot be recovered for those.

The `raw_chunks` source format (`staging:2026-04-09.jsonl:SESSION_ID`) already encodes the session_id and is already correct.

---

## Pipeline Changes

Two new steps added to the existing nightly cron (`22:00`). Existing steps are unchanged except for the source fix.

```
22:00 nightly cron:
  1. rsync staging Mac → ThinkPad                    [existing]
  2. ✦ parse staging → upsert sessions table         [NEW]
       - new sessions: status='unprocessed', chunk_count filled
  3. extract | Haiku → curated_memories              [existing + source fix]
  4. ✦ classify unprocessed sessions | Haiku         [NEW]
       - writes: title, summary, status, tags, classified_at

23:00 Sunday:
  5. reflect | Haiku → insight memories              [existing, unchanged]
```

### Haiku classifier prompt (sketch)

```
Given these conversation turns, return JSON only:
{
  "title": "3-6 word descriptive title",
  "summary": "1-2 sentence summary of what was discussed",
  "status": "open or closed",
  "tags": ["tag1", "tag2"]
}

"open" means: a question went unanswered, a task was left unfinished,
or the conversation ended mid-thought without resolution.
"closed" means: the topic reached a natural conclusion.
```

Estimated cost: ~$0.01–0.02 per session.

### Back-fill

One-time script run before first deploy. Processes all existing staging files through steps 2–4. No pipeline changes needed — just point the new scripts at historical JSONL files.

---

## HTTP API

New standalone FastAPI service (`cortex/api/`). The existing Cortex server is the MCP stdio transport and is not the right host for REST routes — this runs as a separate process on its own port.

```
GET  /api/sessions
     ?status=open|closed|all  (default: all)
     ?page=1&limit=20
     → [{ id, date, title, summary, status, tags, chunk_count, memory_count }]

GET  /api/sessions/:id
     → session detail
       + last 10 raw_chunks (transcript preview)
       + linked curated_memories (where source = session_id)

GET  /api/sessions/:id/transcript
     → all raw_chunks for session, ordered by created_at

POST /api/sessions/:id/vikunja
     → creates Vikunja task: title = session title, description = link back
     ← { task_id, task_url }

GET  /api/memories
     ?type=decision|preference|fact|entity|idea|procedure
     ?tag=farm
     → [{ id, content, type, tags, source }]
```

Vikunja push uses existing API token from `~/.secrets/`. "Copy resumption prompt" is assembled client-side from session data — no API call.

---

## Web UI

SvelteKit app. New systemd service on ThinkPad, new subdomain (`cortex.dkvs8001.org`).

### Timeline view

- Sessions sorted by date descending
- Filter bar: All / Open (N) / Closed — plus search box
- Open sessions: red glow indicator, red accent
- Closed sessions: green dot, neutral style

### Session card (collapsed)

```
● [title]                                    [tag] [tag]  ▶
  [date] · [N] exchanges · [N] memories extracted
```

### Session card (expanded — open session)

> **Transcript limitation:** staging JSONL captures Claude's responses only — user messages are not stored. The transcript preview and full transcript show Claude's side of the conversation only.

```
● [title]                                    [tag] [tag]  ▼ open
  [date] · [N] responses · [N] memories · no conclusion reached

  Last responses (Claude)
  ┌─────────────────────────────────────────────┐
  │ [third-to-last claude response]             │
  │ [second-to-last claude response]            │
  │ [last claude response]                      │
  └─────────────────────────────────────────────┘

  Memories extracted
  [entity] Sebastian handles Lely robot maintenance
  [fact]   Lely A5 alarm fires when parked — suspected config issue

  [📋 Push to Vikunja]  [▶ Copy resumption prompt]  [👁 Full transcript]
```

### Actions

- **Push to Vikunja** — POST `/api/sessions/:id/vikunja`, creates task with back-link
- **Copy resumption prompt** — client-side, writes to clipboard:
  > *"We were working on [title] on [date]. Here's where we left off: [last 3 exchanges]. Pick up from here."*
- **Full transcript** — expands all raw_chunks inline

---

## Deployment

- Backend: `cortex/api/` — standalone FastAPI service, port 5092
- Frontend: `cortex/web/` — SvelteKit, port 5093, new systemd services for both
- Domain: `cortex.dkvs8001.org` (Tailscale only)

---

## Out of Scope (v1)

- **Graph view** — deferred. Build once 50+ sessions exist and connections are meaningful.
- **Manual session labeling** — Haiku does it automatically; no UI for editing titles/tags in v1
- **Cross-session search** — future; full-text search across transcripts
- **Daimon integration** — Telegram bot could eventually surface open loops; deferred
