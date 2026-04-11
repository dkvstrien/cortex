"""SQLite schema and database initialization for Cortex."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("cortex")

# Try to import sqlite-vec; set availability flag
try:
    import sqlite_vec

    VEC_AVAILABLE = True
except ImportError:
    VEC_AVAILABLE = False
    logger.warning("sqlite-vec not available — raw layer (vector search) will be disabled")

SCHEMA_SQL = """
-- Enable WAL mode for concurrent reads
PRAGMA journal_mode=WAL;

-- Curated memories: distilled knowledge extracted from raw sources
CREATE TABLE IF NOT EXISTS curated_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('decision', 'preference', 'procedure', 'entity', 'fact', 'idea', 'insight')),
    source TEXT,
    tags TEXT DEFAULT '[]',  -- JSON array
    confidence REAL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    supersedes_id INTEGER REFERENCES curated_memories(id),
    deleted_at TEXT
);

-- FTS5 index on curated_memories content and tags (content-sync mode)
CREATE VIRTUAL TABLE IF NOT EXISTS curated_memories_fts USING fts5(
    content,
    type,
    tags,
    content=curated_memories,
    content_rowid=id
);

-- Triggers to keep FTS in sync with curated_memories
CREATE TRIGGER IF NOT EXISTS curated_memories_ai AFTER INSERT ON curated_memories BEGIN
    INSERT INTO curated_memories_fts(rowid, content, type, tags)
    VALUES (new.id, new.content, new.type, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS curated_memories_ad AFTER DELETE ON curated_memories BEGIN
    INSERT INTO curated_memories_fts(curated_memories_fts, rowid, content, type, tags)
    VALUES ('delete', old.id, old.content, old.type, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS curated_memories_au AFTER UPDATE ON curated_memories BEGIN
    INSERT INTO curated_memories_fts(curated_memories_fts, rowid, content, type, tags)
    VALUES ('delete', old.id, old.content, old.type, old.tags);
    INSERT INTO curated_memories_fts(rowid, content, type, tags)
    VALUES (new.id, new.content, new.type, new.tags);
END;

-- Raw chunks: unprocessed content from various sources
CREATE TABLE IF NOT EXISTS raw_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    embedding BLOB,
    source TEXT,
    source_type TEXT NOT NULL CHECK(source_type IN ('book', 'podcast', 'session', 'article')),
    metadata TEXT DEFAULT '{}',  -- JSON object
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    tried_at TEXT  -- set when a chunk has been offered to the extractor, even if no memory was produced
);

-- NOTE: raw_chunks_vec virtual table is created separately after sqlite-vec is loaded.

-- Extractions: links raw chunks to curated memories
CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_chunk_id INTEGER NOT NULL REFERENCES raw_chunks(id),
    curated_memory_id INTEGER NOT NULL REFERENCES curated_memories(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Meta: simple key-value store for config and state
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Sessions: one row per conversation session, populated by ingest_sessions + classify
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    date          TEXT NOT NULL,
    title         TEXT,
    summary       TEXT,
    status        TEXT NOT NULL DEFAULT 'unprocessed'
                      CHECK(status IN ('open', 'closed', 'unprocessed')),
    tags          TEXT DEFAULT '[]',
    chunk_count   INTEGER DEFAULT 0,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    classified_at TEXT
);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    """Create (or open) the Cortex database at *path* and ensure the schema exists.

    Returns an open connection with WAL mode enabled.
    If sqlite-vec is unavailable, the raw_chunks_vec table is not created
    but the rest of the schema works normally.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)

    # Idempotent migration: add raw_chunks.tried_at on databases created
    # before the column was introduced.
    try:
        conn.execute("ALTER TABLE raw_chunks ADD COLUMN tried_at TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Idempotent migration: databases created before 'insight' was added to
    # the curated_memories.type CHECK constraint need it patched in so the
    # reflect pipeline can store insight rows. SQLite cannot ALTER a CHECK
    # constraint, so we rewrite sqlite_master directly.
    current_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='curated_memories'"
    ).fetchone()
    if current_sql and "'insight'" not in current_sql[0]:
        conn.execute("PRAGMA writable_schema = 1")
        conn.execute(
            "UPDATE sqlite_master "
            "SET sql = replace(sql, "
            "\"'fact', 'idea')\", "
            "\"'fact', 'idea', 'insight')\") "
            "WHERE type='table' AND name='curated_memories'"
        )
        conn.execute("PRAGMA writable_schema = 0")
        conn.commit()

    if VEC_AVAILABLE:
        # Load sqlite-vec extension and create the vector index table
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS raw_chunks_vec "
                "USING vec0(embedding float[384])"
            )
            logger.debug("sqlite-vec loaded successfully")
        except Exception as e:
            logger.warning("Failed to load sqlite-vec extension: %s", e)
    else:
        logger.debug("Skipping sqlite-vec setup (not installed)")

    return conn
