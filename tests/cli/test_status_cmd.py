"""Tests for ``gregraph status`` (spec §13.12, §8).

The WIP header format (``WIP: yes (3 drafts, 1 modified)`` / ``WIP: no``),
counts of documents by status, drafts with paths, modified-unbumped items,
link freshness buckets, open conflicts, deprecated template pins, change
requests, hook state and degraded mode; always exit 0. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo``/``sample_graph``
fixtures.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gregraph.cli.commands.status import wip_header
from gregraph.cli.main import main
from gregraph.core.operations import create_document
from gregraph.core.status import ItemStatus, WipState
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import SampleGraph


def run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def baseline_commit(root: Path) -> None:
    """Commit the layout on ``main`` so draft/active status is derivable."""
    if not (root / ".git").exists():
        return
    run_git(root, "add", "-A")
    run_git(
        root,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-m",
        "layout",
    )
    run_git(root, "branch", "-M", "main")


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


def status_json(root: Path) -> dict[str, object]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "status", "--json"]) == 0
    return json.loads(buffer.getvalue())


def _item(key: str, status: str = "draft") -> ItemStatus:
    return ItemStatus(
        key=key,
        status=status,  # type: ignore[arg-type]
        body=Path(f"documents/x/{key}.md"),
        sidecar=Path(f"documents/x/{key}.json"),
        deprecated=False,
        superseded=False,
        draft=True,
    )


# --------------------------------------------------------------------------
# WIP header (spec §8, §13.12)
# --------------------------------------------------------------------------


def test_wip_header_format_matches_spec_example() -> None:
    wip = WipState(
        drafts=(_item("a"), _item("b"), _item("c")),
        modified=(_item("d", "active"),),
    )
    assert wip_header(wip) == "WIP: yes (3 drafts, 1 modified)"


def test_wip_header_no() -> None:
    assert wip_header(WipState()) == "WIP: no"


def test_wip_header_singular_draft() -> None:
    wip = WipState(drafts=(_item("a"),))
    assert wip_header(wip) == "WIP: yes (1 draft)"


def test_status_wip_header_live(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "goal")
    baseline_commit(tmp_repo)
    workspace = Workspace.open(tmp_repo)
    goal = create_document(workspace, type="goal", title="Goal")
    body = next((tmp_repo / "documents").rglob(f"{goal.id}.md"))
    body.write_text(body.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "status"]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert "modified" in first
    if (tmp_repo / ".git").exists():
        assert first == "WIP: yes (1 draft, 1 modified, 2 uncommitted)"
    else:
        assert first == "WIP: yes (1 modified)"


# --------------------------------------------------------------------------
# report sections (spec §13.12)
# --------------------------------------------------------------------------


def test_status_sections_and_counts(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--repo", str(sample_graph.root), "status"]) == 0
    out = capsys.readouterr().out
    assert "documents:" in out
    assert "superseded" in out
    assert "deprecated" in out
    assert "links:" in out
    assert "conflicts: 1 open" in out
    assert "deprecated templates:" in out
    assert "change requests:" in out
    assert "hook:" in out
    assert "degraded mode:" in out


def test_status_lists_drafts_with_paths(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "goal")
    baseline_commit(tmp_repo)
    workspace = Workspace.open(tmp_repo)
    goal = create_document(workspace, type="goal", title="Draft")
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "status"]) == 0
    out = capsys.readouterr().out
    if (tmp_repo / ".git").exists():
        assert "drafts:" in out
        assert goal.id in out
        assert ".md" in out


def test_status_modified_unbumped_listed(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "goal")
    workspace = Workspace.open(tmp_repo)
    goal = create_document(workspace, type="goal", title="Goal")
    body = next((tmp_repo / "documents").rglob(f"{goal.id}.md"))
    body.write_text(body.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "status"]) == 0
    out = capsys.readouterr().out
    assert "modified, unbumped:" in out
    assert goal.id in out
    assert "WIP: yes" in out.splitlines()[0]


def test_status_pending_initial_version_note(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AGENT_READINESS §3.3: uncommitted edited ``v1`` documents with inbound
    links are listed under a *pending initial version* note — no new status
    is invented (they stay ``draft``), and grace items without inbound links
    or without unbumped modifications are not listed."""
    if not (tmp_repo / ".git").exists():
        pytest.skip("the grace period is a git-mode behaviour")
    add_template(tmp_repo, "goal")
    baseline_commit(tmp_repo)
    workspace = Workspace.open(tmp_repo)
    target = create_document(workspace, type="goal", title="Target")
    # The inbound link: `source` points at `target` but nothing points at
    # `source`, so only `target` can appear in the note.
    create_document(
        workspace, type="goal", title="Source", links=[("relates-to", target.id)]
    )
    # In grace with an inbound link, but its stored hash matches the file:
    # the initial version is not pending, so it is not listed.
    untouched = create_document(workspace, type="goal", title="Untouched")
    create_document(
        workspace,
        type="goal",
        title="Other linker",
        links=[("relates-to", untouched.id)],
    )
    body = next((tmp_repo / "documents").rglob(f"{target.id}.md"))
    body.write_text(body.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "status"]) == 0
    out = capsys.readouterr().out
    note_lines = [
        line for line in out.splitlines() if line.startswith("pending initial version")
    ]
    assert note_lines == [
        f"pending initial version (v1 with inbound links): {target.id}"
    ]
    payload = status_json(tmp_repo)
    assert payload["pending_initial_version"] == [target.id]


def test_status_always_exits_zero_with_errors(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "goal")
    workspace = Workspace.open(tmp_repo)
    goal = create_document(workspace, type="goal", title="Goal")
    sidecar = next((tmp_repo / "documents").rglob(f"{goal.id}.json"))
    sidecar.write_text("{not json", encoding="utf-8")
    assert main(["--repo", str(tmp_repo), "status"]) == 0
    assert "E-SIDECAR-INVALID" in capsys.readouterr().out


def test_status_json_payload(sample_graph: SampleGraph) -> None:
    payload = status_json(sample_graph.root)
    wip = payload["wip"]
    assert isinstance(wip, dict)
    assert wip["header"].startswith("WIP: ")
    assert isinstance(payload["documents"], dict)
    links = payload["links"]
    assert isinstance(links, dict)
    assert payload["conflicts"] == [["RE-000002", "RE-00000A"]]
    hook = payload["hook"]
    assert set(hook) == {"installed", "up_to_date"}
    assert payload["degraded"] is ((sample_graph.root / ".git").exists() is False)
