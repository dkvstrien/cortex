# Sprint 10 Goal

**Feature:** Text chunking and raw layer ingestion pipeline
**ID:** 10

## Acceptance Criteria
- chunk_text splits a 1000-word text into ~3 chunks of ~300 tokens each with overlap
- ingest_file stores all chunks with embeddings in raw_chunks
- Session log ingestion skips tool call messages and messages under 50 chars
- CLI accepts a file path and source_type flag
- Ingestion is idempotent — re-running on same file doesn't create duplicates
- A summary is printed: N chunks ingested, M skipped

## Approach
Created `src/cortex/ingest.py` with three main components: `chunk_text()` for word-based overlapping text splitting (1 token ~ 0.75 words), `ingest_file()` for reading/chunking/storing with session log JSONL parsing support, and a CLI entry point via `python -m cortex.ingest`. Idempotency is achieved by storing a SHA-256 content hash in each chunk's metadata JSON and checking for duplicates before insertion.
