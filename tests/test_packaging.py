"""Packaging layout and metadata (spec §16.1, §16.4).

Cheap structural checks only. Building wheels and clean installs live in
``tests/packaging_check.py``, run as a dedicated CI step.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import gregraph

ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "packages" / "core"
CLI_DIR = ROOT / "packages" / "cli"
CORE_SRC = CORE_DIR / "src" / "gregraph"
CLI_SRC = CLI_DIR / "src" / "gregraph"

CORE_DEPENDENCIES = [
    "pydantic>=2",
    "jinja2>=3",
    "markdown-it-py>=3",
    "mdit-py-plugins",
]
DEV_GROUP = {
    "pytest",
    "pytest-cov",
    "hypothesis",
    "ruff",
    "mypy",
    "pre-commit",
    "hatchling",
}
CORE_MODULES = {
    "__init__.py",
    "changes.py",
    "config.py",
    "git.py",
    "graph.py",
    "hashing.py",
    "hooks.py",
    "ids.py",
    "markdown.py",
    "mermaid.py",
    "models.py",
    "operations.py",
    "rules.py",
    "status.py",
    "storage.py",
    "templates.py",
    "validation.py",
    "versioning.py",
    "workspace.py",
}
CLI_TOP_MODULES = {"__init__.py", "main.py", "output.py", "prompts.py"}
CLI_COMMANDS = {
    "__init__.py",
    "baseline.py",
    "check.py",
    "cr.py",
    "deprecate.py",
    "edit.py",
    "graph.py",
    "hook.py",
    "hooks.py",
    "init.py",
    "link.py",
    "list.py",
    "migrate.py",
    "new.py",
    "refresh.py",
    "repair.py",
    "set.py",
    "show.py",
    "status.py",
    "supersede.py",
    "sync.py",
    "template.py",
    "term.py",
    "unlink.py",
    "validate.py",
}


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    return data


def _names(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir() if p.suffix == ".py"}


def test_root_pyproject_is_tooling_only() -> None:
    data = _load(ROOT / "pyproject.toml")
    assert "project" not in data
    assert "build-system" not in data
    assert set(data["dependency-groups"]["dev"]) >= DEV_GROUP


def test_root_tooling_covers_both_source_roots() -> None:
    data = _load(ROOT / "pyproject.toml")
    roots = ["packages/core/src", "packages/cli/src"]
    assert data["tool"]["mypy"]["mypy_path"] == roots
    assert set(roots) <= set(data["tool"]["ruff"]["src"])
    assert set(roots) <= set(data["tool"]["coverage"]["run"]["source"])


def test_core_distribution_metadata() -> None:
    data = _load(CORE_DIR / "pyproject.toml")
    project = data["project"]
    assert project["name"] == "gregraph-core"
    assert project["version"] == gregraph.__version__
    assert project["requires-python"] == ">=3.12"
    assert project["dependencies"] == CORE_DEPENDENCIES
    assert "scripts" not in project
    assert data["build-system"]["build-backend"] == "hatchling.build"
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/gregraph"]


def test_cli_distribution_metadata() -> None:
    data = _load(CLI_DIR / "pyproject.toml")
    project = data["project"]
    assert project["name"] == "gregraph-cli"
    assert project["version"] == gregraph.__version__
    assert project["requires-python"] == ">=3.12"
    assert project["dependencies"] == [f"gregraph-core=={gregraph.__version__}"]
    assert project["scripts"] == {"gregraph": "gregraph.cli.main:main"}
    assert data["build-system"]["build-backend"] == "hatchling.build"
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/gregraph"]


def test_namespace_init_is_core_only() -> None:
    init = (CORE_SRC / "__init__.py").read_text(encoding="utf-8")
    assert "pkgutil.extend_path(__path__, __name__)" in init
    assert not (CLI_SRC / "__init__.py").exists()
    assert (CLI_SRC / "__main__.py").is_file()
    assert not (CORE_SRC / "__main__.py").exists()


def test_core_module_layout_matches_spec() -> None:
    assert _names(CORE_SRC / "core") == CORE_MODULES
    assert (CORE_SRC / "core" / "__init__.py").is_file()
    assert (CORE_SRC / "builtin_templates").is_dir()
    assert not (CLI_SRC / "core").exists()


def test_cli_module_layout_matches_spec() -> None:
    cli = CLI_SRC / "cli"
    assert _names(cli) == CLI_TOP_MODULES
    assert _names(cli / "commands") == CLI_COMMANDS
    assert not (CLI_SRC / "builtin_templates").exists()
    assert not (CORE_SRC / "cli").exists()


def test_editable_install_exposes_both_source_roots() -> None:
    paths = {Path(p).resolve() for p in gregraph.__path__}
    assert CORE_SRC.resolve() in paths
    assert CLI_SRC.resolve() in paths


def test_ci_workflow_uses_group_install_and_packaging_check() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'pip>=25.1"' in text
    assert "python -m pip install --group dev -e packages/core -e packages/cli" in text
    assert "ruff check ." in text
    assert "ruff format --check ." in text
    assert "mypy --strict -p gregraph" in text
    assert "pytest" in text
    assert "tests/packaging_check.py" in text
