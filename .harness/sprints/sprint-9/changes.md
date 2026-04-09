# Sprint 9 Changes

**Feature:** MCP server with 4 core tools
**Commit:** pending

## Files Changed
- `src/cortex/server.py` — Created. MCP server with 4 tools (remember, recall, forget, status), argparse CLI for transport/port, CORTEX_DB_PATH env var support.
- `tests/test_server.py` — Created. 10 tests covering tool registration, all 4 tool operations, error handling, env var configuration, and SSE server creation.

## Dependencies Added
- `mcp` (1.27.0) — FastMCP SDK for building MCP servers

## Notes
- `status.py` already existed from a parallel sprint (feature 8), so no placeholder was needed.
- FastMCP's `run()` method does not accept a `port` parameter; port must be set in the constructor. The SSE path creates a new FastMCP instance with the specified port.
- The `mcp` dependency should be added to pyproject.toml dependencies for production use.
