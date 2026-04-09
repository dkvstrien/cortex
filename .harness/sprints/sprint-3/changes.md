# Sprint 3 Changes

**Feature:** Embedding engine with fastembed
**Commit:** d4afaf8

## Files Changed
- `src/cortex/embeddings.py` — Created. Embedding module with lazy-loaded fastembed model, embed_one, embed_batch, serialize, deserialize.
- `tests/test_embeddings.py` — Created. 11 tests covering lazy init, embed_one, embed_batch, serialize/deserialize round-trips.
- `pyproject.toml` — Added fastembed>=0.3.0 to dependencies.
- `.harness/plan.json` — Set feature 3 status to in_progress.

## Dependencies Added
- fastembed>=0.3.0 — lightweight embedding library using onnxruntime (no PyTorch)

## Notes
- First embed call downloads ~50MB model to cache. Subsequent calls are fast.
- Serialize format: little-endian uint32 dimension count + float32 array. Simple and efficient for SQLite BLOB storage.
- All 41 tests pass (30 existing + 11 new).
