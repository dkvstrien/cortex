"""CLI dispatcher for Cortex.

Usage:
    python -m cortex server [--transport stdio|sse] [--port 8765]
    python -m cortex ingest <path> --source-type <type> [--db <path>]
    python -m cortex ingest-staging [--db <path>] [--staging-dir <dir>]
    python -m cortex extract [--scope recent|all] [--process] [--db <path>]
    python -m cortex reflect [--process] [--db <path>]
    python -m cortex decay [--half-life DAYS] [--db <path>]
    python -m cortex migrate <path> [--db <path>]
    python -m cortex status [--db <path>]
    python -m cortex list [--type TYPE] [--limit N] [--db <path>]
    python -m cortex search <query> [--db <path>]
    python -m cortex show <id> [--db <path>]
    python -m cortex export [--db <path>]
    python -m cortex import [--db <path>] < memories.json
    python -m cortex install
    python -m cortex doctor [--db PATH] [--remote <ssh-host>]
    python -m cortex --version
"""

from __future__ import annotations

import argparse
import json
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
        "--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
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

    # ingest-sessions
    _default_staging_dir_sessions = str(Path.home() / ".cortex" / "staging")
    sp_ingest_sessions = subparsers.add_parser(
        "ingest-sessions", help="Parse staging JSONL files into the sessions table"
    )
    sp_ingest_sessions.add_argument("--db", default=None, help="Path to Cortex database")
    sp_ingest_sessions.add_argument(
        "--staging-dir", default=_default_staging_dir_sessions,
        help=f"Directory containing .jsonl staging files (default: {_default_staging_dir_sessions})",
    )

    # classify
    sp_classify = subparsers.add_parser(
        "classify", help="Classify unprocessed sessions with Haiku (generate title/status/tags)"
    )
    sp_classify.add_argument("--db", default=None, help="Path to Cortex database")
    sp_classify.add_argument(
        "--process", action="store_true",
        help="Read classification JSON from stdin and update sessions",
    )

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
    sp_extract.add_argument(
        "--limit", type=int, default=None,
        help="Max number of chunks to include in one extraction batch",
    )
    sp_extract.add_argument(
        "--mark-tried", action="store_true",
        help="Mark selected chunks as tried so empty batches don't recycle",
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

    # decay
    sp_decay = subparsers.add_parser(
        "decay", help="Apply confidence decay to all curated memories"
    )
    sp_decay.add_argument(
        "--half-life", type=float, default=90.0,
        help="Half-life in days for exponential decay (default: 90)",
    )
    sp_decay.add_argument("--db", default=None, help="Path to Cortex database")

    # migrate
    sp_migrate = subparsers.add_parser("migrate", help="Import MEMORY.md into curated layer")
    sp_migrate.add_argument("path", help="Path to MEMORY.md file")
    sp_migrate.add_argument("--db", default=None, help="Path to Cortex database")

    # status
    sp_status = subparsers.add_parser("status", help="Show health dashboard")
    sp_status.add_argument("--db", default=None, help="Path to Cortex database")

    # list
    sp_list = subparsers.add_parser("list", help="List recent curated memories as a table")
    sp_list.add_argument("--type", default=None, help="Filter by memory type")
    sp_list.add_argument("--limit", type=int, default=20, help="Maximum number of results (default: 20)")
    sp_list.add_argument("--db", default=None, help="Path to Cortex database")

    # search
    sp_search = subparsers.add_parser("search", help="FTS5 search of curated memories")
    sp_search.add_argument("query", help="Search query")
    sp_search.add_argument("--limit", type=int, default=20, help="Maximum number of results (default: 20)")
    sp_search.add_argument("--db", default=None, help="Path to Cortex database")

    # show
    sp_show = subparsers.add_parser("show", help="Show full details for a single memory")
    sp_show.add_argument("id", type=int, help="Memory ID")
    sp_show.add_argument("--db", default=None, help="Path to Cortex database")

    # export
    sp_export = subparsers.add_parser(
        "export", help="Dump all non-deleted curated memories as JSON to stdout"
    )
    sp_export.add_argument("--db", default=None, help="Path to Cortex database")

    # import (Python keyword — subcommand name is "import", function is _cmd_import)
    sp_import = subparsers.add_parser(
        "import", help="Import memories from JSON (stdin) into the curated layer"
    )
    sp_import.add_argument("--db", default=None, help="Path to Cortex database")

    # install
    subparsers.add_parser("install", help="Set up Cortex for a new user (idempotent)")

    # doctor
    sp_doctor = subparsers.add_parser("doctor", help="Run health checks and diagnostics")
    sp_doctor.add_argument("--db", default=None, help="Path to Cortex database")
    sp_doctor.add_argument(
        "--remote", default=None, metavar="SSH_HOST",
        help="SSH host to check for remote MCP server reachability",
    )

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
    elif args.command == "ingest-sessions":
        _cmd_ingest_sessions(args)
    elif args.command == "classify":
        _cmd_classify(args)
    elif args.command == "extract":
        _cmd_extract(args)
    elif args.command == "reflect":
        _cmd_reflect(args)
    elif args.command == "decay":
        _cmd_decay(args)
    elif args.command == "migrate":
        _cmd_migrate(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "list":
        _cmd_list(args)
    elif args.command == "search":
        _cmd_search(args)
    elif args.command == "show":
        _cmd_show(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "import":
        _cmd_import(args)
    elif args.command == "install":
        _cmd_install(args)
    elif args.command == "doctor":
        _cmd_doctor(args)


def _resolve_db(args_db: str | None) -> str:
    """Resolve the database path from CLI arg, env var, or default."""
    if args_db:
        return args_db
    return os.environ.get("CORTEX_DB_PATH", os.path.expanduser("~/.cortex/cortex.db"))


def _cmd_server(args: argparse.Namespace) -> None:
    from cortex.server import create_server, main as server_main

    # Delegate to the existing server main which handles its own arg parsing
    # but we already parsed, so call directly
    if args.transport in ("sse", "streamable-http"):
        server = create_server(port=args.port, host=args.host)
        server.run(transport=args.transport)
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


def _cmd_ingest_sessions(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.sessions import ingest_sessions

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    result = ingest_sessions(conn, args.staging_dir)
    conn.close()
    print(
        f"{result['sessions_created']} sessions created, "
        f"{result['sessions_updated']} updated, "
        f"{result['files_processed']} files processed"
    )


def _cmd_classify(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.classify import classify_prompt, process_classification

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)

    if args.process:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            print("No input received on stdin", file=sys.stderr)
            sys.exit(1)
        result = process_classification(conn, raw_input)
        print(f"{result['classified']} sessions classified, {result['skipped']} skipped")
    else:
        prompt = classify_prompt(conn)
        if prompt is None:
            print("No unprocessed sessions found.", file=sys.stderr)
            sys.exit(0)
        print(prompt)

    conn.close()


def _cmd_extract(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.extract import extract_prompt, process_extraction

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)

    if args.process:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            # Empty LLM response — treat as "no memories" so the backfill
            # loop can continue. Chunks were already marked tried upstream
            # if --mark-tried was used, so they won't recycle.
            print("0 memories created, 0 extractions linked (empty input)")
            conn.close()
            return
        try:
            result = process_extraction(conn, raw_input)
        except (json.JSONDecodeError, ValueError) as exc:
            print(
                f"0 memories created, 0 extractions linked (bad LLM output: {exc})",
                file=sys.stderr,
            )
            conn.close()
            return
        print(
            f"{result['memories_created']} memories created, "
            f"{result['extractions_linked']} extractions linked"
        )
    else:
        prompt = extract_prompt(
            conn,
            scope=args.scope,
            limit=args.limit,
            mark_tried=args.mark_tried,
        )
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


def _cmd_decay(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.decay import decay_confidence

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    updated = decay_confidence(conn, half_life_days=args.half_life)
    conn.close()
    print(f"{updated} memories updated")


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


def _cmd_list(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.browse import list_memories, print_list

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    memories = list_memories(conn, type=args.type, limit=args.limit)
    conn.close()
    print_list(memories)


def _cmd_search(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.browse import search_memories, print_search

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    results = search_memories(conn, args.query, limit=args.limit)
    conn.close()
    print_search(results, args.query)


def _cmd_show(args: argparse.Namespace) -> None:
    from cortex.db import init_db
    from cortex.browse import print_show

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    found = print_show(conn, args.id)
    conn.close()
    if not found:
        sys.exit(1)


def _cmd_export(args: argparse.Namespace) -> None:
    import json

    from cortex.db import init_db
    from cortex.port import export_memories

    db_path = _resolve_db(args.db)
    conn = init_db(db_path)
    memories = export_memories(conn)
    conn.close()
    print(json.dumps(memories, indent=2))


def _cmd_import(args: argparse.Namespace) -> None:
    import json

    from cortex.db import init_db
    from cortex.port import import_memories

    db_path = _resolve_db(args.db)
    raw = sys.stdin.read().strip()
    if not raw:
        print("No input received on stdin", file=sys.stderr)
        sys.exit(1)

    try:
        memories = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(memories, list):
        print("Expected a JSON array", file=sys.stderr)
        sys.exit(1)

    conn = init_db(db_path)
    result = import_memories(conn, memories)
    conn.close()
    print(f"{result['imported']} imported, {result['skipped']} skipped")


def _cmd_install(args: argparse.Namespace) -> None:
    from cortex.install import main as install_main

    install_main()


def _cmd_doctor(args: argparse.Namespace) -> None:
    from pathlib import Path

    from cortex.doctor import run_doctor

    db_path = Path(args.db) if args.db else None
    exit_code = run_doctor(db_path=db_path, remote=args.remote)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
