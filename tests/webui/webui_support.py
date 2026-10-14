"""Plain helpers shared by the web UI tests (not fixtures; see conftest.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gregraph.core.operations import create_document
from gregraph.core.workspace import Workspace

LOOPBACK_BASE = "http://127.0.0.1"
TOKEN_HEADER = "X-GREGraph-Token"


def auth(token: str) -> dict[str, str]:
    """Headers for a valid JSON mutation."""
    return {TOKEN_HEADER: token, "Content-Type": "application/json"}


def add_document(root: Path, *, type: str, title: str) -> str:
    """Create a document through core (the same path the CLI uses)."""
    result = create_document(Workspace.open(root), type=type, title=title)
    return result.id


def error_code(response: Any) -> str:
    """Finding code of a ``{"error": Finding}`` envelope."""
    body = response.json()
    assert set(body) == {"error"}, body
    return str(body["error"]["code"])
