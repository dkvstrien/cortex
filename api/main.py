"""Cortex UI — FastAPI backend."""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.db import get_conn
from api.vikunja import push_task

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


@app.post("/api/sessions/{session_id}/vikunja")
def push_session_to_vikunja(
    session_id: str, conn: sqlite3.Connection = Depends(get_conn)
):
    row = conn.execute(
        "SELECT title, date FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    title = row["title"] or f"Session {session_id[:8]}"
    base_url = os.environ.get("CORTEX_UI_URL", "http://cortex.dkvs8001.org")
    description = f"Continue conversation from {row['date']}\n\n{base_url}/sessions/{session_id}"

    try:
        task = push_task(title=f"Continue: {title}", description=description)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vikunja error: {exc}")

    return {"task_id": task.get("id"), "task_url": "https://tasks.dkvs8001.org"}


@app.get("/api/memories")
def list_memories(
    type: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conditions: list[str] = ["deleted_at IS NULL"]
    params: list = []
    if type:
        conditions.append("type = ?")
        params.append(type)
    if tag:
        safe_tag = tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("tags LIKE ? ESCAPE '\\\\'")
        params.append(f'%"{safe_tag}"%')
    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, content, type, tags, source, created_at
        FROM curated_memories
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "id": r["id"],
            "content": r["content"],
            "type": r["type"],
            "tags": json.loads(r["tags"]) if r["tags"] else [],
            "source": r["source"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
