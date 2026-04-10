# Cortex Roadmap

Current version: v0.2.0 (Phase 2 complete — 26 features, 338 tests)

---

## Phase 3 — Make it actually intelligent

### P1 — System prompt injection
**The biggest gap.** Instead of hoping Claude calls `recall`, inject high-confidence
memories directly into every session's system prompt.

Two approaches (implement both, fallback to dumb if smart fails):
- **Dumb inject**: always inject top 20 by confidence at session start
- **Smart inject**: inject memories relevant to the current working directory/project
  via a fast embedding lookup at session start

Implementation: SessionStart hook generates a temp context file that gets prepended
to the session. No tool call required — Claude just *knows*.

Acceptance criteria:
- SessionStart hook writes a `~/.cortex/session-context.md` with top memories
- Claude Code reads it automatically (via hook output or CLAUDE.md include)
- Works without Claude calling any tool
- Falls back silently if Cortex is unreachable

---

### P2 — Web UI
Simple read-only memory browser at `memory.dkvs8001.org` (Tailscale only).

- FastAPI backend, plain HTML frontend (no framework)
- List memories by type, search, filter by confidence/staleness
- Mark memories as stale or delete them without opening a terminal
- Read-only by default; write actions require confirmation

---

### P3 — Quality filter on capture
The Stop hook captures everything including one-word replies, tool outputs, and
boilerplate. Fix this before staging, not after.

A fast local filter in `cortex-capture.sh`:
- Skip if < 100 chars
- Skip if content looks like a tool result (starts with `{`, code fence, etc.)
- Skip if near-duplicate of previous line in same staging file
- Tag skipped lines with reason in a separate `.skip` log for debugging

Benefit: fewer junk chunks = better Haiku extractions = cleaner memory DB.

---

### P4 — Correction and failure capture
Cortex currently learns facts but not mistakes. Fix this by watching for correction
patterns in session content.

- Tag chunks containing "actually", "that didn't work", "we still had to", "my
  mistake", "I was wrong" as `correction` type in staging
- Extraction prompt gives correction-tagged chunks higher weight
- Haiku produces `procedure` memories from corrections: "When doing X, watch out
  for Y" rather than just facts
- Cortex learns from its own failures, not just its successes

---

### P5 — Deduplication pass
Over time the DB accumulates near-duplicate memories from repeated extraction runs.

- `python -m cortex dedup` runs cosine similarity across all curated memories
- Flags pairs above threshold (e.g. 0.92) as duplicates
- In dry-run mode: prints duplicates for review
- In `--auto` mode: merges pairs by keeping higher-confidence memory and
  soft-deleting the other
- Add to Sunday cron after reflect

---

## Phase 4 — Polish

- **Robust staging sync** — handle rsync failures gracefully, retry logic,
  checksum verification
- **Memory analytics** — `cortex analytics`: memories created per week, topic
  distribution, decay curves, extraction hit rate
- **Export to MEMORY.md** — `cortex export-md` generates a human-readable
  MEMORY.md from the DB (eventually replaces the file-based memory system)
- **Telegram slash commands** — `/remember <text>`, `/forget <id>`, `/recall
  <query>` as native bot commands, not just via Claude
- **Multi-machine support** — currently single-user/single-DB; architecture
  notes for anyone wanting to run it on a different setup

---

## Known gaps vs Hindsight

| Feature | Hindsight | Cortex |
|---|---|---|
| Automatic capture | Yes (retain() after every response) | Yes (Stop hook) |
| System prompt injection | Yes (always) | No — Claude must call recall |
| Contradiction detection | Yes | Yes (extraction pipeline) |
| Insight synthesis | Yes (observation consolidation) | Yes (reflect pipeline) |
| Supersede via tool | Yes | Yes |
| Multi-user | Yes | No (by design) |
| Web UI | No | Planned (Phase 3) |
| Quality filter | Unknown | Planned (Phase 3) |
| Failure/correction capture | Unknown | Planned (Phase 3) |

The only meaningful gap right now is **system prompt injection (P1)**.
Everything else is polish.
