# Sprint 12 Changes

**Feature:** MEMORY.md migration ingestion
**Commit:** (see git log)

## Files Changed
- `src/cortex/migrate.py` — Created. Core migration logic: parse MEMORY.md, map sections to types, read linked files, insert with idempotency.
- `tests/test_migrate.py` — Created. 19 tests covering parsing, type mapping, idempotency, linked file inclusion, both old and new MEMORY.md formats.
- `.harness/plan.json` — Feature 12 status set to in_progress.

## Dependencies Added
None.

## Notes
- Tested against Dan's actual MEMORY.md: 16 entries imported (7 entity, 6 fact, 2 preference, 1 procedure). Second run: 0 imported, 16 skipped.
- Supports both original (Project/User/Feedback/Reference) and newer (Dan/Active Projects/Tools & Environments/Areas/Reference) section header formats.
- CLI: `python -m cortex.migrate <path> --db <dbpath>`
