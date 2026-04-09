"""CLI dispatcher for Cortex.

Usage:
    python -m cortex server [--transport stdio|sse] [--port 8765]
    python -m cortex ingest <path> --source-type <type> [--db <path>]
    python -m cortex ingest-staging [--db <path>] [--staging-dir <dir>]
    python -m cortex extract [--scope recent|all] [--process] [--db <path>]
    python -m cortex reflect [--process] [--db <path>]
    python -m cortex migrate <path> [--db <path>]
    python -m cortex status [--db <path>]
    python -m cortex --version
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from cortex import __version__


def _configure_logging() -> None:
    """Configure logging based on CORTEX_LOG_LEVEL env var."""
    level_name = os.environ.get("CORTEX_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("cortex").setLevel(level)


def main() -> None:
    _configure_logging()

    parser = argparse.ArgumentParser(
        prog="cortex",
        description="Cortex — personal memory system CLI",
    )
    parser.add_argument(
        "--version", action="version", version=f"cortex {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # server
    sp_server = subparsers.add_parser("server", help="Start the MCP server")
    sp_server.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="Transport protocol (default: stdio)",
    )
    sp_server.add_argument(
        "--host", default="127.0.0.1",
        help="Host to bind SSE server (default: 127.0.0.1)",
    )
    sp_server.add_argument(
        "--port", type=int, default=8765,
        help="Port for SSE transport (default: 8765)",
    )

    # ingest
    sp_ingest = subparsers.add_parser("ingest", help="Ingest a file into raw chunks")
    sp_ingest.add_argument("path", help="Path to the file to ingest")
    sp_ingest.add_argument(
        "--source-type", required=True,
        choices=["book", "podcast", "session", "article"],
        help="Type of source content",
    )
    sp_ingest.add_argument("--db", default=None, help="Path to Cortex database")
    sp_ingest.add_argument("--max-tokens", type=int, default=300)
    sp_ingest.add_argument("--overlap", type=int, default=50)

    # ingest-staging
    _default_staging_dir = str(Path.home() / ".cortex" / "staging")
    sp_ingest_staging = subparsers.add_parser(
        "ingest-staging", help="Ingest JSONL staging files into raw chunks"
    )
    sp_ingest_staging.add_argument("--db", default=None, help="Path to Cortex database")
    sp_ingest_staging.add_argument(
        "--staging-dir", default=_default_staging_dir,
        help=f"Directory containing .jsonl staging files (default: {_default_staging_dir})",
    )
    sp_ingest_staging.add_argument("--max-tokens", type=int, default=300)
    sp_ingest_staging.add_argument("--overlap", type=int, default=50)

    # extract
    sp_extract = subparsers.add_parser("extract", help="Extract curated memories from raw chunks")
    sp_extract.add_argument(
        "--scope", default="recent", choices=["recent", "all"],
        help="Scope of chunks to extract",
    )
    sp_extract.add_argument(
        "--process", action="store_true",
        help="Read extraction JSON from stdin and process it",
    )
    sp_extract.add_argument("--db", default=None, help="Path to Cortex database")

    # reflect
    sp_reflect = subparsers.add_parser(
        "reflect", help="Synthesize insights from curated memories"
    )
    sp_reflect.add_argument(
        "--process", action="store_true",
        help="Read reflection JSON from stdin and process it into insight memories",
    )
    sp_reflect.add_argument("--db", default=None, help="Path to Cortex database")

    # migrate
    sp_migrate = subparsers.add_parser("migrate", help="Import MEMORY.md into curated layer")
    sp_migrate.add_argument("path", help="Path to MEMORY.md file")
    sp_migrate.add_argument("--db", default=None, help="Path to Cortex database")

    # status
    sp_status = subparsers.add_parser("status", help="Show health dashboard")
    sp_status.add_argument("--db", default=None, help="Path to Cortex database")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "server":
        _cmd_server(args)
    elif args.command == "ingest":
        _cmd_ingest(args)
    elif args.command == "ingest-staging":
        _cmd_ingest_staging(args)
    elif args.command == "extract":
        _cmd_extract(args)
    elif args.command == "reflect":
        _cmd_reflect(args)
    elif args.command == "migrate":
        _cmd_migrate(args)
    elif args.command == "status":
        _cmd_status(args)


def _resolve_db(args_db: str | None) -> str:
    """Resolve the database path from CLI arg, env var, or default."""
    if args_db:
        return args_db
    return os.environ.get("CORTEX_DB_PATH", "cortex.db")


def _cmd_server(args: argparse.Namespace) -> None:
    from cortex.server import create_server, main as server_main

    # Delegate to the existing server main which handles its own arg parsing
    # but we already parsed, so call directly
    if args.transport == "sse":
        server = create_server(port=args.port, host=args.host)
        server.run(transport="sse")
    else:
        from cortex.server import mcp

        mcp.run(transport="stdio")


def _cmd_ingest(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.ingest import ingest_file

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    result = ingest_file(
        conn, args.path, args.source_type,
        max_tokens=args.max_tokens, overlap=args.overlap,
    )
    print(f"{result['ingested']} chunks ingested, {result['skipped']} skipped")
    conn.close()


def _cmd_ingest_staging(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.ingest_staging import ingest_staging

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    result = ingest_staging(
        conn, args.staging_dir,
        max_tokens=args.max_tokens,
        overlap=args.overlap,
    )
    conn.close()
    print(
        f"{result['lines_processed']} lines processed, "
        f"{result['chunks_stored']} chunks stored, "
        f"{result['files_completed']} files completed, "
        f"{result['files_skipped']} files skipped"
    )


def _cmd_extract(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.extract import extract_prompt, process_extraction

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)

    if args.process:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            print("No input received on stdin", file=sys.stderr)
            sys.exit(1)
        result = process_extraction(conn, raw_input)
        print(
            f"{result['memories_created']} memories created, "
            f"{result['extractions_linked']} extractions linked"
        )
    else:
        prompt = extract_prompt(conn, scope=args.scope)
        if prompt is None:
            print("No unextracted chunks found.", file=sys.stderr)
            sys.exit(0)
        print(prompt)

    conn.close()


def _cmd_reflect(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.reflect import reflect_prompt, process_reflection

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)

    if args.process:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            print("No input received on stdin", file=sys.stderr)
            sys.exit(1)
        result = process_reflection(conn, raw_input)
        print(
            f"{result['insights_created']} insights created, "
            f"{result['source_ids_tracked']} source IDs tracked"
        )
    else:
        prompt = reflect_prompt(conn)
        if prompt is None:
            print("No unreflected memories found.", file=sys.stderr)
            sys.exit(0)
        print(prompt)

    conn.close()


def _cmd_migrate(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.migrate import migrate_memory_md

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    result = migrate_memory_md(conn, args.path)
    conn.close()
    print(f"{result['imported']} memories imported, {result['skipped']} skipped (duplicates)")


def _cmd_status(args: argparse.Namespace) -> None:
    import json

    from cortex.db import init_db
    from cortex.status import status as get_status

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    result = get_status(conn, db_path)
    conn.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
