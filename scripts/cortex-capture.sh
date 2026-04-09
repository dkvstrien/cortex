#!/usr/bin/env bash
# cortex-capture.sh — Claude Code Stop hook
# Reads Stop hook JSON from stdin, extracts last assistant response,
# appends to ~/.cortex/staging/YYYY-MM-DD.jsonl
#
# Stop hook payload: {"session_id": "...", "transcript_path": "...", "stop_hook_active": true}
# Each output line: {"timestamp": "...", "session_id": "...", "content": "..."}

set -euo pipefail

STAGING_DIR="$HOME/.cortex/staging"
MIN_LEN=50

# Read the Stop hook payload from stdin
PAYLOAD=$(cat)

# Extract session_id and transcript_path
SESSION_ID=$(echo "$PAYLOAD" | jq -r '.session_id // ""')
TRANSCRIPT_PATH=$(echo "$PAYLOAD" | jq -r '.transcript_path // ""')

# Bail if we don't have what we need
if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi

# Extract last assistant message text from the transcript
# Transcript is JSONL; find last line with type=assistant and text content
CONTENT=$(python3 - "$TRANSCRIPT_PATH" <<'PYEOF'
import sys, json

path = sys.argv[1]
text_out = ""

with open(path, "r") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            parts = [
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            ]
            text = "".join(parts).strip()
            if text:
                text_out = text
        elif isinstance(content, str) and content.strip():
            text_out = content.strip()

print(text_out)
PYEOF
)

# Skip if content is empty or too short
if [[ -z "$CONTENT" || "${#CONTENT}" -lt $MIN_LEN ]]; then
    exit 0
fi

# Ensure staging directory exists
mkdir -p "$STAGING_DIR"

# Build output filename with today's date
DATE=$(date +%Y-%m-%d)
OUTPUT_FILE="$STAGING_DIR/$DATE.jsonl"

# Build ISO 8601 timestamp
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Write JSONL line — use python3 to safely encode JSON
python3 -c "
import json, sys
line = json.dumps({
    'timestamp': sys.argv[1],
    'session_id': sys.argv[2],
    'content': sys.argv[3],
})
print(line)
" "$TIMESTAMP" "$SESSION_ID" "$CONTENT" >> "$OUTPUT_FILE"

exit 0
