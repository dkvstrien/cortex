"""Cortex UI — FastAPI backend."""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.db import get_conn

app = FastAPI(title="Cortex UI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5093", "http://thinkpad:5093"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/sessions")
def list_sessions(
    status: Optional[str] = Query(None, pattern="^(open|closed|unprocessed|all)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_conn),
):
    offset = (page - 1) * limit
    params: list = []
    where = ""
    if status and status != "all":
        where = "WHERE s.status = ?"
        params.append(status)
    params += [limit, offset]
    query = f"""
        SELECT s.id, s.date, s.title, s.summary, s.status, s.tags,
               s.chunk_count, s.classified_at,
               COUNT(cm.id) as memory_count
        FROM sessions s
        LEFT JOIN curated_memories cm ON cm.source = s.id AND cm.deleted_at IS NULL
        {where}
        GROUP BY s.id
        ORDER BY s.date DESC, s.first_seen_at DESC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": r["id"],
            "date": r["date"],
            "title": r["title"],
            "summary": r["summary"],
            "status": r["status"],
            "tags": json.loads(r["tags"] or "[]"),
            "chunk_count": r["chunk_count"],
            "classified_at": r["classified_at"],
            "memory_count": r["memory_count"],
        }
        for r in rows
    ]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    safe_id = session_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    chunks = conn.execute(
        """SELECT id, content, created_at FROM raw_chunks
           WHERE source LIKE ? ESCAPE '\\' AND source_type = 'session'
           ORDER BY created_at DESC LIMIT 10""",
        (f"%:{safe_id}",),
    ).fetchall()

    memories = conn.execute(
        """SELECT id, content, type, tags FROM curated_memories
           WHERE source = ? AND deleted_at IS NULL""",
        (session_id,),
    ).fetchall()

    return {
        "id": row["id"],
        "date": row["date"],
        "title": row["title"],
        "summary": row["summary"],
        "status": row["status"],
        "tags": json.loads(row["tags"] or "[]"),
        "chunk_count": row["chunk_count"],
        "classified_at": row["classified_at"],
        "chunks": [
            {"id": c["id"], "content": c["content"], "created_at": c["created_at"]}
            for c in chunks
        ],
        "memories": [
            {
                "id": m["id"],
                "content": m["content"],
                "type": m["type"],
                "tags": json.loads(m["tags"]) if m["tags"] else [],
            }
            for m in memories
        ],
    }


@app.get("/api/sessions/{session_id}/transcript")
def get_transcript(session_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    exists = conn.execute(
        "SELECT id FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Session not found")

    safe_id = session_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    chunks = conn.execute(
        """SELECT id, content, created_at FROM raw_chunks
           WHERE source LIKE ? ESCAPE '\\' AND source_type = 'session'
           ORDER BY created_at ASC""",
        (f"%:{safe_id}",),
    ).fetchall()

    return {
        "session_id": session_id,
        "chunks": [
            {"id": c["id"], "content": c["content"], "created_at": c["created_at"]}
            for c in chunks
        ],
    }
