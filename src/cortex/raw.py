"""Raw chunks layer: store and recall via sqlite-vec vector search."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from cortex.db import VEC_AVAILABLE
from cortex.embeddings import FASTEMBED_AVAILABLE, embed_one, serialize, serialize_vec

logger = logging.getLogger("cortex")


def store_chunk(
    conn: sqlite3.Connection,
    content: str,
    source: str,
    source_type: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Embed content, store in raw_chunks and index in sqlite-vec.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema and sqlite-vec loaded.
    content:
        The text content to store.
    source:
        Where the content came from (e.g. a file path, URL, session ID).
    source_type:
        One of: book, podcast, session, article.
    metadata:
        Optional JSON-serializable dict of extra metadata.

    Returns
    -------
    The integer ID of the newly created raw_chunks row.
    """
    if not FASTEMBED_AVAILABLE:
        raise RuntimeError(
            "fastembed is not installed — cannot store raw chunks without embeddings. "
            "Install it with: pip install fastembed"
        )
    if not VEC_AVAILABLE:
        raise RuntimeError(
            "sqlite-vec is not installed — cannot store raw chunks without vector index. "
            "Install it with: pip install sqlite-vec"
        )

    vector = embed_one(content)
    embedding_blob = serialize(vector)
    vec_blob = serialize_vec(vector)
    metadata_json = json.dumps(metadata or {})

    cursor = conn.execute(
        """
        INSERT INTO raw_chunks (content, embedding, source, source_type, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (content, embedding_blob, source, source_type, metadata_json),
    )
    chunk_id = cursor.lastrowid

    # Index the embedding in the sqlite-vec virtual table with matching rowid
    conn.execute(
        "INSERT INTO raw_chunks_vec (rowid, embedding) VALUES (?, ?)",
        (chunk_id, vec_blob),
    )
    conn.commit()
    return chunk_id


def recall_raw(
    conn: sqlite3.Connection,
    query: str,
    *,
    source_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search raw chunks by semantic similarity using sqlite-vec.

    Parameters
    ----------
    conn:
        Open SQLite connection with sqlite-vec loaded.
    query:
        Free-text query to embed and search for.
    source_type:
        If set, only return chunks of this source type.
    limit:
        Maximum number of results (default 10).

    Returns
    -------
    List of dicts with keys: id, content, source, source_type, metadata,
    distance, created_at. Ordered by cosine distance (closest first).
    """
    if not FASTEMBED_AVAILABLE or not VEC_AVAILABLE:
        missing = []
        if not FASTEMBED_AVAILABLE:
            missing.append("fastembed")
        if not VEC_AVAILABLE:
            missing.append("sqlite-vec")
        raise RuntimeError(
            f"Raw layer search requires {' and '.join(missing)}, which "
            f"{'is' if len(missing) == 1 else 'are'} not installed."
        )

    query_vec = serialize_vec(embed_one(query))

    if source_type is not None:
        # Fetch extra candidates to account for post-join filtering
        fetch_limit = limit * 4
        rows = conn.execute(
            """
            SELECT v.rowid, v.distance, rc.content, rc.source, rc.source_type,
                   rc.metadata, rc.created_at
            FROM raw_chunks_vec v
            JOIN raw_chunks rc ON rc.id = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
              AND rc.source_type = ?
            ORDER BY v.distance
            LIMIT ?
            """,
            (query_vec, fetch_limit, source_type, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT v.rowid, v.distance, rc.content, rc.source, rc.source_type,
                   rc.metadata, rc.created_at
            FROM raw_chunks_vec v
            JOIN raw_chunks rc ON rc.id = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (query_vec, limit),
        ).fetchall()

    return [
        {
            "id": row[0],
            "distance": row[1],
            "content": row[2],
            "source": row[3],
            "source_type": row[4],
            "metadata": json.loads(row[5]) if row[5] else {},
            "created_at": row[6],
        }
        for row in rows
    ]
