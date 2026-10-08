"""Tests for ``gregraph init`` (spec §13.1, §3, §5.5) and the M1 acceptance.

Layout, built-in template copying (``--templates all|minimal``), config,
``.gitignore``/``README.md``, ``git init``/hook installation, and the refusal
when ``.gregraph/`` exists. CLI tests invoke ``gregraph.cli.main.main([...])``.
"""

from __future__ import annotations

import json
from pathlib import Path

from gregraph.cli.main import main
from gregraph.core.config import Config, read_config
from gregraph.core.hashing import body_hash
from gregraph.core.ids import is_derivable_from
from gregraph.core.models import Document
from gregraph.core.storage import config_path, read_sidecar
from gregraph.core.validation import validate_workspace
from gregraph.core.workspace import Workspace

BUILTIN_NAMES = [
    "assumption",
    "change-request",
    "constraint",
    "context",
    "decision",
    "design",
    "epic",
    "feature",
    "goal",
    "requirement-ears",
    "stakeholder",
    "term",
    "test-case",
    "user-story",
]

STRUCTURAL_CODES = {
    "E-SIDECAR-MISSING",
    "E-BODY-MISSING",
    "E-SIDECAR-INVALID",
    "E-ID-FILENAME",
    "E-ID-DERIVATION",
    "E-ID-DUPLICATE",
    "E-TITLE-MISSING",
}


def test_init_layout_and_config(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    assert (
        main(
            [
                "init",
                str(target),
                "--prefix",
                "XX",
                "--baseline-branch",
                "trunk",
                "--no-git",
            ]
        )
        == 0
    )
    for name in ("documents", "changes", "glossary", "assets"):
        assert (target / name).is_dir()
    config = read_config(config_path(target))
    assert config.ids.prefix == "XX"
    assert config.git.baseline_branch == "trunk"
    assert config.types == Config().types
    assert (target / ".gitignore").read_text(encoding="utf-8") == ".gregraph/cache/\n"
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "documents/" in readme
    assert ".gregraph/" in readme


def test_init_copies_all_builtin_templates(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--no-git"]) == 0
    templates = target / ".gregraph" / "templates"
    assert sorted(path.name for path in templates.iterdir()) == BUILTIN_NAMES
    for name in BUILTIN_NAMES:
        version = templates / name / "v1"
        assert (version / "template.md").is_file()
        descriptor = json.loads((version / "template.json").read_text(encoding="utf-8"))
        assert descriptor["name"] == name
        assert descriptor["version"] == 1


def test_init_minimal_templates_cover_default_config(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--templates", "minimal", "--no-git"]) == 0
    copied = sorted(
        path.name for path in (target / ".gregraph" / "templates").iterdir()
    )
    assert set(copied) <= set(BUILTIN_NAMES)
    assert {"user-story", "change-request", "term"} <= set(copied)
    config = read_config(config_path(target))
    needed = {spec.template for spec in config.types.values()} | {
        config.cr.template,
        "term",
    }
    assert set(copied) == needed & set(BUILTIN_NAMES)


def test_init_refuses_existing_repository(tmp_path: Path, capsys) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--no-git"]) == 0
    assert main(["init", str(target), "--no-git"]) == 4
    assert "E-INIT-EXISTS" in capsys.readouterr().err


def test_init_no_git_skips_git_and_hooks(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--no-git"]) == 0
    assert not (target / ".git").exists()
    assert not (target / ".git" / "hooks" / "pre-commit").exists()


def test_init_runs_git_init_and_installs_hooks(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target)]) == 0
    assert (target / ".git").is_dir()
    head = (target / ".git" / "HEAD").read_text(encoding="utf-8")
    assert "refs/heads/main" in head
    hook = target / ".git" / "hooks" / "pre-commit"
    assert hook.is_file()
    assert "gregraph hook pre-commit" in hook.read_text(encoding="utf-8")


def test_init_in_existing_git_repo_installs_hooks_only(tmp_path: Path) -> None:
    import subprocess

    target = tmp_path / "repo"
    target.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True
    )
    assert main(["init", str(target)]) == 0
    assert (target / ".git" / "hooks" / "pre-commit").is_file()


def test_init_invalid_prefix_is_usage_error(tmp_path: Path, capsys) -> None:
    assert (
        main(["init", str(tmp_path / "repo"), "--prefix", "bad prefix", "--no-git"])
        == 2
    )
    assert "error" in capsys.readouterr().err


def test_init_appends_existing_gitignore(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / ".gitignore").write_text("*.log\n", encoding="utf-8")
    assert main(["init", str(target), "--no-git"]) == 0
    text = (target / ".gitignore").read_text(encoding="utf-8")
    assert text.splitlines() == ["*.log", ".gregraph/cache/"]


def test_init_preserves_existing_readme(tmp_path: Path, capsys) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("mine\n", encoding="utf-8")
    assert main(["init", str(target), "--no-git"]) == 0
    assert (target / "README.md").read_text(encoding="utf-8") == "mine\n"
    assert "README.md" in capsys.readouterr().err


def test_m1_init_then_new_writes_valid_pair(tmp_path: Path, capsys) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--no-git"]) == 0
    assert (
        main(
            [
                "--repo",
                str(target),
                "new",
                "user-story",
                "--title",
                "Upload from the desktop",
                "--no-input",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    bodies = sorted((target / "documents" / "user-story").glob("*.md"))
    assert len(bodies) == 1
    body = bodies[0]
    sidecar = body.with_suffix(".json")
    assert sidecar.is_file()
    assert body.stem in captured.out
    assert str(Path("documents") / "user-story" / body.name) in captured.out

    document = read_sidecar(sidecar, Document)
    assert document.id == body.stem
    assert document.title == "Upload from the desktop"
    assert document.type == "user-story"
    assert is_derivable_from(document.id, document.uuid, "RE")
    text = body.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "# Upload from the desktop"
    assert document.body_hash == body_hash(text)
    assert document.template.name == "user-story"
    assert document.version == 1

    workspace = Workspace.open(target)
    findings = validate_workspace(workspace)
    assert not [item for item in findings if item.code in STRUCTURAL_CODES]
