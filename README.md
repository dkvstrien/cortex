# Cortex

Claude forgets everything between sessions. Cortex fixes that.

Every response Claude gives is captured automatically. A nightly pipeline extracts the facts, decisions, and preferences into a searchable memory database. Next session, those memories load at startup — Claude already knows your preferences, your current projects, and what you decided last week.

No cloud sync. No accounts. Runs on your own machines.

---

## What Cortex does NOT do

- No cloud storage — everything stays on your hardware
- No multi-user support — one person, one memory database
- No GUI — command line and Claude tools only
- No automatic LLM calls — extraction runs on demand (you pipe it through Haiku/Claude when ready)
- No internet-connected service — the MCP server is local to your network (Tailscale)

---

## How it compares

| Scenario | Without Cortex | With Cortex |
|---|---|---|
| You mention your preferred code style in session 1 | Claude asks again in session 2 | Claude already knows. No re-explaining. |
| You decide to switch from Postgres to SQLite | Next session Claude suggests Postgres again | Decision is stored. Claude recommends SQLite. |
| You ask "what did we decide about X?" | Claude guesses or says it doesn't know | Claude calls `recall("X decision")` and finds the answer |
| You've been working on a project for 3 months | Claude has no project context until you paste it in | Claude loads recent project facts at session start automatically |

---

## Architecture

```
  Mac (Claude Code)
  ┌─────────────────────────────────────────────┐
  │                                             │
  │  Claude responds to you                     │
  │       │                                     │
  │  Stop hook fires (cortex-capture.sh)        │
  │       │                                     │
  │  Appends response to                        │
  │  ~/.cortex/staging/YYYY-MM-DD.jsonl         │
  │                                             │
  └─────────────────────────────────────────────┘
           │
           │  nightly rsync (cron on ThinkPad)
           ▼
  ThinkPad (home server)
  ┌─────────────────────────────────────────────┐
  │                                             │
  │  ingest-staging                             │
  │  Chunks each response → embeds → raw_chunks │
  │       │                                     │
  │  extract  (piped through Haiku)             │
  │  Promotes key facts → curated_memories      │
  │       │                                     │
  │  reflect  (optional, piped through Haiku)   │
  │  Synthesizes patterns → insight memories    │
  │                                             │
  │  SQLite DB: cortex.db                       │
  │  ├── curated_memories  (FTS5 indexed)       │
  │  └── raw_chunks        (vector indexed)     │
  │                                             │
  │  MCP server (SSE, port 8765)                │
  │  Exposes 5 tools to Claude Code             │
  │                                             │
  └─────────────────────────────────────────────┘
           │
           │  Tailscale network
           ▼
  Mac (Claude Code, session start)
  ┌─────────────────────────────────────────────┐
  │                                             │
  │  SessionStart hook fires                    │
  │  Fetches memory summary from MCP server     │
  │  Prints "Cortex: 47 memories, last ..."     │
  │                                             │
  │  During session, Claude calls:              │
  │  remember / recall / forget / supersede     │
  │                                             │
  └─────────────────────────────────────────────┘
```

---

## 5-minute setup

You need: a Mac running Claude Code, and a home server (Linux box, Raspberry Pi, NAS) reachable over your local network or Tailscale.

**Step 1 — Install Cortex on both machines**

On your Mac:
```
pip install git+https://github.com/yourname/cortex.git
```

On your ThinkPad/server:
```
pip install git+https://github.com/yourname/cortex.git
```

**Step 2 — Run the installer on your Mac**

```
python -m cortex install
```

This does everything automatically:
- Creates `~/.cortex/` and the database
- Copies hook scripts to `~/scripts/`
- Adds the Stop hook so Claude's responses get captured
- Adds the SessionStart hook so memories load at startup
- Adds the Cortex MCP server to `~/.claude/.mcp.json`

Output looks like:
```
Cortex installer
========================================
  [done] Create /Users/you/.cortex — created
  [done] Initialize DB at /Users/you/.cortex/cortex.db — initialized
  [done] Copy cortex-capture.sh to /Users/you/scripts — installed
  [done] Copy cortex-session-start.sh to /Users/you/scripts — installed
  [done] Add Stop hook (cortex-capture.sh) to settings.json — added
  [done] Add SessionStart hook (cortex-session-start.sh) to settings.json — added
  [done] Add cortex MCP entry to .mcp.json — added
========================================
Done. Run `python -m cortex status` to verify.
```

**Step 3 — Start the MCP server on your ThinkPad**

```
CORTEX_DB_PATH=/home/dan/.cortex/cortex.db \
  python -m cortex server --transport sse --host 0.0.0.0 --port 8765
```

To keep it running, add it to a systemd service or run it in a tmux session. The installer's MCP entry already points to `http://100.108.198.107:8765/sse` — edit `~/.claude/.mcp.json` if your server's IP is different.

**Step 4 — Set up the nightly cron on your ThinkPad**

```
crontab -e
```

Add:
```
# Sync staging files from Mac and ingest them
0 2 * * * rsync -a dan@mac:.cortex/staging/ /home/dan/.cortex/staging/ && \
  CORTEX_DB_PATH=/home/dan/.cortex/cortex.db \
  python -m cortex ingest-staging
```

**Step 5 — Verify it works**

Start a new Claude Code session. You should see a line like:

```
Cortex: 0 active memories, last updated never.
```

Have a conversation. After it ends, check that a staging file was created:
```
ls ~/.cortex/staging/
```

You should see a file named `YYYY-MM-DD.jsonl` with today's date.

**That's it.** After the first nightly sync + ingest, run `extract` to promote raw chunks to curated memories (see below). From that point, Cortex runs automatically in the background.

---

## Migration: importing your existing MEMORY.md

If you already have a `MEMORY.md` file you've been maintaining manually, import it in one command:

```
python -m cortex migrate ~/.claude/projects/your-project/memory/MEMORY.md \
  --db /home/dan/.cortex/cortex.db
```

Output:
```
42 memories imported, 0 skipped (duplicates)
```

Run it again safely — it skips duplicates.

---

## The extraction pipeline

Raw chunks are just text blobs. The extract pipeline uses an LLM (Haiku is fast and cheap) to pull out the facts worth remembering.

**Step 1 — Generate the extraction prompt**
```
python -m cortex extract --db /home/dan/.cortex/cortex.db > /tmp/extract-prompt.txt
```

**Step 2 — Run it through Claude/Haiku**

Paste the contents of `/tmp/extract-prompt.txt` into Claude and ask it to follow the instructions. Or use the API directly.

**Step 3 — Feed the JSON output back**
```
cat /tmp/extract-output.json | \
  python -m cortex extract --process --db /home/dan/.cortex/cortex.db
```

Output:
```
12 memories created, 12 extractions linked
```

The extraction pipeline is smart: it includes your existing curated memories in the prompt so it can spot contradictions. If a new chunk says you switched from Postgres to SQLite, it will supersede the old "uses Postgres" memory automatically.

---

## The reflect pipeline

After you've built up a few hundred memories, reflect synthesizes higher-level insights: patterns across decisions, long-term preferences, recurring themes.

```
# Generate the reflection prompt
python -m cortex reflect --db /home/dan/.cortex/cortex.db > /tmp/reflect-prompt.txt

# Run through Claude, then process the output
cat /tmp/reflect-output.json | \
  python -m cortex reflect --process --db /home/dan/.cortex/cortex.db
```

Reflection memories have `type=insight`. They show up in recall like any other memory.

---

## MCP tools

When Claude Code is connected to the Cortex MCP server, it has 5 tools available. The `CLAUDE.md` in this repo instructs Claude to use them proactively — but you can also call them directly in conversation.

### remember

Store a fact, decision, or preference.

```
remember(
  content="I'm switching from vim to neovim as my primary editor",
  type="decision",
  tags=["editor", "tools"]
)
# Returns: {"id": 47, "layer": "curated", "status": "stored"}
```

Types: `fact`, `decision`, `preference`, `procedure`, `entity`, `idea`

### recall

Search memories by keyword.

```
recall(query="editor preference")
# Returns: {"results": [{"id": 47, "content": "I'm switching from vim...", "rank": -1.2, ...}], "count": 1}

recall(query="Python projects", type="procedure", limit=5)
# Filtered by type, max 5 results

recall(query="database", layer="both")
# Searches curated memories (FTS5) AND raw chunks (vector similarity)
```

### forget

Soft-delete a memory. The row is kept but excluded from search.

```
forget(id=12)
# Returns: {"id": 12, "status": "forgotten"}
```

Use `forget` for memories that are just wrong. For updates (the fact changed), use `supersede` instead — it preserves history.

### supersede

Replace one memory with another, keeping a chain of what changed.

```
supersede(
  old_id=47,
  new_content="Switched back to vim after neovim config issues",
  type="decision"
)
# Returns: {"old_id": 47, "new_id": 89, "status": "superseded"}
```

The old memory (47) is soft-deleted. The new one (89) links back to it via `supersedes_id`. The full chain is visible in `show`.

### status

Health check for the whole system.

```
status()
# Returns:
{
  "curated_count": 84,
  "raw_count": 1203,
  "by_type": {"fact": 41, "decision": 18, "preference": 15, "procedure": 7, "insight": 3},
  "by_source": {"extract": 72, "memory_md_migration": 12},
  "last_memory_at": "2026-04-08T22:41:00",
  "last_consolidation_at": "2026-04-08T23:00:00",
  "db_size_mb": 24.3,
  "stale_count": 2,
  "fts_ok": true,
  "vec_ok": true
}
```

`stale_count` is memories with confidence below 0.1 — they haven't been accessed or reinforced in a long time and may be outdated.

---

## CLI reference

All subcommands accept `--db <path>` to specify the database. Default is `cortex.db` in the current directory, or `CORTEX_DB_PATH` env var.

### server

Start the MCP server.

```
# stdio (for direct Claude Code integration, no network)
python -m cortex server

# SSE (for remote access over network/Tailscale)
python -m cortex server --transport sse --host 0.0.0.0 --port 8765
```

### ingest

Chunk a file and store it in the raw layer with vector embeddings.

```
python -m cortex ingest /path/to/notes.txt --source-type article --db cortex.db
# 47 chunks ingested, 0 skipped

python -m cortex ingest session.log --source-type session
# Short messages and tool calls are skipped automatically
```

Source types: `book`, `podcast`, `session`, `article`

### ingest-staging

Process the JSONL staging files captured by the Stop hook.

```
python -m cortex ingest-staging --db /home/dan/.cortex/cortex.db

# Custom staging directory:
python -m cortex ingest-staging \
  --staging-dir /home/dan/.cortex/staging \
  --db /home/dan/.cortex/cortex.db
```

Output:
```
312 lines processed, 891 chunks stored, 14 files completed, 0 files skipped
```

Already-ingested files are tracked in the database. Re-running is safe.

### extract

Generate an LLM prompt to extract curated memories from raw chunks, or process the LLM's JSON output.

```
# Step 1: generate prompt (pipe to LLM)
python -m cortex extract --db cortex.db

# Step 2: process LLM output
echo '{"memories": [...]}' | python -m cortex extract --process --db cortex.db

# Extract all chunks, not just recent ones
python -m cortex extract --scope all --db cortex.db
```

### reflect

Synthesize insight memories from existing curated memories.

```
# Generate reflection prompt
python -m cortex reflect --db cortex.db

# Process LLM output into insight memories
cat reflect-output.json | python -m cortex reflect --process --db cortex.db
```

### migrate

Import an existing `MEMORY.md` file into the curated layer.

```
python -m cortex migrate /path/to/MEMORY.md --db cortex.db
# 42 memories imported, 0 skipped (duplicates)
```

### status

Print the health dashboard as JSON.

```
python -m cortex status --db cortex.db
```

### list

Browse recent memories in a table.

```
# Most recent 20
python -m cortex list --db cortex.db

# Filter by type, limit results
python -m cortex list --type decision --limit 10 --db cortex.db
```

Output:
```
 ID  Type        Conf  Content
---  ----------  ----  -----------------------------------------------
 89  decision    1.00  Switched back to vim after neovim config issues
 84  preference  0.92  Prefer short responses with no summaries at end
 81  fact        0.87  Farm has 42 dairy cows as of March 2026
...
```

### search

Full-text search of curated memories with relevance scores.

```
python -m cortex search "editor preferences" --db cortex.db
python -m cortex search "farm" --limit 5 --db cortex.db
```

### show

Full details for a single memory, including supersession history.

```
python -m cortex show 89 --db cortex.db
```

Output:
```
Memory #89
  Type:       decision
  Source:     extract
  Confidence: 1.00
  Created:    2026-04-08 22:41
  Tags:       editor, tools
  Content:    Switched back to vim after neovim config issues

Supersedes: #47
  [47] I'm switching from vim to neovim as my primary editor
       (soft-deleted 2026-04-08 22:41)
```

### export

Dump all non-deleted curated memories to stdout as JSON.

```
python -m cortex export --db cortex.db > backup.json
python -m cortex export --db /home/dan/.cortex/cortex.db > memories-$(date +%Y%m%d).json
```

### import

Import a JSON array of memories (from `export`) into the database.

```
python -m cortex import --db cortex.db < backup.json
# 84 imported, 0 skipped

# Move memories between machines:
python -m cortex export --db old.db | python -m cortex import --db new.db
```

Idempotent — re-importing the same file skips duplicates.

### install

One-command setup. See the 5-minute setup guide above.

```
python -m cortex install
```

### doctor

Diagnostics — checks every component and reports pass/fail with remediation hints.

```
python -m cortex doctor

# Also check the remote MCP server:
python -m cortex doctor --remote thinkpad
```

Output:
```
Cortex doctor
========================================
  [PASS] DB file exists and opens
  [PASS] FTS5 index intact
  [WARN] sqlite-vec not available — vector search disabled
  [PASS] fastembed available
  [PASS] staging directory writable
  [PASS] MCP server reachable on port 8765
========================================
1 warning. Run `python -m cortex status` for details.
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CORTEX_DB_PATH` | `cortex.db` (cwd) | Path to the SQLite database |
| `CORTEX_LOG_LEVEL` | `WARNING` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Project layout

```
cortex/
├── src/cortex/
│   ├── __main__.py      # CLI dispatcher
│   ├── server.py        # MCP server (5 tools)
│   ├── db.py            # Schema, init_db
│   ├── curated.py       # remember, forget, supersede, get_history
│   ├── raw.py           # store_chunk, recall_raw
│   ├── recall.py        # Unified recall with layer fallback
│   ├── embeddings.py    # fastembed wrapper (bge-small-en-v1.5)
│   ├── extract.py       # Raw → curated extraction pipeline
│   ├── reflect.py       # Insight synthesis pipeline
│   ├── ingest.py        # File ingestion
│   ├── ingest_staging.py # JSONL staging ingestion
│   ├── migrate.py       # MEMORY.md importer
│   ├── browse.py        # list, search, show commands
│   ├── port.py          # export, import
│   ├── decay.py         # Confidence decay math
│   ├── status.py        # Health dashboard
│   └── install.py       # One-command installer
├── scripts/
│   ├── cortex-capture.sh        # Stop hook — appends to staging JSONL
│   └── cortex-session-start.sh  # SessionStart hook — prints memory summary
└── tests/               # 174+ tests
```

---

## Dependencies

- **mcp** — MCP server protocol (FastMCP)
- **fastembed** — Local embeddings, no GPU needed (bge-small-en-v1.5, 384d)
- **sqlite-vec** — Vector similarity search inside SQLite

Python 3.9+. No cloud APIs required for storage or search. Only the extraction and reflection pipelines require an LLM API call — and those are manual, not automatic.
