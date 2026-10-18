"""Tests for ``gregraph init`` (spec §13.1, §3, §5.5) and the M1 acceptance.

Layout, built-in template copying (``--templates all|minimal``), config,
``.gitignore``/``README.md``, ``git init``/hook installation, and the refusal
when ``.gregraph/`` exists. CLI tests invoke ``gregraph.cli.main.main([...])``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_legacy_config_is_exit_3_with_migration_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / ".gregraph" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        '[gregraph]\nconfig_schema = 1\ntool_version = "0.1.1"\n',
        encoding="utf-8",
    )
    assert main(["--repo", str(tmp_path), "validate"]) == 3
    captured = capsys.readouterr()
    assert "migrate_type_ids" in captured.err
    assert captured.out == ""


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


def test_init_in_subdirectory_of_worktree_creates_own_repository(
    tmp_path: Path,
) -> None:
    import subprocess

    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=outer, check=True, capture_output=True
    )
    target = outer / "nested"
    assert main(["init", str(target)]) == 0
    head = (target / ".git" / "HEAD").read_text(encoding="utf-8")
    assert "refs/heads/main" in head
    hook = target / ".git" / "hooks" / "pre-commit"
    assert hook.is_file()
    assert "gregraph hook pre-commit" in hook.read_text(encoding="utf-8")
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )
    assert Path(result.stdout.strip()).resolve() == target.resolve()
    assert not (outer / ".git" / "hooks" / "pre-commit").exists()


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
    assert is_derivable_from(document.id, document.uuid, "RE", "STORY")
    text = body.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "# Upload from the desktop"
    assert document.body_hash == body_hash(text)
    assert document.template.name == "user-story"
    assert document.version == 1

    workspace = Workspace.open(target)
    findings = validate_workspace(workspace)
    assert not [item for item in findings if item.code in STRUCTURAL_CODES]


# --------------------------------------------------------------------------
# agent instruction files (AGENT_READINESS §7.1, AGENT-031)
# --------------------------------------------------------------------------


def test_init_writes_agents_md_and_skill(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--no-git"]) == 0
    agents = target / "AGENTS.md"
    skill = target / ".agents" / "skills" / "gregraph" / "SKILL.md"
    assert agents.is_file()
    assert skill.is_file()
    text = agents.read_text(encoding="utf-8")
    assert "<!-- >>> gregraph agent instructions >>> -->" in text
    assert "<!-- <<< gregraph agent instructions <<< -->" in text
    assert "never hand-edit" in text
    skill_text = skill.read_text(encoding="utf-8")
    assert skill_text.startswith("---\n")
    assert "name: gregraph" in skill_text
    assert "description:" in skill_text


def test_init_human_output_reports_agents_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--no-git"]) == 0
    out = capsys.readouterr().out
    assert "agents files written: AGENTS.md, .agents/skills/gregraph/SKILL.md" in out


def test_init_json_payload_lists_agents_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "repo"
    assert main(["init", str(target), "--no-git", "--json"]) == 0
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert set(payload) == {
        "root",
        "created",
        "templates",
        "git_initialised",
        "hooks_installed",
        "agents_files",
        "findings",
        "notices",
    }
    assert payload["agents_files"] == [
        "AGENTS.md",
        ".agents/skills/gregraph/SKILL.md",
    ]
    assert payload["root"] == str(target)
    assert payload["git_initialised"] is False
    assert (target / "AGENTS.md").is_file()
    assert (target / ".agents" / "skills" / "gregraph" / "SKILL.md").is_file()


def test_init_preserves_existing_agents_md_content(tmp_path: Path) -> None:
    """AGENT-031: pre-existing ``AGENTS.md`` content is preserved and the
    managed block is appended."""
    target = tmp_path / "repo"
    target.mkdir()
    (target / "AGENTS.md").write_text("# My project notes\n", encoding="utf-8")
    assert main(["init", str(target), "--no-git"]) == 0
    text = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# My project notes\n")
    assert text.count("<!-- >>> gregraph agent instructions >>> -->") == 1
