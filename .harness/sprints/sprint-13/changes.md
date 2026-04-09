# Sprint 13 Changes

**Feature:** End-to-end test suite
**Commit:** (see git log)

## Files Changed
- `tests/test_e2e.py` — Created. 21 end-to-end tests across 8 classes.
- `.harness/plan.json` — Feature 13 status set to in_progress.

## Dependencies Added
None.

## Notes
- Total test count is now 206 (185 existing + 21 new), all passing.
- FTS5 ranking test uses 32 memories spanning SQLite-relevant, database-adjacent, and completely unrelated content.
- Vector search ranking test uses 22 chunks across 5 topical clusters (food, programming, nature, music, tech).
- Decay math tests verify confidence at exactly 1 and 2 half-lives (0.5 and 0.25 respectively), plus 300-day stale threshold.
