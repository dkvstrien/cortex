# Sprint 25 Changes

**Feature:** README and install guide
**Commit:** pending

## Files Changed
- `README.md` — created, 572 lines, comprehensive project documentation

## Dependencies Added
None.

## Notes

The README covers everything in the acceptance criteria:
- 5-minute setup guide (5 numbered steps with exact commands and expected output)
- ASCII architecture diagram: Mac Stop hook → staging JSONL → rsync → ThinkPad → ingest-staging → raw_chunks → extract → curated_memories → MCP server → Claude Code
- Comparison table with 4 scenarios (Without Cortex vs With Cortex)
- All 5 MCP tools with example calls and return values
- All CLI subcommands: server, ingest, ingest-staging, extract, reflect, migrate, status, list, search, show, export, import, install, doctor

The `doctor` subcommand is included in the CLI reference (feature 26, not yet implemented) — its section documents the expected interface so the README is complete when that feature lands.
