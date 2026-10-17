"""Packaging layout and metadata (spec §16.1, §16.4).

Cheap structural checks only. Building wheels and clean installs live in
``tests/packaging_check.py``, run as a dedicated CI step.
"""

from __future__ import annotations

import re
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import packaging_check as pc

import gregraph

ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "packages" / "core"
CLI_DIR = ROOT / "packages" / "cli"
WEBUI_DIR = ROOT / "packages" / "webui"
CORE_SRC = CORE_DIR / "src" / "gregraph"
CLI_SRC = CLI_DIR / "src" / "gregraph"
WEBUI_SRC = WEBUI_DIR / "src" / "gregraph"

CORE_DEPENDENCIES = [
    "pydantic>=2",
    "jinja2>=3",
    "markdown-it-py>=3",
    "mdit-py-plugins",
]
WEBUI_DEPENDENCIES = [
    f"gregraph-core=={gregraph.__version__}",
    f"gregraph-cli=={gregraph.__version__}",
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
]
DEV_GROUP = {
    "pytest",
    "pytest-cov",
    "hypothesis",
    "ruff",
    "mypy",
    "pre-commit",
    "hatchling",
    "fastapi",
    "uvicorn",
    "httpx",
}
CORE_MODULES = {
    "__init__.py",
    "agents.py",
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
CLI_TOP_MODULES = {"__init__.py", "main.py", "output.py", "prompts.py", "webui.py"}
CLI_COMMANDS = {
    "__init__.py",
    "baseline.py",
    "check.py",
    "context.py",
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
    "schema.py",
    "sections.py",
    "serve.py",
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
    names = {
        re.split(r"[<>=!~\s]", dep, maxsplit=1)[0]
        for dep in data["dependency-groups"]["dev"]
    }
    assert names >= DEV_GROUP


def test_root_tooling_covers_all_source_roots() -> None:
    data = _load(ROOT / "pyproject.toml")
    roots = ["packages/core/src", "packages/cli/src", "packages/webui/src"]
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


def test_webui_distribution_metadata() -> None:
    data = _load(WEBUI_DIR / "pyproject.toml")
    project = data["project"]
    assert project["name"] == "gregraph-webui"
    assert project["version"] == gregraph.__version__
    assert project["requires-python"] == ">=3.12"
    assert project["dependencies"] == WEBUI_DEPENDENCIES
    assert "scripts" not in project
    assert project["entry-points"] == {
        "gregraph.serve": {"webui": "gregraph.webui.launch:launch"}
    }
    assert data["build-system"]["build-backend"] == "hatchling.build"
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/gregraph"]


def test_cli_does_not_depend_on_webui() -> None:
    project = _load(CLI_DIR / "pyproject.toml")["project"]
    assert not any("gregraph-webui" in dep for dep in project["dependencies"])
    assert "gregraph.serve" not in project.get("entry-points", {})


def test_webui_module_layout() -> None:
    assert not (WEBUI_SRC / "__init__.py").exists()
    package = WEBUI_SRC / "webui"
    assert (package / "__init__.py").is_file()
    launch = (package / "launch.py").read_text(encoding="utf-8")
    assert "def launch(" in launch
    assert not (WEBUI_SRC / "core").exists()
    assert not (WEBUI_SRC / "cli").exists()
    assert not (CORE_SRC / "webui").exists()
    assert not (CLI_SRC / "webui").exists()


def test_webui_static_bundle_is_committed() -> None:
    index = WEBUI_SRC / "webui" / "static" / "index.html"
    assert index.is_file()


def test_namespace_init_is_core_only() -> None:
    init = (CORE_SRC / "__init__.py").read_text(encoding="utf-8")
    assert "pkgutil.extend_path(__path__, __name__)" in init
    assert not (CLI_SRC / "__init__.py").exists()
    assert not (WEBUI_SRC / "__init__.py").exists()
    assert (CLI_SRC / "__main__.py").is_file()
    assert not (CORE_SRC / "__main__.py").exists()
    assert not (WEBUI_SRC / "__main__.py").exists()


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


def test_editable_install_exposes_all_source_roots() -> None:
    paths = {Path(p).resolve() for p in gregraph.__path__}
    assert CORE_SRC.resolve() in paths
    assert CLI_SRC.resolve() in paths
    assert WEBUI_SRC.resolve() in paths


def test_gitignore_covers_node_modules_and_caches() -> None:
    lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    assert "node_modules/" in lines
    assert ".vite/" in lines
    assert "*.tsbuildinfo" in lines
    assert ".pytest_cache/" in lines


def test_ci_workflow_uses_group_install_and_packaging_check() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'pip>=25.1"' in text
    assert (
        "python -m pip install --group dev -e packages/core -e packages/cli "
        "-e packages/webui"
    ) in text
    assert "ruff check ." in text
    assert "ruff format --check ." in text
    assert "mypy --strict -p gregraph" in text
    assert "pytest" in text
    assert "tests/packaging_check.py" in text


def test_mypy_gate_covers_core_cli_and_webui_packages() -> None:
    # `-p gregraph` alone resolves to core's regular package and never reaches
    # cli or webui, so every distribution is named explicitly (spec §16.4).
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "mypy --strict -p gregraph -p gregraph.cli -p gregraph.webui" in text


def test_ci_runs_frontend_quality_gate_on_node_22_and_24() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "node-version:" in text
    assert "'22'" in text or '"22"' in text
    assert "'24'" in text or '"24"' in text
    assert "packages/webui/frontend" in text
    assert "npm ci" in text
    assert "npm run test" in text
    assert "npm run typecheck" in text
    assert "npm run build" in text
    assert "git diff --exit-code" in text
    assert "packages/webui/src/gregraph/webui/static" in text


# --------------------------------------------------------------------------
# packaging_check helpers for the three-wheel contract (spec §16.4)
# --------------------------------------------------------------------------

WEBUI_NAMES = {
    "gregraph/webui/__init__.py",
    "gregraph/webui/launch.py",
    "gregraph/webui/static/index.html",
    "gregraph/webui/static/assets/index-abc.js",
    "gregraph/webui/static/assets/index-abc.css",
}


def test_three_wheel_contract_accepts_split_layout() -> None:
    core = {"gregraph/__init__.py", "gregraph/core/operations.py"}
    core.add("gregraph/builtin_templates/term/v1/template.json")
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py"}
    assert pc.wheel_contract_violations(core, cli, WEBUI_NAMES) == []


def test_webui_wheel_must_not_bring_namespace_or_core_or_cli() -> None:
    core = {"gregraph/__init__.py", "gregraph/core/operations.py"}
    core.add("gregraph/builtin_templates/term/v1/template.json")
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py"}
    webui = set(WEBUI_NAMES) | {"gregraph/__init__.py", "gregraph/cli/serve.py"}
    violations = pc.wheel_contract_violations(core, cli, webui)
    assert any("webui" in v and "gregraph/__init__.py" in v for v in violations)
    assert any("webui" in v and "gregraph/cli/serve.py" in v for v in violations)


def test_core_and_cli_must_not_contain_webui_files() -> None:
    core = {"gregraph/__init__.py", "gregraph/core/operations.py"}
    core.add("gregraph/builtin_templates/term/v1/template.json")
    core.add("gregraph/webui/launch.py")
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py", "gregraph/webui/launch.py"}
    violations = pc.wheel_contract_violations(core, cli, WEBUI_NAMES)
    assert any("core wheel must not contain gregraph/webui/" in v for v in violations)
    assert any("cli wheel must not contain gregraph/webui/" in v for v in violations)


def test_webui_wheel_requires_launcher_and_static_index() -> None:
    core = {"gregraph/__init__.py", "gregraph/core/operations.py"}
    core.add("gregraph/builtin_templates/term/v1/template.json")
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py"}
    violations = pc.wheel_contract_violations(core, cli, {"gregraph/webui/__init__.py"})
    assert any("gregraph/webui/launch.py" in v for v in violations)
    assert any("static/index.html" in v for v in violations)


def test_two_wheel_contract_still_checkable_without_webui() -> None:
    core = {"gregraph/__init__.py", "gregraph/core/operations.py"}
    core.add("gregraph/builtin_templates/term/v1/template.json")
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py"}
    assert pc.wheel_contract_violations(core, cli) == []


def test_index_references_are_local_only() -> None:
    html = (
        '<html><head><link rel="stylesheet" href="/assets/app.css">'
        '<link rel="icon" href="https://example.org/x.ico"></head>'
        '<body><script type="module" src="./assets/app.js"></script>'
        '<script src="//cdn.example.org/a.js"></script></body></html>'
    )
    assert pc.index_references(html) == ["/assets/app.css", "./assets/app.js"]


def _bundle(files: dict[str, str]) -> tuple[set[str], Any]:
    names = {f"gregraph/webui/static/{name}" for name in files}
    contents = {f"gregraph/webui/static/{name}": text for name, text in files.items()}
    return names, lambda member: contents[member]


def test_static_bundle_clean_when_references_resolve() -> None:
    names, read = _bundle(
        {
            "index.html": '<link href="/assets/app.css"><script src="/assets/app.js">',
            "assets/app.js": "console.log(1)",
            "assets/app.css": "body{background:url(./bg.png)}",
            "assets/bg.png": "",
        }
    )
    assert pc.static_asset_violations(names, read) == []


def test_static_bundle_reports_missing_script_and_css_references() -> None:
    names, read = _bundle(
        {
            "index.html": '<script src="/assets/missing.js"></script>',
            "assets/app.js": "",
            "assets/app.css": "a{background:url(./nope.png)}",
        }
    )
    violations = pc.static_asset_violations(names, read)
    assert any("assets/missing.js" in v for v in violations)
    assert any("nope.png" in v for v in violations)


def test_static_bundle_requires_script_and_stylesheet() -> None:
    names, read = _bundle({"index.html": "<p>hi</p>"})
    violations = pc.static_asset_violations(names, read)
    assert any(".js" in v for v in violations)
    assert any(".css" in v for v in violations)


def test_static_bundle_requires_index_html() -> None:
    names, read = _bundle({"assets/app.js": "", "assets/app.css": ""})
    violations = pc.static_asset_violations(names, read)
    assert any("index.html" in v for v in violations)


def test_entry_point_violation_detects_missing_serve_group(tmp_path: Path) -> None:
    wheel = tmp_path / "gregraph_webui-0.1.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "gregraph_webui-0.1.1.dist-info/entry_points.txt", "[console_scripts]\n"
        )
    assert pc._entry_point_violations(wheel, "0.1.1")


# --------------------------------------------------------------------------
# installed smoke: /api/session payload (design §21.4, §21.6)
# --------------------------------------------------------------------------


def _session_payload() -> dict[str, Any]:
    return {
        "repository": {"name": "requirements", "git": True, "degraded": False},
        "types": [{"name": "requirement", "kind": "requirement"}],
        "link_types": ["refines", "satisfies"],
        "version": gregraph.__version__,
        "csrf_token": "abc123",
    }


def test_session_payload_clean_for_expected_repository() -> None:
    assert pc.session_violations(_session_payload(), "requirements") == []


def test_session_payload_requires_csrf_token_and_repository_name() -> None:
    payload = _session_payload()
    payload["csrf_token"] = ""
    payload["repository"]["name"] = "other"
    violations = pc.session_violations(payload, "requirements")
    assert any("csrf_token" in v for v in violations)
    assert any("repository.name" in v for v in violations)


def test_session_payload_requires_types_and_version() -> None:
    payload = _session_payload()
    payload["types"] = []
    del payload["version"]
    violations = pc.session_violations(payload, "requirements")
    assert any("types" in v for v in violations)
    assert any("version" in v for v in violations)


def test_session_payload_rejects_non_object() -> None:
    assert pc.session_violations(["not", "an", "object"], "requirements")


def test_smoke_urls_resolve_relative_references_against_the_page() -> None:
    # The bundle references "./assets/x.js"; joining must not leave "/./".
    assert (
        pc.page_url("http://127.0.0.1:8765/", "./assets/index-a.js")
        == "http://127.0.0.1:8765/assets/index-a.js"
    )
    assert (
        pc.page_url("http://127.0.0.1:8765/", "/assets/index-a.css")
        == "http://127.0.0.1:8765/assets/index-a.css"
    )
