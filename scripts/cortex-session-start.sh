#!/usr/bin/env bash
# cortex-session-start.sh — Claude Code SessionStart hook
# SSHes to ThinkPad, runs `python3 -m cortex status`, parses the JSON,
# and prints a one-line summary. Exits 0 silently on any failure.

TMPFILE=$(mktemp)

# Run SSH in background, write stdout to tempfile.
# BatchMode=yes prevents interactive prompts; ConnectTimeout limits handshake.
ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=2 \
    -o StrictHostKeyChecking=no \
    thinkpad \
    "/home/dan/projects/cortex/.venv/bin/python3 -m cortex status --db /home/dan/.cortex/cortex.db 2>/dev/null" \
    > "$TMPFILE" 2>/dev/null &
SSH_PID=$!

# Wait up to 2 seconds for the SSH command to finish.
sleep 2
kill "$SSH_PID" 2>/dev/null
wait "$SSH_PID" 2>/dev/null

# Read whatever was written to the tempfile.
out=$(cat "$TMPFILE")
rm -f "$TMPFILE"

# Nothing from the server — bail silently.
[ -z "$out" ] && exit 0

# Parse the JSON and print the summary line.
python3 - "$out" <<'PYEOF' || exit 0
import json, sys, datetime

try:
    s = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)

if "error" in s:
    sys.exit(0)

count = s.get("curated_count", 0)
stale = s.get("stale_count", 0)

# Format last_memory_at as "X ago"
last_at = s.get("last_memory_at")
ago = "unknown"
if last_at:
    try:
        ts = datetime.datetime.fromisoformat(last_at.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - ts
        d = delta.days
        if d == 0:
            h = delta.seconds // 3600
            if h == 0:
                ago = f"{delta.seconds // 60}m ago"
            else:
                ago = f"{h}h ago"
        elif d == 1:
            ago = "1 day ago"
        else:
            ago = f"{d} days ago"
    except Exception:
        pass

# Show top memory types as "recent" context
by_type = s.get("by_type", {})
top_types = ", ".join(f"{k}:{v}" for k, v in list(by_type.items())[:3]) if by_type else ""

summary = f"Cortex: {count} active memories, last updated {ago}"
if stale:
    summary += f", {stale} stale"
if top_types:
    summary += f". Recent: [{top_types}]"

print(summary)
sys.exit(0)
PYEOF

exit 0
