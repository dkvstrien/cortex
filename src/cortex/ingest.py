"""Ingestion pipeline: text chunking and bulk content loading into raw layer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from cortex.raw import store_chunk


def chunk_text(
    text: str,
    max_tokens: int = 300,
    overlap: int = 50,
) -> list[str]:
    """Split text into overlapping chunks based on approximate token count.

    Uses simple word-based splitting where 1 token ~ 0.75 words.

    Parameters
    ----------
    text:
        The text to split.
    max_tokens:
        Maximum tokens per chunk (default 300).
    overlap:
        Number of overlap tokens between consecutive chunks (default 50).

    Returns
    -------
    List of text chunks.
    """
    words = text.split()
    if not words:
        return []

    # Convert token counts to word counts: tokens * 0.75 = words
    max_words = int(max_tokens * 0.75)
    overlap_words = int(overlap * 0.75)
    step = max(1, max_words - overlap_words)

    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i : i + max_words]
        chunks.append(" ".join(chunk_words))
        i += step
        # Don't create a tiny trailing chunk
        if i < len(words) and len(words) - i < overlap_words:
            # Extend the last chunk to include remaining words
            chunks[-1] = " ".join(words[i - step :])
            break

    return chunks


def _content_hash(content: str) -> str:
    """Return a hex SHA-256 hash of the content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chunk_exists(conn: sqlite3.Connection, source: str, content_hash: str) -> bool:
    """Check if a chunk with the same source and content hash already exists."""
    row = conn.execute(
        "SELECT 1 FROM raw_chunks WHERE source = ? AND json_extract(metadata, '$.content_hash') = ?",
        (source, content_hash),
    ).fetchone()
    return row is not None


def _parse_session_log(text: str) -> list[str]:
    """Parse a JSONL session log and extract assistant text messages.

    Skips tool_use content blocks and messages under 50 chars.
    """
    texts = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("type") != "assistant":
            continue

        # Extract text from content blocks
        content = obj.get("content", [])
        if isinstance(content, str):
            if len(content) >= 50:
                texts.append(content)
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                continue
            if block.get("type") == "text":
                text_val = block.get("text", "")
                if len(text_val) >= 50:
                    texts.append(text_val)

    return texts


def ingest_file(
    conn: sqlite3.Connection,
    path: str | Path,
    source_type: str,
    max_tokens: int = 300,
    overlap: int = 50,
) -> dict[str, int]:
    """Read a file, chunk it, embed, and store in raw_chunks.

    For source_type='session': parses JSONL and extracts assistant text,
    skipping tool_use blocks and messages under 50 chars.

    Parameters
    ----------
    conn:
        Open SQLite connection with Cortex schema.
    path:
        Path to the file to ingest.
    source_type:
        One of: book, podcast, session, article.
    max_tokens:
        Maximum tokens per chunk.
    overlap:
        Overlap tokens between chunks.

    Returns
    -------
    Dict with keys: ingested, skipped.
    """
    path = Path(path)
    source = str(path)
    raw_text = path.read_text(encoding="utf-8")

    if source_type == "session":
        text_segments = _parse_session_log(raw_text)
    else:
        text_segments = [raw_text]

    ingested = 0
    skipped = 0

    for segment in text_segments:
        chunks = chunk_text(segment, max_tokens=max_tokens, overlap=overlap)
        for chunk in chunks:
            h = _content_hash(chunk)
            if _chunk_exists(conn, source, h):
                skipped += 1
                continue
            metadata = {"content_hash": h}
            store_chunk(conn, chunk, source, source_type, metadata=metadata)
            ingested += 1

    return {"ingested": ingested, "skipped": skipped}


def main() -> None:
    """CLI entry point for ingestion."""
    import argparse

    from cortex.db import init_db

    parser = argparse.ArgumentParser(
        description="Ingest a file into Cortex raw chunks layer.",
    )
    parser.add_argument("path", help="Path to the file to ingest")
    parser.add_argument(
        "--source-type",
        required=True,
        choices=["book", "podcast", "session", "article"],
        help="Type of source content",
    )
    parser.add_argument(
        "--db",
        default="cortex.db",
        help="Path to the Cortex database (default: cortex.db)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=300,
        help="Maximum tokens per chunk (default: 300)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=50,
        help="Overlap tokens between chunks (default: 50)",
    )
    args = parser.parse_args()

    conn = init_db(args.db)
    result = ingest_file(
        conn, args.path, args.source_type,
        max_tokens=args.max_tokens, overlap=args.overlap,
    )
    print(f"{result['ingested']} chunks ingested, {result['skipped']} skipped")
    conn.close()


if __name__ == "__main__":
    main()
