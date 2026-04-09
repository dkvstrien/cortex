# Sprint 4 Goal

**Feature:** Raw layer: chunk storage and vector search
**ID:** 4

## Acceptance Criteria
- store_chunk stores content with embedding and returns an ID
- recall_raw('database preference') finds semantically similar chunks
- recall_raw with source_type filter only returns matching source types
- recall_raw respects the limit parameter
- Semantic search works: store 'I love pizza', search 'favorite food' returns it
- sqlite-vec extension loads on the current platform without errors

## Approach
Created `src/cortex/raw.py` with `store_chunk()` and `recall_raw()` functions. `store_chunk` embeds content via fastembed, stores in `raw_chunks` with the serialized embedding BLOB, and indexes in the `raw_chunks_vec` sqlite-vec virtual table. `recall_raw` embeds the query, performs KNN search via sqlite-vec using the `k = ?` constraint syntax, joins with `raw_chunks` for full content, and supports optional `source_type` filtering. Updated `init_db()` to load the sqlite-vec extension and create the vec0 virtual table. Added `serialize_vec()` helper for raw float32 bytes (no dimension prefix) as required by sqlite-vec.
