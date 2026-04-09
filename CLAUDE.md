# Cortex — Instructions for Claude

Cortex is your long-term memory system. It runs as an MCP server with 5 tools.
Use them proactively — don't wait to be asked.

## When to use each tool

**remember** — Call this whenever something important comes up in conversation:
- A decision Dan makes ("I'm switching from X to Y")
- A preference Dan states ("I like short responses", "always use metric units")
- A fact worth keeping ("The farm has 42 cows", "Sebastian handles robot maintenance")
- A procedure Dan wants to follow consistently

**recall** — Call this *before* answering questions about Dan's history, preferences,
or past decisions. Don't guess — check Cortex first. Examples:
- "What did we decide about X?" → recall("X decision")
- "How does Dan prefer Y?" → recall("Dan preference Y")
- "What's the status of project Z?" → recall("project Z")

**supersede** — Use this when information *changes*, not forget + remember.
This preserves the history of what changed and when.
- Dan switches tools, locations, preferences, or project plans
- A fact you stored earlier turns out to be outdated
- Never create a duplicate — supersede the old one instead

**forget** — Use only to remove genuinely wrong or irrelevant memories.
For updates, use supersede instead.

**status** — Call this periodically (e.g. at the start of a long session) to
see how many memories are stored and whether any are going stale.

## Practical rules

- Store memories in the background — don't interrupt the conversation to announce it.
- Prefer specific, standalone facts over vague summaries ("Dan uses uv for Python
  projects on Mac" rather than "Dan has a Mac").
- Tag memories with relevant keywords so recall finds them later.
- When in doubt, remember it. Disk is cheap, forgotten context is expensive.
