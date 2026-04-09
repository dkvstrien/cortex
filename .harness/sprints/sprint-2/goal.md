# Sprint 2 Goal

**Feature:** Curated layer: remember and FTS5 search
**ID:** 2

## Acceptance Criteria
- remember('Dan prefers SQLite over Postgres', type='preference', source='manual') returns an integer ID
- recall_curated('database preference') returns the stored memory with a rank score
- recall_curated with type filter only returns memories of that type
- recall_curated with limit=1 returns exactly 1 result
- Soft-deleted memories (deleted_at set) do not appear in recall results
- FTS5 search handles partial word matches via prefix queries
- Results are returned as dicts with keys: id, content, type, source, tags, confidence, rank, created_at

## Approach
Created `src/cortex/curated.py` with `remember()` and `recall_curated()` functions. `remember()` inserts into `curated_memories` with JSON-serialized tags and returns the row ID. `recall_curated()` builds a prefix-expanded FTS5 query (term -> term*), joins FTS results with the main table filtering out soft-deleted and superseded memories, and returns BM25-ranked results as dicts. Added `type` to the FTS5 index so type-based searches work naturally.
