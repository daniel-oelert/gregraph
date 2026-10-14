"""GET /api/session: contract shape, Git probe, no absolute-root leakage."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from webui_support import LOOPBACK_BASE

from gregraph import __version__
from gregraph.core.rules import EDGE_RULES
from gregraph.webui.app import create_app


def test_session_matches_frontend_contract(client: TestClient, repo: Path) -> None:
    response = client.get("/api/session")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "repository",
        "types",
        "link_types",
        "version",
        "csrf_token",
    }
    assert body["repository"]["name"] == repo.name
    assert set(body["repository"]) == {"name", "git", "degraded"}
    assert body["version"] == __version__
    assert isinstance(body["csrf_token"], str) and len(body["csrf_token"]) >= 32
    assert {"name": "user-story", "kind": "requirement"} in body["types"]
    assert sorted(body["link_types"]) == sorted(EDGE_RULES)


def test_session_never_leaks_absolute_root(client: TestClient, repo: Path) -> None:
    response = client.get("/api/session")

    assert str(repo) not in response.text
    assert str(repo.parent) not in response.text


def test_session_reports_git_and_degraded_mode(repo: Path) -> None:
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as client:
        body = client.get("/api/session").json()

    is_git = (repo / ".git").exists()
    assert body["repository"]["git"] is is_git
    assert body["repository"]["degraded"] is (not is_git)


def test_each_app_has_its_own_random_token(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    from gregraph.core.operations import init_repository

    init_repository(other, no_git=True)
    with (
        TestClient(create_app(repo), base_url=LOOPBACK_BASE) as first,
        TestClient(create_app(other), base_url=LOOPBACK_BASE) as second,
    ):
        token_one = first.get("/api/session").json()["csrf_token"]
        token_two = second.get("/api/session").json()["csrf_token"]

    assert token_one != token_two


def test_session_is_no_store(client: TestClient) -> None:
    response = client.get("/api/session")

    assert response.headers["cache-control"] == "no-store"


def test_create_app_rejects_a_directory_that_is_not_a_repository(
    tmp_path: Path,
) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        create_app(tmp_path)
