"""Tests for ``gregraph baseline`` (spec §13.21, §12.4): baseline tags.

``baseline create`` refuses on uncommitted managed files, validation errors,
existing tags, or without Git; ``baseline list`` shows the ``baseline/*`` tags
and degrades gracefully outside a repository. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import GitIdentity
from test_hook import doc_body, git, install_templates, write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.storage import config_path


@pytest.fixture
def repo(tmp_repo: Path, identity: GitIdentity) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    git(tmp_repo, "symbolic-ref", "HEAD", "refs/heads/main")
    return tmp_repo


def commit_all(root: Path, message: str = "content") -> None:
    git(root, "add", "-A")
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_baseline_create_and_list(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    commit_all(repo)
    assert main(["--repo", str(repo), "baseline", "create", "v1", "-m", "first"]) == 0
    captured = capsys.readouterr().out
    assert "created baseline/v1" in captured
    assert main(["--repo", str(repo), "baseline", "list"]) == 0
    assert "baseline/v1" in capsys.readouterr().out


def test_baseline_create_refuses_existing_tag(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    commit_all(repo)
    assert main(["--repo", str(repo), "baseline", "create", "v1"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(repo), "baseline", "create", "v1"]) == 4
    assert "E-BASELINE-EXISTS" in capsys.readouterr().err


def test_baseline_create_refuses_uncommitted_files(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    commit_all(repo)
    write_doc(repo, "feature", "Scan uploads")
    assert main(["--repo", str(repo), "baseline", "create", "v1"]) == 4
    assert "E-BASELINE-UNCOMMITTED" in capsys.readouterr().err


def test_baseline_create_refuses_validation_errors(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "feature", "Upload documents")
    body = doc_body(repo, doc_id)
    body.write_text("# Upload documents\n", encoding="utf-8")
    commit_all(repo)
    assert main(["--repo", str(repo), "baseline", "create", "v1"]) == 4
    assert "E-BASELINE-INVALID" in capsys.readouterr().err


def test_baseline_create_without_git_is_refused(tmp_repo: Path, capsys) -> None:
    if (tmp_repo / ".git").exists():
        pytest.skip("needs the no-git tmp_repo")
    assert main(["--repo", str(tmp_repo), "baseline", "create", "v1"]) == 4
    assert "E-GIT-UNAVAILABLE" in capsys.readouterr().err


def test_baseline_list_without_git_notes_degraded_mode(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if (tmp_repo / ".git").exists():
        pytest.skip("needs the no-git tmp_repo")
    assert main(["--repo", str(tmp_repo), "baseline", "list"]) == 0
    captured = capsys.readouterr()
    assert "not a git repository" in captured.err


def test_baseline_without_subcommand_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "baseline"]) == 2
