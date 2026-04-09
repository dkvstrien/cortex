"""MCP server exposing Cortex memory tools via FastMCP.

Usage:
    python -m cortex.server                          # stdio transport (default)
    python -m cortex.server --transport sse --port 8765  # SSE transport

The CORTEX_DB_PATH environment variable controls the database location.
Defaults to ~/.cortex/cortex.db if not set.
"""

from __future__ import annotations

import argparse
import logging
import os

from mcp.server.fastmcp import FastMCP

from cortex.db import init_db

logger = logging.getLogger("cortex")

# Resolve DB path from env
_db_path = os.environ.get("CORTEX_DB_PATH", os.path.expanduser("~/.cortex/cortex.db"))

# Create the FastMCP server
mcp = FastMCP("cortex")


def _get_conn():
    """Get a database connection, initializing if needed."""
    return init_db(_db_path)


@mcp.tool()
def remember(
    content: str,
    type: str = "fact",
    tags: list[str] | None = None,
    layer: str = "curated",
) -> dict:
    """Store a memory in Cortex.

    Parameters:
        content: The memory text to store.
        type: Memory type (fact, decision, preference, procedure, entity, idea).
        tags: Optional list of tag strings.
        layer: Which layer to store in ('curated' or 'raw').
    """
    try:
        conn = _get_conn()
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        return {"error": f"Database connection failed: {e}"}
    try:
        if layer == "curated":
            from cortex.curated import remember as curated_remember

            memory_id = curated_remember(conn, content, type=type, tags=tags)
            return {"id": memory_id, "layer": "curated", "status": "stored"}
        elif layer == "raw":
            from cortex.raw import store_chunk

            chunk_id = store_chunk(
                conn, content, source="mcp", source_type="session"
            )
            return {"id": chunk_id, "layer": "raw", "status": "stored"}
        else:
            return {"error": f"Invalid layer: {layer!r}. Must be 'curated' or 'raw'."}
    except Exception as e:
        logger.error("remember failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def recall(
    query: str,
    type: str | None = None,
    limit: int = 10,
    layer: str = "curated",
) -> dict:
    """Search memories in Cortex.

    Parameters:
        query: Free-text search query.
        type: Filter by memory type (curated) or source_type (raw).
        limit: Maximum number of results.
        layer: Which layer to search ('curated', 'raw', or 'both').
    """
    try:
        conn = _get_conn()
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        return {"error": f"Database connection failed: {e}"}
    try:
        from cortex.recall import recall as unified_recall

        results = unified_recall(conn, query, type=type, limit=limit, layer=layer)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error("recall failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def forget(id: int) -> dict:
    """Soft-delete a curated memory by ID.

    Parameters:
        id: The integer ID of the memory to forget.
    """
    try:
        conn = _get_conn()
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        return {"error": f"Database connection failed: {e}"}
    try:
        from cortex.curated import forget as curated_forget

        curated_forget(conn, id)
        return {"id": id, "status": "forgotten"}
    except KeyError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("forget failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def supersede(old_id: int, new_content: str, type: str | None = None) -> dict:
    """Replace an existing curated memory with updated content.

    Soft-deletes the old memory and creates a new one that links back to it
    via supersedes_id. Use this instead of forget + remember to preserve
    the change history.

    Parameters:
        old_id: The integer ID of the memory to replace.
        new_content: The updated memory text.
        type: Memory type override (defaults to same type as old memory).
    """
    try:
        conn = _get_conn()
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        return {"error": f"Database connection failed: {e}"}
    try:
        from cortex.curated import supersede as curated_supersede

        new_id = curated_supersede(conn, old_id, new_content, type=type)
        return {"old_id": old_id, "new_id": new_id, "status": "superseded"}
    except KeyError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("supersede failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


@mcp.tool()
def status() -> dict:
    """Return the Cortex health dashboard.

    Shows counts, breakdowns by type/source, staleness, and integrity checks.
    """
    try:
        conn = _get_conn()
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        return {"error": f"Database connection failed: {e}"}
    try:
        from cortex.status import status as get_status

        return get_status(conn, _db_path)
    except Exception as e:
        logger.error("status failed: %s", e)
        return {"error": str(e)}
    finally:
        conn.close()


def create_server(port: int = 8000, host: str = "127.0.0.1") -> FastMCP:
    """Create a new FastMCP server instance with the given host/port.

    Re-registers all tools on the new instance. Useful when port
    needs to differ from the default module-level server.
    """
    server = FastMCP("cortex", host=host, port=port)

    # Re-register tools on the new server
    server.tool()(remember)
    server.tool()(recall)
    server.tool()(forget)
    server.tool()(supersede)
    server.tool()(status)
    return server


def main():
    """Entry point for python -m cortex.server."""
    parser = argparse.ArgumentParser(description="Cortex MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind SSE server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        server = create_server(port=args.port, host=args.host)
        server.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
