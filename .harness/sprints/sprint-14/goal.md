# Sprint 14 Goal

**Feature:** Graceful degradation and production hardening
**ID:** 14

## Acceptance Criteria
- If sqlite-vec is unavailable, curated layer still works and recall(layer='raw') returns a clear error message instead of crashing
- If fastembed is unavailable, recall falls back to FTS5-only search with a warning
- CORTEX_LOG_LEVEL=DEBUG enables verbose logging
- CLI python -m cortex dispatches to subcommands: server, ingest, extract, migrate, status
- MCP server returns structured error responses for invalid inputs (doesn't crash)
- Running python -m cortex --version prints the version

## Approach
Wrapped sqlite-vec and fastembed imports in try/except blocks with module-level availability flags (VEC_AVAILABLE, FASTEMBED_AVAILABLE). These flags are checked at operation boundaries (store_chunk, recall_raw) to raise clear RuntimeErrors. The unified recall function catches these errors: layer='raw' returns an error dict, layer='both' silently skips raw. Added structured try/except around all MCP server tool handlers. Created __main__.py as a CLI dispatcher using argparse subcommands. Added logging via the standard library with CORTEX_LOG_LEVEL env var configuration.
