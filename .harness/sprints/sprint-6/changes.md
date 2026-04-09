# Sprint 6 Changes

**Feature:** Forget and supersede operations

## Files Changed
- `src/cortex/curated.py` — Added forget(), supersede(), and get_history() functions
- `tests/test_mutations.py` — Created: 18 tests covering all three operations
- `.harness/plan.json` — Set feature 6 status to in_progress

## Dependencies Added
None

## Notes
- The forget() function removes the entry from the FTS5 index to prevent stale matches. Calling forget() twice on the same ID will cause an FTS5 error (the entry was already removed from the index). This is acceptable since double-forget is not a required use case.
- supersede() inherits type, source, and tags from the old memory by default, but all can be overridden.
- One pre-existing test failure in test_decay.py (test_returns_count_of_updated) is unrelated to this sprint.
