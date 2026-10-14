"""launch(): loopback-only validation and one uvicorn process (design §21.3)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from gregraph.webui import launch as launch_module
from gregraph.webui.launch import launch

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "packages" / "webui" / "pyproject.toml"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    def fake_run(app: FastAPI, **kwargs: Any) -> None:
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr(launch_module.uvicorn, "run", fake_run)
    return calls


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "192.168.1.5", "example.com", "::", "", "127.0.0.2:8765"]
)
def test_non_loopback_host_is_refused_before_any_socket(
    repo: Path, captured: dict[str, Any], host: str
) -> None:
    with pytest.raises(ValueError):
        launch(repo, host=host, port=8765)

    assert captured == {}


@pytest.mark.parametrize("port", [0, -1, 65536, 1_000_000])
def test_out_of_range_ports_are_refused(
    repo: Path, captured: dict[str, Any], port: int
) -> None:
    with pytest.raises(ValueError):
        launch(repo, port=port)

    assert captured == {}


def test_bool_is_not_a_port(repo: Path, captured: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        launch(repo, port=True)  # type: ignore[arg-type]

    assert captured == {}


def test_non_repository_is_refused(tmp_path: Path, captured: dict[str, Any]) -> None:
    with pytest.raises(FileNotFoundError):
        launch(tmp_path)

    assert captured == {}


def test_defaults_serve_the_app_on_loopback_and_return_zero(
    repo: Path, captured: dict[str, Any]
) -> None:
    result = launch(repo)

    assert result == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8765
    assert isinstance(captured["app"], FastAPI)
    assert captured.get("reload") in (None, False)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_each_allowed_loopback_host_is_served(
    repo: Path, captured: dict[str, Any], host: str
) -> None:
    assert launch(repo, host=host, port=9000) == 0
    assert captured["host"] == host
    assert captured["port"] == 9000


def test_launch_binds_the_app_to_the_requested_port_for_host_checks(
    repo: Path, captured: dict[str, Any]
) -> None:
    launch(repo, port=9001)

    from fastapi.testclient import TestClient

    with TestClient(captured["app"], base_url="http://127.0.0.1:9001") as client:
        assert client.get("/api/session").status_code == 200
    with TestClient(captured["app"], base_url="http://127.0.0.1:9002") as client:
        assert client.get("/api/session").status_code == 403


def test_no_token_is_printed_in_the_url_by_launch(
    repo: Path, captured: dict[str, Any]
) -> None:
    # The token is served by GET /api/session; launch has no fragment or announce hook.
    launch(repo)

    assert "announce" not in captured


def test_webui_distribution_metadata() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    core = tomllib.loads((ROOT / "packages" / "core" / "pyproject.toml").read_text())[
        "project"
    ]

    assert project["name"] == "gregraph-webui"
    assert project["version"] == core["version"] == "0.1.1"
    assert project["requires-python"] == ">=3.12"
    deps = project["dependencies"]
    assert f"gregraph-core=={core['version']}" in deps
    assert f"gregraph-cli=={core['version']}" in deps
    assert any(dep.startswith("fastapi>=0.115") for dep in deps)
    assert any(dep.startswith("uvicorn>=0.30") for dep in deps)
    entry = project_entry_points()
    assert entry == {"webui": "gregraph.webui.launch:launch"}


def project_entry_points() -> dict[str, str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return dict(data["project"]["entry-points"]["gregraph.serve"])


def test_webui_contributes_no_gregraph_init_module() -> None:
    assert not (
        ROOT / "packages" / "webui" / "src" / "gregraph" / "__init__.py"
    ).exists()
    assert (
        ROOT / "packages" / "webui" / "src" / "gregraph" / "webui" / "launch.py"
    ).is_file()


def test_uvicorn_ignores_forwarded_headers_and_banner(
    repo: Path, captured: dict[str, Any]
) -> None:
    launch(repo)

    assert captured["proxy_headers"] is False
    assert captured["forwarded_allow_ips"] == ""
    assert captured["server_header"] is False


def test_bind_failure_is_an_environment_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_to_bind(app: FastAPI, **kwargs: Any) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(launch_module.uvicorn, "run", refuse_to_bind)

    with pytest.raises(OSError):
        launch(repo, port=8765)
