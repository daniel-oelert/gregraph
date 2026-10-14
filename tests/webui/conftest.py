"""Shared fixtures for the optional web UI backend (design §21).

Every test drives the real FastAPI app through ``TestClient`` with the loopback
base URL ``http://127.0.0.1``; IPv6 and ``localhost`` are covered in
``test_security.py``. Repositories are created with core ``init_repository``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webui_support import LOOPBACK_BASE, auth

from gregraph.core.operations import init_repository
from gregraph.webui.app import create_app


@pytest.fixture(params=["no-git", "git"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """Initialised repository, with and without Git (degraded mode, spec §12.1)."""
    root = tmp_path / "requirements"
    root.mkdir()
    init_repository(root, no_git=request.param == "no-git")
    return root


@pytest.fixture
def client(repo: Path) -> Iterator[TestClient]:
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as test_client:
        yield test_client


@pytest.fixture
def token(client: TestClient) -> str:
    """CSRF token from ``GET /api/session`` (the only way a client obtains it)."""
    response = client.get("/api/session")
    assert response.status_code == 200
    value = response.json()["csrf_token"]
    assert isinstance(value, str) and value
    return str(value)


__all__ = ["auth"]
