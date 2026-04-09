# Sprint 8 Goal

**Feature:** Status and health dashboard
**ID:** 8

## Acceptance Criteria
- status() returns a dict with keys: curated_count, raw_count, by_type, by_source, last_memory_at, last_consolidation_at, db_size_mb, stale_count
- by_type maps memory types to counts
- by_source maps source types to counts
- stale_count is the number of curated memories with confidence < 0.1
- Integrity check reports if FTS5 count differs from curated_memories count
- Integrity check reports if vec index count differs from raw_chunks count

## Approach
Created `src/cortex/status.py` with a `status(conn, db_path)` function that queries all relevant tables and returns a comprehensive health dashboard dict. Used the FTS5 docsize shadow table for accurate indexed row counts (since content-sync FTS5 COUNT(*) reads from the source table). Integrity checks compare actual indexed counts against source table counts for both FTS5 and sqlite-vec.
