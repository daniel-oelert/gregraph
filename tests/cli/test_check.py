"""Tests for ``gregraph check`` (spec §13.8, §7.5 hook policy).

Exit 1 iff the hook would block: validation errors, newly outdated links
under ``versioning.on_outdated_links = "block"``, open conflicts under
``graph.open_conflicts = "block"`` on the baseline branch, change requests
modified after their last decision under ``versioning.on_cr_modified =
"block"``. Warnings never abort; links already outdated before the change are
reported but never block (D2 refinement 2). CLI tests invoke
``gregraph.cli.main.main([...])``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gregraph.cli.main import main
from gregraph.core.config import read_config, write_config
from gregraph.core.models import Document
from gregraph.core.operations import create_document, link
from gregraph.core.storage import config_path, read_sidecar, write_body
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import GitIdentity


def add_template(root: Path, name: str) -> None:
    directory = root / ".gregraph" / "templates" / name / "v1"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = {
        "schema": 1,
        "name": name,
        "version": 1,
        "description": f"{name} v1",
        "deprecated": False,
        "breaking": False,
        "sections": [{"heading": "Notes", "required": False, "placeholder": ""}],
    }
    (directory / "template.json").write_text(json.dumps(descriptor), encoding="utf-8")
    (directory / "template.md").write_text(
        "# {{ title }}\n\n## Notes\n", encoding="utf-8"
    )


def linked_pair(root: Path) -> tuple[str, str]:
    """A goal and a user-story refining it (fresh link, version 1)."""
    add_template(root, "goal")
    add_template(root, "user-story")
    workspace = Workspace.open(root)
    goal = create_document(workspace, type="goal", title="Goal")
    story = create_document(
        workspace, type="user-story", title="Story", links=[("refines", goal.id)]
    )
    return goal.id, story.id


def edit_body(root: Path, doc_id: str) -> None:
    body = next((root / "documents").rglob(f"{doc_id}.md"))
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")


def read_doc(root: Path, doc_id: str) -> Document:
    return read_sidecar(next((root / "documents").rglob(f"{doc_id}.json")), Document)


def run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def commit_seed(root: Path, message: str = "init") -> None:
    """Test scaffolding: commit the whole tree when ``root`` is a Git repository.

    The uncommitted-``v1`` grace period (AGENT_READINESS §3.3) applies only to
    documents absent from ``HEAD``; committing the seed first makes a later
    edit a normal post-commit ``v1 → v2`` bump.
    """
    if not (root / ".git").exists():
        return
    run_git(root, "add", "-A")
    run_git(root, "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-m", message)


# --------------------------------------------------------------------------
# blocking policy (spec §7.5)
# --------------------------------------------------------------------------


def test_check_ok_on_clean_repo(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    linked_pair(tmp_repo)
    assert main(["--repo", str(tmp_repo), "check"]) == 0
    assert "check: ok" in capsys.readouterr().out


def test_check_blocks_on_validation_error(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    goal_id, _ = linked_pair(tmp_repo)
    sidecar = next((tmp_repo / "documents").rglob(f"{goal_id}.json"))
    sidecar.write_text("{not json", encoding="utf-8")
    assert main(["--repo", str(tmp_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "check: blocked" in out
    assert "validation error" in out
    assert "E-SIDECAR-INVALID" in out


def test_check_blocks_on_newly_outdated_links(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    goal_id, story_id = linked_pair(tmp_repo)
    commit_seed(tmp_repo)  # git mode: v1 is in HEAD, so an edit is a normal bump
    edit_body(tmp_repo, goal_id)
    assert main(["--repo", str(tmp_repo), "check"]) == 1
    out = capsys.readouterr().out
    assert "newly outdated:" in out
    assert f"{story_id} refines → {goal_id}" in out
    assert f"gregraph link refresh {story_id} refines {goal_id}" in out
    assert "check: blocked" in out
    assert main(["--repo", str(tmp_repo), "link", "refresh", "--to", goal_id]) == 0
    assert main(["--repo", str(tmp_repo), "check"]) == 0


def test_check_warn_policy_never_blocks(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    goal_id, _ = linked_pair(tmp_repo)
    config = read_config(config_path(tmp_repo))
    config.versioning.on_outdated_links = "warn"
    write_config(config_path(tmp_repo), config)
    commit_seed(tmp_repo)
    edit_body(tmp_repo, goal_id)
    assert main(["--repo", str(tmp_repo), "check"]) == 0
    out = capsys.readouterr().out
    assert "newly outdated:" in out
    assert "check: ok" in out


def test_check_previously_outdated_reported_not_blocking(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    goal_id, story_id = linked_pair(tmp_repo)
    commit_seed(tmp_repo)
    edit_body(tmp_repo, goal_id)
    assert main(["--repo", str(tmp_repo), "sync", "--bump"]) == 0
    assert read_doc(tmp_repo, story_id).links[0].target_version == 1  # outdated
    edit_body(tmp_repo, story_id)  # unrelated change
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "check"]) == 0
    out = capsys.readouterr().out
    assert "check: ok" in out
    assert "newly outdated:" not in out


def test_check_json_payload(tmp_repo: Path) -> None:
    import contextlib
    import io

    goal_id, story_id = linked_pair(tmp_repo)
    commit_seed(tmp_repo)
    edit_body(tmp_repo, goal_id)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(tmp_repo), "check", "--json"]) == 1
    payload = json.loads(buffer.getvalue())
    assert payload["blocked"] is True
    assert payload["would_bump"] == [goal_id]
    entry = payload["newly_outdated"][0]
    assert entry["source"] == story_id
    assert entry["target"] == goal_id
    assert entry["fix"] == f"gregraph link refresh {story_id} refines {goal_id}"
    assert isinstance(payload["findings"], list)


def test_check_exit_codes_match_hook(tmp_repo: Path, identity: GitIdentity) -> None:
    """check exits exactly when ``hook pre-commit`` would abort the commit."""
    goal_id, _story_id = linked_pair(tmp_repo)
    run_git(tmp_repo, "add", "-A")
    run_git(tmp_repo, "commit", "-m", "initial")
    edit_body(tmp_repo, goal_id)
    run_git(tmp_repo, "add", "-A")
    assert main(["--repo", str(tmp_repo), "check"]) == 1
    assert main(["--repo", str(tmp_repo), "hook", "pre-commit"]) == 1
    assert main(["--repo", str(tmp_repo), "link", "refresh", "--to", goal_id]) == 0
    run_git(tmp_repo, "add", "-A")
    assert main(["--repo", str(tmp_repo), "check"]) == 0
    assert main(["--repo", str(tmp_repo), "hook", "pre-commit"]) == 0


def test_check_open_conflicts_block_policy_on_baseline(
    tmp_repo: Path, identity: GitIdentity
) -> None:
    goal_id, story_id = linked_pair(tmp_repo)
    workspace = Workspace.open(tmp_repo)
    link(workspace, source=story_id, link_type="conflicts-with", target=goal_id)
    config = read_config(config_path(tmp_repo))
    config.graph.open_conflicts = "block"
    write_config(config_path(tmp_repo), config)
    run_git(tmp_repo, "add", "-A")
    run_git(tmp_repo, "commit", "-m", "initial")
    run_git(tmp_repo, "branch", "-M", "main")
    edit_body(tmp_repo, story_id)
    run_git(tmp_repo, "add", "-A")
    assert main(["--repo", str(tmp_repo), "check"]) == 1


# --------------------------------------------------------------------------
# uncommitted-v1 grace period (AGENT_READINESS §3.3, AGENT-011) and payload
# --------------------------------------------------------------------------


def test_check_initialised_bucket_for_uncommitted_v1(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.3: an uncommitted ``v1`` edit lands in ``initialised``, not
    ``would_bump``, and never blocks as a pending-outdated target."""
    if not (tmp_repo / ".git").exists():
        pytest.skip("the grace period is a git-mode behaviour")
    goal_id, _story_id = linked_pair(tmp_repo)
    commit_seed(tmp_repo)
    workspace = Workspace.open(tmp_repo)
    fresh = create_document(
        workspace, type="user-story", title="Fresh story", links=[("refines", goal_id)]
    )
    edit_body(tmp_repo, fresh.id)
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["initialised"] == [fresh.id]
    assert payload["would_bump"] == []
    assert payload["blocked"] is False
    assert read_doc(tmp_repo, fresh.id).version == 1
    entry = payload["newly_outdated"]
    assert entry == []  # a grace target is never pending-outdated (§3.3 rule 4)


def test_check_json_payload_has_additive_keys(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2.4.3: ``check --json`` keeps its shape and adds the new keys."""
    goal_id, story_id = linked_pair(tmp_repo)
    commit_seed(tmp_repo)
    edit_body(tmp_repo, goal_id)
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "check", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "blocked",
        "block_reasons",
        "would_bump",
        "initialised",
        "findings",
        "newly_outdated",
        "previously_outdated",
        "stale",
        "pending",
        "refresh_commands",
        "notices",
    }
    assert payload["would_bump"] == [goal_id]
    assert payload["initialised"] == []
    assert payload["refresh_commands"] == [
        f"gregraph link refresh {story_id} refines {goal_id}"
    ]
    for entry in payload["previously_outdated"] + payload["stale"] + payload["pending"]:
        assert set(entry) == {
            "source",
            "type",
            "target",
            "link_target_version",
            "target_version",
            "effective",
            "state",
            "newly",
        }
