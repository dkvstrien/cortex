# Sprint 9 Goal

**Feature:** MCP server with 4 core tools
**ID:** 9

## Acceptance Criteria
- Running python -m cortex.server starts an MCP server on stdio transport
- Running python -m cortex.server --transport sse --port 8765 starts SSE server
- The server exposes exactly 4 tools: remember, recall, forget, status
- remember tool accepts content, type, tags, layer parameters
- recall tool accepts query, type, limit, layer parameters
- forget tool accepts id and returns confirmation
- status tool returns the full health dashboard
- CORTEX_DB_PATH environment variable controls database location

## Approach
Created `src/cortex/server.py` using FastMCP SDK. The server registers 4 tools that delegate to existing cortex modules (curated, raw, recall, status). Each tool manages its own DB connection via `init_db`. The `main()` entry point uses argparse for `--transport` and `--port` flags, with stdio as the default transport. For SSE, a new FastMCP instance is created with the specified port since FastMCP takes port in the constructor, not in `run()`.
