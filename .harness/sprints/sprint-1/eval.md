# Sprint 1 Evaluation

**Feature:** Project scaffolding and SQLite schema
**Verdict:** PASS

## Criteria Results

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Running `pip install -e .` from project root succeeds | PASS | `pip install -e ".[dev]"` completed successfully with system Python 3.9 |
| 2 | Importing `from cortex.db import init_db` works and creates a .db file with all tables/virtual tables | PASS | `python3 -c "from cortex.db import init_db; init_db('/tmp/test_cortex_eval.db')"` succeeded, DB file created with curated_memories, curated_memories_fts, raw_chunks, extractions, meta tables |
| 3 | curated_memories table has correct columns and CHECK constraint | PASS | Schema verified via `sqlite3 .schema` -- all 10 columns present (id, content, type, source, tags, confidence, created_at, updated_at, supersedes_id, deleted_at). CHECK constraint rejects invalid type with error 19. |
| 4 | curated_memories_fts virtual table exists and indexes content + tags | PASS | Virtual table confirmed in schema: `USING fts5(content, tags, content=curated_memories, content_rowid=id)`. FTS sync triggers for INSERT/UPDATE/DELETE all present. Test `test_fts_sync` confirms search works. |
| 5 | raw_chunks table has correct columns | PASS | 7 columns verified: id, content, embedding, source, source_type, metadata, created_at |
| 6 | meta table exists with key-value structure | PASS | Schema shows `meta (key TEXT PRIMARY KEY, value TEXT)`. Test inserts and retrieves key-value pair successfully. |
| 7 | WAL mode is enabled on the database | PASS | `PRAGMA journal_mode` returns `wal` |
| 8 | pytest runs with 0 errors | PASS | 13 tests passed in 0.08s, 0 failures, 0 errors |

## Testing Done
- `pip install -e ".[dev]"` -- successful installation
- `python3 -c "from cortex.db import init_db; init_db('/tmp/test_cortex_eval.db')"` -- DB created
- `sqlite3 /tmp/test_cortex_eval.db ".schema"` -- all tables and triggers verified
- `sqlite3 /tmp/test_cortex_eval.db "PRAGMA journal_mode"` -- returns "wal"
- `sqlite3 /tmp/test_cortex_eval.db "INSERT INTO curated_memories (content, type) VALUES ('bad', 'invalid');"` -- correctly rejected with CHECK constraint error
- `python3 -m pytest tests/ -v` -- 13/13 passed

## Issues Found
- The project installs under system Python 3.9 (`/Library/Developer/CommandLineTools/usr/bin/python3`) but not under homebrew Python due to PEP 668 restrictions. This is a local environment issue, not a code issue -- using a venv would resolve it.
- The acceptance criteria mention "6 tables/virtual tables" but there are 5 user-defined tables (curated_memories, curated_memories_fts, raw_chunks, extractions, meta). The extractions table was not in the original criteria list but is a reasonable addition. All specifically named tables exist.
