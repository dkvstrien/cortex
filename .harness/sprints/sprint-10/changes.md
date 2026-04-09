# Sprint 10 Changes

**Feature:** Text chunking and raw layer ingestion pipeline
**Commit:** see git log

## Files Changed
- `src/cortex/ingest.py` — created; chunk_text, ingest_file, session log parser, CLI entry point
- `tests/test_ingest.py` — created; 12 tests covering chunking, session parsing, idempotency, embeddings
- `.harness/plan.json` — feature 10 status set to in_progress

## Dependencies Added
- None

## Notes
- Idempotency uses SHA-256 content hash stored in metadata JSON (no schema migration needed)
- Session log parsing handles JSONL format, extracts assistant text blocks, skips tool_use and short messages
- 2 pre-existing test failures in test_decay.py and test_mutations.py are from sprint 6 (in_progress), not related to this sprint
