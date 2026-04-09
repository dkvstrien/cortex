# Sprint 1 Goal

**Feature:** Project scaffolding and SQLite schema
**ID:** 1

## Acceptance Criteria
- Running `pip install -e .` from project root succeeds
- Importing `from cortex.db import init_db` works and creates a .db file with all tables
- curated_memories table has correct columns and CHECK constraint
- curated_memories_fts virtual table exists and indexes content + tags
- raw_chunks table has correct columns
- meta table exists with key-value structure
- WAL mode is enabled on the database
- pytest runs with 0 errors

## Approach
Created a src-layout Python project with pyproject.toml. Implemented db.py with a single `init_db(path)` function that runs an SQL script to create all tables (curated_memories, raw_chunks, extractions, meta), FTS5 virtual table with content-sync triggers, and enables WAL mode. sqlite-vec virtual table deferred to Sprint 4.
