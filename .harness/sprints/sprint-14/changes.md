# Sprint 14 Changes

**Feature:** Graceful degradation and production hardening
**Commit:** pending

## Files Changed
- `src/cortex/db.py` — Wrapped sqlite-vec import in try/except, added VEC_AVAILABLE flag, skip vec table creation when unavailable, added logging
- `src/cortex/embeddings.py` — Wrapped fastembed import in try/except, added FASTEMBED_AVAILABLE flag, embed_one/embed_batch raise RuntimeError when unavailable, added logging
- `src/cortex/raw.py` — Check VEC_AVAILABLE and FASTEMBED_AVAILABLE before store_chunk and recall_raw, raise clear RuntimeError when missing
- `src/cortex/recall.py` — Catch RuntimeError from raw layer: layer='raw' returns error dict, layer='both' silently skips raw, added logging
- `src/cortex/server.py` — Wrapped all 4 tool handlers in try/except returning structured error dicts, added logging
- `src/cortex/curated.py` — Added logging import
- `src/cortex/__init__.py` — Added __version__ = "0.1.0"
- `src/cortex/__main__.py` — Created CLI dispatcher with argparse subcommands: server, ingest, extract, migrate, status. Configures logging from CORTEX_LOG_LEVEL env var.
- `tests/test_degradation.py` — Created 15 tests covering: vec unavailable, fastembed unavailable, logging config, CLI version/help/status/no-args, MCP server error handling

## Dependencies Added
None

## Notes
- Availability flags are module-level booleans set at import time, checked at operation boundaries
- The CLI dispatcher delegates to existing module main() functions for consistency
- All 221 tests pass (206 existing + 15 new)
