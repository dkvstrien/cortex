# Sprint 2 Changes

**Feature:** Curated layer: remember and FTS5 search
**Commit:** TBD

## Files Changed
- `src/cortex/curated.py` — Created. Contains `remember()` and `recall_curated()` functions.
- `src/cortex/db.py` — Added `type` column to FTS5 virtual table and updated sync triggers to include type.
- `tests/test_curated.py` — Created. 17 tests covering all acceptance criteria.
- `.harness/plan.json` — Set feature 2 to in_progress.

## Dependencies Added
None.

## Notes
- Added `type` to the FTS5 index (was only content + tags). This allows searching by memory type (e.g. "preference") which the acceptance criteria requires.
- Superseded memories are excluded by checking if any other memory has `supersedes_id` pointing to them (subquery), not by checking the supersedes_id column on the memory itself.
- BM25 scores are negative in SQLite FTS5 (lower = better match), so ORDER BY rank gives best matches first.
