"""S0 scaffold smoke tests.

Behaviour tests arrive with S1+ (spec §17); these only prove the skeleton is
importable, versioned, and wired to its entry points.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import pytest

import gregraph
from gregraph.cli.main import main
from gregraph.core.config import Config, dumps_toml


def test_version_attribute() -> None:
    assert gregraph.__version__ == "0.1.1"


def test_version_consistent_across_packaging_and_config() -> None:
    root = Path(__file__).resolve().parents[1]
    for dist in ("core", "cli"):
        path = root / "packages" / dist / "pyproject.toml"
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert data["project"]["version"] == gregraph.__version__, dist
    assert f'tool_version = "{gregraph.__version__}"\n' in dumps_toml(Config())


def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == "0.1.1"


def test_python_dash_m_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "gregraph", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "0.1.1"


def test_console_script_entry_point() -> None:
    scripts = entry_points(group="console_scripts")
    gregraph_scripts = [ep for ep in scripts if ep.name == "gregraph"]
    assert [ep.value for ep in gregraph_scripts] == ["gregraph.cli.main:main"]
    assert [ep.dist.name for ep in gregraph_scripts if ep.dist] == ["gregraph-cli"]


def test_tmp_repo_layout(tmp_repo: Path) -> None:
    assert (tmp_repo / ".gregraph" / "config.toml").is_file()
    assert (tmp_repo / ".gitignore").read_text(encoding="utf-8") == ".gregraph/cache/\n"
    for name in ("documents", "changes", "glossary", "assets"):
        assert (tmp_repo / name).is_dir()


def test_identity_configures_git_user(tmp_repo: Path, identity: object) -> None:
    name = subprocess.run(
        ["git", "config", "user.name"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    email = subprocess.run(
        ["git", "config", "user.email"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert name.stdout.strip() == "Test Author"
    assert email.stdout.strip() == "test.author@example.org"
