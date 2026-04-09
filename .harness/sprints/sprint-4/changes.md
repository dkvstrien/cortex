# Sprint 4 Changes

**Feature:** Raw layer: chunk storage and vector search

## Files Changed
- `src/cortex/raw.py` — Created. Contains `store_chunk()` and `recall_raw()` functions.
- `src/cortex/db.py` — Updated `init_db()` to load sqlite-vec extension and create `raw_chunks_vec` virtual table.
- `src/cortex/embeddings.py` — Added `serialize_vec()` for raw float32 serialization (no dimension prefix, as required by sqlite-vec).
- `pyproject.toml` — Added `sqlite-vec>=0.1.0` to dependencies.
- `.harness/plan.json` — Set feature 4 status to `in_progress`.
- `tests/test_raw.py` — Created. 10 tests covering all acceptance criteria.

## Dependencies Added
- `sqlite-vec>=0.1.0` — SQLite extension for vector similarity search (KNN via vec0 virtual tables).

## Notes
- sqlite-vec requires `k = ?` constraint in WHERE clause for KNN queries (not `LIMIT ?`). This is different from standard SQL patterns.
- sqlite-vec expects raw little-endian float32 bytes without a dimension prefix, so `serialize_vec()` was added alongside the existing `serialize()` which includes a 4-byte dimension header.
- For source_type filtering, we fetch 4x the limit from the vec index to account for post-join filtering.
