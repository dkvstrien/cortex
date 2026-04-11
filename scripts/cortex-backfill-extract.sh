#!/bin/bash
# cortex-backfill-extract.sh — extract curated memories from ALL unextracted
# raw chunks, in batches. Use after a large backfill ingestion to work through
# the full backlog without blowing the LLM context window.
set -e

DB="${CORTEX_DB:-$HOME/.cortex/cortex.db}"
BATCH="${CORTEX_BATCH:-50}"
CORTEX_DIR="${CORTEX_DIR:-/home/dan/projects/cortex}"
CLAUDE_BIN="${CLAUDE_BIN:-/home/dan/.local/bin/claude}"
MODEL="${CORTEX_MODEL:-claude-haiku-4-5-20251001}"

cd "$CORTEX_DIR"

round=0
while : ; do
    round=$((round + 1))
    prompt=$(.venv/bin/python -m cortex extract --db "$DB" --scope all --limit "$BATCH" 2>/dev/null || true)
    if [ -z "$prompt" ]; then
        echo "backfill complete after $((round - 1)) rounds"
        break
    fi
    echo "round $round: sending batch of up to $BATCH chunks to $MODEL"
    echo "$prompt" \
        | "$CLAUDE_BIN" -p --model "$MODEL" --output-format text 2>/dev/null \
        | .venv/bin/python -m cortex extract --db "$DB" --process
done
