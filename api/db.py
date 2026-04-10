"""Database connection helper for the Cortex API."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Generator


def get_db_path() -> str:
    return os.environ.get(
        "CORTEX_DB_PATH",
        str(Path.home() / ".cortex" / "cortex.db"),
    )


def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection to cortex.db, closing it after the request.

    Used as a FastAPI dependency via Depends(get_conn).
    Row factory set to sqlite3.Row for dict-like access.
    """
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
