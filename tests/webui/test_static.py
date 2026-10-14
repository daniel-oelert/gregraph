"""Static bundle serving and the fixed route surface (design §21.4, §21.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webui_support import LOOPBACK_BASE, error_code

from gregraph.webui import app as app_module
from gregraph.webui.app import create_app


@pytest.fixture
def static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        "<!doctype html><title>GREGraph</title>", encoding="utf-8"
    )
    (static / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    return static


def test_index_is_served_from_the_bundle(repo: Path, static_dir: Path) -> None:
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "GREGraph" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_assets_are_served_from_the_bundle(repo: Path, static_dir: Path) -> None:
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as client:
        response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "export {};"


@pytest.mark.parametrize(
    "path",
    [
        "/assets/%2e%2e/secret.txt",
        "/assets/..%2fsecret.txt",
        "/assets/%2e%2e%2fsecret.txt",
    ],
)
def test_asset_traversal_is_refused(repo: Path, static_dir: Path, path: str) -> None:
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as client:
        response = client.get(path)

    assert response.status_code == 404
    assert "private" not in response.text


def test_missing_bundle_is_a_json_503_not_a_traceback(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "STATIC_DIR", tmp_path / "absent")
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as client:
        response = client.get("/")

    assert response.status_code == 503
    assert error_code(response) == "E-ASSETS-MISSING"


@pytest.mark.parametrize(
    "path", ["/docs", "/redoc", "/openapi.json", "/anything", "/api"]
)
def test_no_docs_no_catch_all(repo: Path, static_dir: Path, path: str) -> None:
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as client:
        response = client.get(path)

    assert response.status_code == 404
    assert "GREGraph" not in response.text
