"""Unified recall: search across curated and raw layers with fallback."""

from __future__ import annotations

import sqlite3
from typing import Any

from cortex.curated import recall_curated
from cortex.raw import recall_raw


def _normalize_bm25(rank: float) -> float:
    """Convert BM25 rank (negative, lower=better) to 0-1 scale (1=best).

    BM25 scores from SQLite FTS5 are negative floats where more negative
    means a better match. We map them to 0-1 using: score = -rank / (1 - rank).
    This gives 0 when rank=0 (no match) and approaches 1 as rank -> -inf.
    """
    if rank >= 0.0:
        return 0.0
    return -rank / (1.0 - rank)


def _normalize_distance(distance: float) -> float:
    """Convert cosine distance (0=identical, higher=worse) to 0-1 scale (1=best).

    score = 1 / (1 + distance)
    """
    return 1.0 / (1.0 + distance)


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts based on word sets."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def recall(
    conn: sqlite3.Connection,
    query: str,
    *,
    type: str | None = None,
    limit: int = 10,
    layer: str = "curated",
) -> list[dict[str, Any]]:
    """Search memories across curated and/or raw layers.

    Parameters
    ----------
    conn:
        Open SQLite connection with the Cortex schema.
    query:
        Free-text search query.
    type:
        For curated layer: filter by memory type.
        For raw layer: maps to source_type filter.
    limit:
        Maximum total results to return.
    layer:
        Which layer(s) to search:
        - 'curated' (default): FTS5 search only
        - 'raw': vector search only
        - 'both': curated first, then fill remaining from raw (deduplicated)

    Returns
    -------
    List of result dicts. Each has a 'score' key (0-1, higher=better)
    and a 'layer' key ('curated' or 'raw').
    """
    if layer == "curated":
        return _search_curated(conn, query, type=type, limit=limit)
    elif layer == "raw":
        return _search_raw(conn, query, source_type=type, limit=limit)
    elif layer == "both":
        return _search_both(conn, query, type=type, limit=limit)
    else:
        raise ValueError(f"Invalid layer: {layer!r}. Must be 'curated', 'raw', or 'both'.")


def _search_curated(
    conn: sqlite3.Connection,
    query: str,
    *,
    type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search curated layer and add normalized score + layer tag."""
    results = recall_curated(conn, query, type=type, limit=limit)
    for r in results:
        r["score"] = _normalize_bm25(r["rank"])
        r["layer"] = "curated"
    return results


def _search_raw(
    conn: sqlite3.Connection,
    query: str,
    *,
    source_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search raw layer and add normalized score + layer tag."""
    results = recall_raw(conn, query, source_type=source_type, limit=limit)
    for r in results:
        r["score"] = _normalize_distance(r["distance"])
        r["layer"] = "raw"
    return results


def _search_both(
    conn: sqlite3.Connection,
    query: str,
    *,
    type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search curated first, fill remaining slots from raw, deduplicate."""
    # Get curated results first (priority)
    curated = _search_curated(conn, query, type=type, limit=limit)

    remaining = limit - len(curated)
    if remaining <= 0:
        return curated[:limit]

    # Fetch extra raw results to account for deduplication
    raw = _search_raw(conn, query, source_type=type, limit=remaining * 2)

    # Deduplicate: skip raw results whose content closely matches a curated result
    curated_contents = [r["content"] for r in curated]
    deduped_raw: list[dict[str, Any]] = []
    for raw_result in raw:
        if len(deduped_raw) >= remaining:
            break
        if _is_duplicate(raw_result["content"], curated_contents):
            continue
        deduped_raw.append(raw_result)

    return curated + deduped_raw


def _is_duplicate(content: str, existing_contents: list[str], threshold: float = 0.6) -> bool:
    """Check if content is a duplicate of any existing content."""
    for existing in existing_contents:
        # Exact substring match
        if content in existing or existing in content:
            return True
        # Jaccard similarity
        if _jaccard_similarity(content, existing) >= threshold:
            return True
    return False
