#!/bin/bash
set -e
cd /home/dan/projects/cortex

# Sync staging from Mac
rsync -a macbook:~/.cortex/staging/ ~/.cortex/staging/ 2>/dev/null || true

# Ingest new sessions
.venv/bin/python -m cortex ingest-sessions --db ~/.cortex/cortex.db --staging-dir ~/.cortex/staging/

# Ingest raw chunks
.venv/bin/python -m cortex ingest-staging --db ~/.cortex/cortex.db --staging-dir ~/.cortex/staging/

# Extract memories
.venv/bin/python -m cortex extract --db ~/.cortex/cortex.db 2>/dev/null \
  | /home/dan/.local/bin/claude -p --model claude-haiku-4-5-20251001 --output-format text 2>/dev/null \
  | .venv/bin/python -m cortex extract --db ~/.cortex/cortex.db --process

# Classify new sessions
.venv/bin/python -m cortex classify --db ~/.cortex/cortex.db 2>/dev/null \
  | /home/dan/.local/bin/claude -p --model claude-haiku-4-5-20251001 --output-format text 2>/dev/null \
  | .venv/bin/python -m cortex classify --db ~/.cortex/cortex.db --process

# Reflect: synthesize insights from new memories
.venv/bin/python -m cortex reflect --db ~/.cortex/cortex.db 2>/dev/null \
  | /home/dan/.local/bin/claude -p --model claude-haiku-4-5-20251001 --output-format text 2>/dev/null \
  | .venv/bin/python -m cortex reflect --db ~/.cortex/cortex.db --process

# Decay: apply confidence decay to all curated memories
.venv/bin/python -m cortex decay --db ~/.cortex/cortex.db
