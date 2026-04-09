"""SQLite schema and database initialization for Cortex."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA_SQL = """
-- Enable WAL mode for concurrent reads
PRAGMA journal_mode=WAL;

-- Curated memories: distilled knowledge extracted from raw sources
CREATE TABLE IF NOT EXISTS curated_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('decision', 'preference', 'procedure', 'entity', 'fact', 'idea')),
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
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
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
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    """Create (or open) the Cortex database at *path* and ensure the schema exists.

    Returns an open connection with WAL mode enabled.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)

    # Load sqlite-vec extension and create the vector index table
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS raw_chunks_vec "
        "USING vec0(embedding float[384])"
    )

    return conn
