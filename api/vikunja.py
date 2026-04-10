"""Vikunja task creation client."""
from __future__ import annotations

import os
from pathlib import Path

import httpx


def _get_token() -> str:
    token_path = os.environ.get(
        "VIKUNJA_TOKEN_PATH",
        str(Path.home() / ".secrets" / "vikunja-api-token"),
    )
    return Path(token_path).read_text().strip()


def _get_api_url() -> str:
    return os.environ.get("VIKUNJA_API_URL", "https://tasks.dkvs8001.org")


def _get_project_id() -> int:
    return int(os.environ.get("VIKUNJA_PROJECT_ID", "7"))


def push_task(title: str, description: str) -> dict:
    """Create a task in Vikunja. Returns the created task dict."""
    token = _get_token()
    project_id = _get_project_id()
    url = f"{_get_api_url()}/api/v1/projects/{project_id}/tasks"

    resp = httpx.put(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title, "description": description, "priority": 2},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()
