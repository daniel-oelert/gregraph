"""Tests for ``gregraph cr`` (spec §13.18, §9): change-request CLI.

Scope management, decisions (``set``/``reaffirm``), reanalysis, listing and
the impact view, ``E-CR-DISABLED``, plus the §9.9 proposal-first and
single-PR walkthroughs end-to-end via the CLI. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import GitIdentity
from test_hook import doc_body, git, install_templates, write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, CrSection, write_config
from gregraph.core.models import ChangeRequest, Document
from gregraph.core.storage import config_path, read_sidecar


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


@pytest.fixture
def git_repo(repo: Path, identity: GitIdentity) -> Path:
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    return repo


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
    )


def cr_id_in(root: Path) -> str:
    crs = list((root / "changes").rglob("*.md"))
    assert len(crs) == 1
    return crs[0].stem


def cr_model(root: Path, cr_id: str) -> ChangeRequest:
    return read_sidecar(root / "changes" / f"{cr_id}.json", ChangeRequest)


def fill_cr_body(root: Path, cr_id: str) -> None:
    from test_hook import filled_body

    path = root / "changes" / f"{cr_id}.md"
    title = path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ").strip()
    path.write_text(filled_body(root, "change-request", title), encoding="utf-8")


# --------------------------------------------------------------------------
# unit surface
# --------------------------------------------------------------------------


def test_cr_new_records_scope_and_open_status(repo: Path, capsys) -> None:
    target = write_doc(repo, "feature", "Upload documents")
    assert (
        main(
            [
                "--repo",
                str(repo),
                "cr",
                "new",
                "--title",
                "Raise the upload limit",
                "--scope",
                f"{target}:modify",
                "--external-ref",
                "JIRA-123",
            ]
        )
        == 0
    )
    captured = capsys.readouterr().out
    cr_id = cr_id_in(repo)
    assert f"created {cr_id}" in captured
    assert "status open" in captured
    assert f"scope: {target}" in captured
    model = cr_model(repo, cr_id)
    assert model.status == "open"
    assert model.scope[0].id == target
    assert model.scope[0].base_version == 1
    assert model.external_ref == "JIRA-123"


def test_cr_scope_add_and_remove(repo: Path, capsys) -> None:
    target = write_doc(repo, "feature", "Upload documents")
    other = write_doc(repo, "feature", "Scan uploads")
    assert main(["--repo", str(repo), "cr", "new", "--title", "Change"]) == 0
    cr_id = cr_id_in(repo)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "cr",
                "scope",
                "add",
                cr_id,
                other,
                "--intent",
                "supersede",
            ]
        )
        == 0
    )
    assert "scope updated" in capsys.readouterr().out
    assert [entry.id for entry in cr_model(repo, cr_id).scope] == [other]
    assert main(["--repo", str(repo), "cr", "scope", "remove", cr_id, other]) == 0
    assert cr_model(repo, cr_id).scope == []
    assert main(["--repo", str(repo), "cr", "scope", "add", cr_id, target]) == 0


def test_cr_set_records_decision(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "cr", "new", "--title", "Change"]) == 0
    cr_id = cr_id_in(repo)
    assert main(["--repo", str(repo), "cr", "set", cr_id, "status=accepted"]) == 0
    captured = capsys.readouterr().out
    assert f"{cr_id}  status accepted" in captured
    model = cr_model(repo, cr_id)
    assert model.status == "accepted"
    assert [decision.status for decision in model.decisions] == ["open", "accepted"]


def test_cr_set_invalid_transition_refused(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "cr", "new", "--title", "Change"]) == 0
    cr_id = cr_id_in(repo)
    assert main(["--repo", str(repo), "cr", "set", cr_id, "status=implemented"]) == 4
    assert "E-CR-STATUS" in capsys.readouterr().err


def test_cr_reaffirm(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "cr", "new", "--title", "Change"]) == 0
    cr_id = cr_id_in(repo)
    assert main(["--repo", str(repo), "cr", "set", cr_id, "status=accepted"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(repo), "cr", "reaffirm", cr_id]) == 0
    captured = capsys.readouterr().out
    assert "reaffirmed" in captured
    assert len(cr_model(repo, cr_id).decisions) == 3


def test_cr_reanalyze_refreshes_base_versions(repo: Path, capsys) -> None:
    target = write_doc(repo, "feature", "Upload documents")
    assert (
        main(["--repo", str(repo), "cr", "new", "--title", "Change", "--scope", target])
        == 0
    )
    cr_id = cr_id_in(repo)
    capsys.readouterr()
    assert main(["--repo", str(repo), "cr", "reanalyze", cr_id]) == 0
    captured = capsys.readouterr().out
    assert f"{cr_id} base versions refreshed" in captured or "unchanged" in captured


def test_cr_list_filters(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "cr", "new", "--title", "Change one"]) == 0
    cr_id = cr_id_in(repo)
    assert main(["--repo", str(repo), "cr", "set", cr_id, "status=accepted"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(repo), "cr", "list"]) == 0
    captured = capsys.readouterr().out
    assert cr_id in captured
    assert "Change one" in captured
    assert main(["--repo", str(repo), "cr", "list", "--status", "open"]) == 0
    assert cr_id not in capsys.readouterr().out
    assert (
        main(["--repo", str(repo), "cr", "list", "--status", "accepted", "--effective"])
        == 0
    )
    assert cr_id in capsys.readouterr().out


def test_cr_show_impact_view(repo: Path, capsys) -> None:
    target = write_doc(repo, "feature", "Upload documents")
    child = write_doc(repo, "user-story", "Upload from the desktop")
    assert (
        main(["--repo", str(repo), "cr", "new", "--title", "Change", "--scope", target])
        == 0
    )
    cr_id = cr_id_in(repo)
    assert main(["--repo", str(repo), "cr", "show", cr_id]) == 0
    captured = capsys.readouterr().out
    assert f"{cr_id}  Change" in captured
    assert "decisions:" in captured
    assert "scope:" in captured
    assert "intent=modify  base=1" in captured
    assert child  # the downstream story is created above
    assert main(["--repo", str(repo), "show", cr_id]) == 0
    assert "scope:" in capsys.readouterr().out


def test_cr_disabled_refuses(repo: Path, capsys) -> None:
    write_config(config_path(repo), Config(cr=CrSection(enabled=False)))
    assert main(["--repo", str(repo), "cr", "new", "--title", "Change"]) == 4
    assert "E-CR-DISABLED" in capsys.readouterr().err


def test_cr_without_subcommand_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "cr"]) == 2


# --------------------------------------------------------------------------
# §9.9 workflows
# --------------------------------------------------------------------------


def test_proposal_first_walkthrough(git_repo: Path) -> None:
    root = git_repo
    target = write_doc(root, "feature", "Upload documents")
    commit_all(root, "initial content")
    assert main(["--repo", str(root), "hooks", "install"]) == 0

    git(root, "checkout", "-b", "cr/limit")
    assert (
        main(
            [
                "--repo",
                str(root),
                "cr",
                "new",
                "--title",
                "Raise the limit",
                "--scope",
                target,
            ]
        )
        == 0
    )
    cr_id = cr_id_in(root)
    fill_cr_body(root, cr_id)
    commit_all(root, "propose the CR")

    git(root, "checkout", "main")
    git(root, "merge", "cr/limit", "-m", "merge the proposal")
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=accepted"]) == 0
    commit_all(root, "accept the CR")

    git(root, "checkout", "-b", "implement/limit")
    body = doc_body(root, target)
    body.write_text(
        body.read_text(encoding="utf-8") + "\nRaise the limit to 200 MB.\n",
        encoding="utf-8",
    )
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=implemented"]) == 0
    commit_all(root, "implement the CR")

    model = cr_model(root, cr_id)
    assert model.status == "implemented"
    assert model.scope[0].id == target
    assert model.decisions[-1].status == "implemented"
    updated = read_sidecar(root / "documents" / "feature" / f"{target}.json", Document)
    assert updated.version == 2


def test_single_pr_walkthrough(git_repo: Path) -> None:
    root = git_repo
    target = write_doc(root, "feature", "Upload documents")
    commit_all(root, "initial content")
    assert main(["--repo", str(root), "hooks", "install"]) == 0

    git(root, "checkout", "-b", "feature/limit")
    assert (
        main(
            [
                "--repo",
                str(root),
                "cr",
                "new",
                "--title",
                "Raise the limit",
                "--scope",
                target,
            ]
        )
        == 0
    )
    cr_id = cr_id_in(root)
    fill_cr_body(root, cr_id)
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=accepted"]) == 0
    body = doc_body(root, target)
    body.write_text(
        body.read_text(encoding="utf-8") + "\nRaise the limit to 200 MB.\n",
        encoding="utf-8",
    )
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=implemented"]) == 0

    git(root, "add", "-A")
    proc = subprocess.run(
        ["git", "commit", "-m", "one PR does it all"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    assert proc.returncode == 0

    model = cr_model(root, cr_id)
    assert model.status == "implemented"
    updated = read_sidecar(root / "documents" / "feature" / f"{target}.json", Document)
    assert updated.version == 2


# --------------------------------------------------------------------------
# --json payloads (AGENT_READINESS §2.4.4) and cr new authoring flags (§3.4)
# --------------------------------------------------------------------------


def test_cr_new_json_payload(repo: Path, capsys) -> None:
    target = write_doc(repo, "user-story", "Scoped story")
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(repo),
            "cr",
            "new",
            "--title",
            "Change the story",
            "--scope",
            f"{target}:modify",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {
        "id",
        "uuid",
        "md_path",
        "json_path",
        "template",
        "sections",
        "body",
        "sidecar",
        "scope",
        "status",
        "findings",
        "notices",
    }
    assert payload["status"] == "open"
    assert payload["md_path"] == str(
        (repo / "changes" / f"{payload['id']}.md").relative_to(repo)
    )
    assert payload["scope"] == [{"id": target, "intent": "modify", "base_version": 1}]
    assert payload["sidecar"]["id"] == payload["id"]
    assert payload["template"] == {"name": "change-request", "version": 1}


def test_cr_new_section_flags_fill_the_body(repo: Path, capsys) -> None:
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(repo),
            "cr",
            "new",
            "--title",
            "Filled CR",
            "--section",
            "Motivation=Because it matters.",
            "--section",
            "Proposed change=Rewrite the story.",
            "--section",
            "Impact=One inbound link.",
            "--strict",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert "Because it matters." in payload["body"]
    cr = cr_model(repo, payload["id"])
    assert cr.status == "open"


def test_cr_new_body_flag_is_usage_error(repo: Path) -> None:
    """``cr new`` takes sections only (no whole-body flags)."""
    assert (
        main(
            [
                "--repo",
                str(repo),
                "cr",
                "new",
                "--title",
                "T",
                "--body",
                "text",
                "--no-input",
            ]
        )
        == 2
    )


def test_cr_new_unknown_section_refusal(repo: Path, capsys) -> None:
    exit_code = main(
        [
            "--repo",
            str(repo),
            "cr",
            "new",
            "--title",
            "T",
            "--section",
            "Missing=x",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 4
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-SECTION-UNKNOWN"
    details = payload["error"]["finding"]["details"]
    assert details["given_heading"] == "Missing"
    assert "Motivation" in [s["heading"] for s in details["template_sections"]]


def test_cr_scope_add_and_remove_json(repo: Path, capsys) -> None:
    target = write_doc(repo, "user-story", "Scoped story")
    assert main(["--repo", str(repo), "cr", "new", "--title", "CR", "--no-input"]) == 0
    cr_id = cr_id_in(repo)
    capsys.readouterr()
    exit_code = main(
        ["--repo", str(repo), "cr", "scope", "add", cr_id, target, "--json"]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {"cr", "added", "scope", "findings", "notices"}
    assert payload["cr"] == cr_id
    assert payload["added"] == {
        "id": target,
        "intent": "modify",
        "base_version": 1,
    }
    exit_code = main(
        ["--repo", str(repo), "cr", "scope", "remove", cr_id, target, "--json"]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {"cr", "removed", "scope", "findings", "notices"}
    assert payload["removed"] == target
    assert payload["scope"] == []


def test_cr_set_reaffirm_reanalyze_json(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "cr", "new", "--title", "CR", "--no-input"]) == 0
    cr_id = cr_id_in(repo)
    capsys.readouterr()
    exit_code = main(
        ["--repo", str(repo), "cr", "set", cr_id, "status=accepted", "--json"]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {"cr", "applied", "decision", "findings", "notices"}
    assert payload["applied"] == {"status": "accepted"}
    assert payload["decision"]["status"] == "accepted"
    exit_code = main(["--repo", str(repo), "cr", "reaffirm", cr_id, "--json"])
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {"cr", "decision", "findings", "notices"}
    assert payload["decision"]["status"] == "accepted"
    exit_code = main(["--repo", str(repo), "cr", "reanalyze", cr_id, "--json"])
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {"cr", "updated", "findings", "notices"}
    assert isinstance(payload["updated"], list)


def test_cr_list_json_rows(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "cr", "new", "--title", "CR", "--no-input"]) == 0
    cr_id = cr_id_in(repo)
    capsys.readouterr()
    exit_code = main(["--repo", str(repo), "cr", "list", "--json"])
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert payload == [
        {
            "id": cr_id,
            "title": "CR",
            "status": "open",
            "effective": "open",
            "drift": False,
        }
    ]


def test_cr_show_json_matches_show_command(repo: Path, capsys) -> None:
    target = write_doc(repo, "user-story", "Scoped story")
    assert (
        main(
            [
                "--repo",
                str(repo),
                "cr",
                "new",
                "--title",
                "CR",
                "--scope",
                target,
                "--no-input",
            ]
        )
        == 0
    )
    cr_id = cr_id_in(repo)
    capsys.readouterr()
    exit_code = main(["--repo", str(repo), "cr", "show", cr_id, "--json"])
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert payload["id"] == cr_id
    assert payload["kind"] == "change-request"
    assert payload["scope"][0]["id"] == target
