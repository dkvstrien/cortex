# Sprint 8 Changes

**Feature:** Status and health dashboard
**Commit:** see git log

## Files Changed
- `src/cortex/status.py` — created; status() function and _check_integrity() helper
- `tests/test_status.py` — created; 16 tests covering all acceptance criteria

## Dependencies Added
None

## Notes
- FTS5 content-sync mode makes COUNT(*) on the FTS table return the source table count. Used `curated_memories_fts_docsize` shadow table for actual indexed row count.
- The integrity dict includes an `ok` boolean and an `issues` list of human-readable strings.
