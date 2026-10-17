"""Tests for ``gregraph link``/``unlink``/``link refresh``/``set`` (spec
§13.3–§13.6).

Flag-driven and interactive (type-filtered pickers, cycle candidates
precomputed and excluded), link refusals exit 4, duplicates and missing edges
are no-op notices (exit 0), ``link --help`` prints the §6.1 edge guidelines,
``link refresh`` selectors with ``--follow``/``--dry-run`` (stale re-pointing
interactive or reported), and ``set`` key/value refusals. CLI tests invoke
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

from gregraph.cli.commands.link import _target_rows
from gregraph.cli.main import main
from gregraph.core.models import Document
from gregraph.core.operations import (
    create_document,
    deprecate,
    link,
    supersede,
)
from gregraph.core.storage import read_sidecar, write_body
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import SampleGraph


class FakeTTY(io.StringIO):
    """Scripted stdin that reports itself as a terminal."""

    def isatty(self) -> bool:  # noqa: D102
        return True


def add_template(root: Path, name: str) -> None:
    """Write one simple template version into the repository (spec §5.5)."""
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


def read_doc(root: Path, doc_id: str) -> Document:
    return read_sidecar(next((root / "documents").rglob(f"{doc_id}.json")), Document)


# --------------------------------------------------------------------------
# link (spec §13.3)
# --------------------------------------------------------------------------


def test_link_creates_edge_with_target_version(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    design = sample_graph.ids["design"]
    assert (
        main(["--repo", str(root), "link", story, "depends-on", design, "--no-input"])
        == 0
    )
    links = [
        (link.type, link.target, link.target_version)
        for link in read_doc(root, story).links
    ]
    assert ("depends-on", design, 1) in links


def test_link_duplicate_is_noop_notice(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    assert (
        main(["--repo", str(root), "link", story, "refines", feature, "--no-input"])
        == 0
    )
    assert "already exists" in capsys.readouterr().out


def test_link_cycle_refused_exits_4(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    story = sample_graph.ids["story"]
    assert (
        main(["--repo", str(root), "link", goal, "refines", story, "--no-input"]) == 4
    )
    assert "E-CYCLE" in capsys.readouterr().err


def test_link_edge_rule_refused_exits_4(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    test = sample_graph.ids["test"]
    goal = sample_graph.ids["goal"]
    assert main(["--repo", str(root), "link", test, "refines", goal, "--no-input"]) == 4
    assert "E-EDGE-RULE" in capsys.readouterr().err


def test_link_superseded_target_refused_exits_4(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    feature = sample_graph.ids["feature"]
    story_old = sample_graph.ids["story_old"]
    argv = ["--repo", str(root), "link", feature, "depends-on", story_old, "--no-input"]
    assert main(argv) == 4
    assert "E-TARGET-SUPERSEDED" in capsys.readouterr().err


def test_link_unknown_source_refused_exits_4(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    assert main(["--repo", str(root), "link", "RE-NOSUCH", "refines", goal]) == 4
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_link_help_prints_edge_guidelines(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["link", "--help"])
    assert excinfo.value.code == 0
    text = capsys.readouterr().out
    assert "edge guidelines:" in text
    assert "refines" in text
    assert "derives-from" in text
    assert "depends-on" in text
    assert "constrains" in text
    assert "Never model quality attributes as children" in text
    assert "A design node never refines a requirement" in text
    assert "relates-to is the last resort" in text


def test_link_no_input_partial_args_is_usage_error(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    assert main(["--repo", str(root), "link", story, "refines", "--no-input"]) == 2


# --------------------------------------------------------------------------
# link interactive flow (scripted stdin)
# --------------------------------------------------------------------------


def test_link_interactive_flow_creates_edge(
    sample_graph: SampleGraph, monkeypatch, capsys
) -> None:
    root = sample_graph.root
    orphan = sample_graph.ids["orphan"]
    goal = sample_graph.ids["goal"]
    monkeypatch.setattr("sys.stdin", FakeTTY(f"{orphan}\nrelates-to\n{goal}\n"))
    assert main(["--repo", str(root), "link"]) == 0
    links = [(link.type, link.target) for link in read_doc(root, orphan).links]
    assert ("relates-to", goal) in links
    assert "linked" in capsys.readouterr().out


def test_link_target_picker_excludes_cycles_and_dead_nodes(
    sample_graph: SampleGraph,
) -> None:
    workspace = Workspace.open(sample_graph.root)
    goal = sample_graph.ids["goal"]
    rows = _target_rows(workspace, goal, "refines")
    keys = {row.key for row in rows}
    assert sample_graph.ids["compliance"] in keys
    assert sample_graph.ids["story"] not in keys  # reaches goal → cycle
    assert sample_graph.ids["epic"] not in keys
    assert sample_graph.ids["story_old"] not in keys  # superseded
    assert sample_graph.ids["stale_note"] not in keys  # deprecated


def test_link_interactive_cancel_is_usage_error(
    sample_graph: SampleGraph, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdin", FakeTTY("q\n"))
    assert main(["--repo", str(sample_graph.root), "link"]) == 2


# --------------------------------------------------------------------------
# link --candidates (AGENT_READINESS §4.3, AGENT-023)
# --------------------------------------------------------------------------


def candidates_json(root: Path, *extra: str) -> dict[str, object]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "link", "--candidates", *extra]) == 0
    return json.loads(buffer.getvalue())


def test_link_candidates_json_payload(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]  # kind: requirement
    payload = candidates_json(root, story, "--json")
    assert payload["source"] == story
    assert payload["source_kind"] == "requirement"
    allowed = payload["allowed_edge_types"]
    assert isinstance(allowed, list)
    # requirement sources may use everything except satisfies/verifies
    assert set(allowed) == {
        "refines",
        "derives-from",
        "depends-on",
        "constrains",
        "supersedes",
        "conflicts-with",
        "relates-to",
    }
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    keys = [(c["type"], c["target"]) for c in candidates]
    assert keys == sorted(keys)  # sorted by (type, target)
    entry = next(
        c
        for c in candidates
        if c["target"] == sample_graph.ids["fr"] and c["type"] == "refines"
    )
    assert entry["type"] == "refines"
    assert entry["target_title"] == "Pipeline rejects infected files"
    assert entry["target_type"] == "functional-requirement"
    assert entry["target_kind"] == "requirement"


def test_link_candidates_type_filter(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    payload = candidates_json(root, story, "--type", "refines", "--json")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    assert {c["type"] for c in candidates} == {"refines"}


def test_link_candidates_exclude_cycles_and_dead(tmp_repo: Path) -> None:
    # AGENT-403: cycle candidates and deprecated/superseded targets are
    # excluded; live kind-rule-admissible targets remain.
    add_template(tmp_repo, "feature")
    workspace = Workspace.open(tmp_repo)
    source = create_document(workspace, type="feature", title="Source")
    live = create_document(workspace, type="feature", title="Live target")
    cycling = create_document(workspace, type="feature", title="Cycle maker")
    deprecated = create_document(workspace, type="feature", title="Deprecated")
    link(workspace, source=cycling.id, link_type="refines", target=source.id)
    deprecate(workspace, doc_id=deprecated.id, reason="obsolete")
    payload = candidates_json(tmp_repo, source.id, "--type", "refines", "--json")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    assert [c["target"] for c in candidates] == [live.id]


def test_link_candidates_unknown_source_refused_exits_4(
    sample_graph: SampleGraph, capsys
) -> None:
    assert (
        main(["--repo", str(sample_graph.root), "link", "--candidates", "RE-NOSUCH"])
        == 4
    )
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_link_candidates_with_target_position_is_usage_error(
    sample_graph: SampleGraph,
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    assert (
        main(["--repo", str(root), "link", "--candidates", story, "refines", feature])
        == 2
    )


def test_link_candidates_positional_type_is_usage_error(
    sample_graph: SampleGraph,
) -> None:
    """§4.3: ``--candidates`` takes ``<SOURCE_ID> [--type EDGE_TYPE]`` only.

    A positional ``TYPE`` is refused; ``--type EDGE_TYPE`` is the only filter.
    """
    root = sample_graph.root
    story = sample_graph.ids["story"]
    assert main(["--repo", str(root), "link", "--candidates", story, "refines"]) == 2
    payload = candidates_json(root, story, "--type", "refines", "--json")
    assert payload["source"] == story


def test_link_candidates_without_source_is_usage_error(
    sample_graph: SampleGraph,
) -> None:
    assert main(["--repo", str(sample_graph.root), "link", "--candidates"]) == 2


def test_link_candidates_unknown_edge_type_is_usage_error(
    sample_graph: SampleGraph,
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    assert (
        main(["--repo", str(root), "link", "--candidates", story, "--type", "bogus"])
        == 2
    )


def test_link_type_without_candidates_is_usage_error(
    sample_graph: SampleGraph,
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    assert (
        main(["--repo", str(root), "link", story, "refines", feature, "--type", "x"])
        == 2
    )


def test_link_candidates_human_mode_lists_rows(
    sample_graph: SampleGraph, capsys
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    assert main(["--repo", str(root), "link", "--candidates", story, "--no-input"]) == 0
    out = capsys.readouterr().out
    assert "refines" in out
    assert sample_graph.ids["feature"] in out


def test_link_candidates_human_mode_no_candidates(tmp_repo: Path, capsys) -> None:
    add_template(tmp_repo, "feature")
    workspace = Workspace.open(tmp_repo)
    created = create_document(workspace, type="feature", title="Only")
    # kind rule: a requirement source may not satisfies/verifies → no rows
    argv = [
        "--repo",
        str(tmp_repo),
        "link",
        "--candidates",
        created.id,
        "--type",
        "verifies",
    ]
    assert main(argv) == 0
    assert "no candidates" in capsys.readouterr().out


# --------------------------------------------------------------------------
# link --json (AGENT_READINESS §2.4.2)
# --------------------------------------------------------------------------


def link_json(root: Path, *extra: str) -> dict[str, object]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "link", *extra]) == 0
    return json.loads(buffer.getvalue())


def test_link_json_created_payload(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    design = sample_graph.ids["design"]
    payload = link_json(root, story, "depends-on", design, "--no-input", "--json")
    assert payload == {
        "source": story,
        "type": "depends-on",
        "target": design,
        "created": True,
        "target_version": 1,
        "notice": None,
        "findings": [],
        "notices": [],
    }


def test_link_json_duplicate_is_noop_created_false(
    sample_graph: SampleGraph,
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    # story already refines feature in the sample graph → duplicate no-op
    payload = link_json(root, story, "refines", feature, "--no-input", "--json")
    assert payload["created"] is False
    assert "already exists" in str(payload["notice"])
    assert payload["target_version"] is None
    assert any("already exists" in notice for notice in payload["notices"])


# --------------------------------------------------------------------------
# unlink (spec §13.4)
# --------------------------------------------------------------------------


def test_unlink_removes_directed_edge(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    assert (
        main(["--repo", str(root), "unlink", story, "refines", feature, "--no-input"])
        == 0
    )
    assert not any(
        link.type == "refines" and link.target == feature
        for link in read_doc(root, story).links
    )


def test_unlink_symmetric_either_endpoint(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    compliance = sample_graph.ids["compliance"]
    design = sample_graph.ids["design"]
    assert (
        main(
            [
                "--repo",
                str(root),
                "unlink",
                design,
                "conflicts-with",
                compliance,
                "--no-input",
            ]
        )
        == 0
    )
    assert not any(
        link.type == "conflicts-with" and link.target == design
        for link in read_doc(root, compliance).links
    )


def test_unlink_missing_edge_is_noop(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    goal = sample_graph.ids["goal"]
    assert (
        main(["--repo", str(root), "unlink", story, "depends-on", goal, "--no-input"])
        == 0
    )
    assert "no edge" in capsys.readouterr().err


# --------------------------------------------------------------------------
# link refresh (spec §13.5)
# --------------------------------------------------------------------------


def _git_commit_all(root: Path, message: str = "initial") -> None:
    """Commit everything in the fixture (test scaffolding; spec §17)."""
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test Author",
            "-c",
            "user.email=test.author@example.org",
            "commit",
            "-m",
            message,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_refresh_to_updates_inbound(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    feature = sample_graph.ids["feature"]
    story = sample_graph.ids["story"]
    if (root / ".git").exists():
        # Commit the initial state first: an *uncommitted* v1 document is in
        # the grace period (§3.3) where the effective version stays 1, so the
        # edit below would not bump. Committed, it is a normal unbumped
        # modification and refresh records the pending v2.
        _git_commit_all(root)
    body = root / "documents" / "feature" / f"{feature}.md"
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    assert main(["--repo", str(root), "link", "refresh", "--to", feature]) == 0
    refreshed = [
        (link.type, link.target, link.target_version)
        for link in read_doc(root, story).links
        if link.target == feature
    ]
    assert refreshed == [("refines", feature, 2)]


def test_refresh_uncommitted_v1_target_keeps_version_1(
    sample_graph: SampleGraph,
) -> None:
    # Grace period (AGENT_READINESS §3.3, AGENT-012): the uncommitted v1
    # target's effective version is 1, so refresh keeps target_version 1.
    if not (sample_graph.root / ".git").exists():
        pytest.skip("the v1 grace period applies in git mode only")
    root = sample_graph.root
    feature = sample_graph.ids["feature"]
    story = sample_graph.ids["story"]
    body = root / "documents" / "feature" / f"{feature}.md"
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    assert main(["--repo", str(root), "link", "refresh", "--to", feature]) == 0
    refreshed = [
        (link.type, link.target, link.target_version)
        for link in read_doc(root, story).links
        if link.target == feature
    ]
    assert refreshed == [("refines", feature, 1)]


def test_refresh_dry_run_writes_nothing(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    feature = sample_graph.ids["feature"]
    story = sample_graph.ids["story"]
    body = root / "documents" / "feature" / f"{feature}.md"
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    assert (
        main(["--repo", str(root), "link", "refresh", "--to", feature, "--dry-run"])
        == 0
    )
    assert read_doc(root, story).links[0].target_version == 1


def test_refresh_no_selector_no_input_is_usage_error(sample_graph: SampleGraph) -> None:
    argv = ["--repo", str(sample_graph.root), "link", "refresh", "--no-input"]
    assert main(argv) == 2


def _stale_setup(root: Path) -> tuple[str, str, str]:
    """``old`` superseded by ``successor``; ``x`` refines ``old`` (now stale)."""
    add_template(root, "user-story")
    workspace = Workspace.open(root)
    old = create_document(workspace, type="user-story", title="Old")
    x = create_document(
        workspace, type="user-story", title="X", links=[("refines", old.id)]
    )
    successor = supersede(workspace, targets=[old.id], title="Successor")
    return old.id, x.id, successor.id


def test_refresh_follow_repoints_stale(tmp_repo: Path) -> None:
    old_id, x_id, successor_id = _stale_setup(tmp_repo)
    assert (
        main(
            [
                "--repo",
                str(tmp_repo),
                "link",
                "refresh",
                x_id,
                "refines",
                old_id,
                "--follow",
            ]
        )
        == 0
    )
    links = [(link.type, link.target) for link in read_doc(tmp_repo, x_id).links]
    assert links == [("refines", successor_id)]


def test_refresh_stale_reported_without_follow(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old_id, x_id, _ = _stale_setup(tmp_repo)
    assert (
        main(
            [
                "--repo",
                str(tmp_repo),
                "link",
                "refresh",
                x_id,
                "refines",
                old_id,
                "--no-input",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "stale:" in out
    links = [(link.type, link.target) for link in read_doc(tmp_repo, x_id).links]
    assert links == [("refines", old_id)]


def test_refresh_stale_interactive_repoint(tmp_repo: Path, monkeypatch, capsys) -> None:
    old_id, x_id, successor_id = _stale_setup(tmp_repo)
    monkeypatch.setattr("sys.stdin", FakeTTY(f"{successor_id}\n"))
    assert (
        main(["--repo", str(tmp_repo), "link", "refresh", x_id, "refines", old_id]) == 0
    )
    out = capsys.readouterr().out
    assert "re-pointed" in out
    links = [(link.type, link.target) for link in read_doc(tmp_repo, x_id).links]
    assert links == [("refines", successor_id)]


def test_refresh_follow_fork_refused_exits_4(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "user-story")
    workspace = Workspace.open(tmp_repo)
    old = create_document(workspace, type="user-story", title="Old")
    x = create_document(
        workspace, type="user-story", title="X", links=[("refines", old.id)]
    )
    supersede(workspace, targets=[old.id], title="First")
    supersede(workspace, targets=[old.id], title="Second")
    assert (
        main(
            [
                "--repo",
                str(tmp_repo),
                "link",
                "refresh",
                x.id,
                "refines",
                old.id,
                "--follow",
            ]
        )
        == 4
    )
    assert "E-SUPERSEDE-FORK" in capsys.readouterr().err


# --------------------------------------------------------------------------
# set (spec §13.6)
# --------------------------------------------------------------------------


def test_set_tags_and_extra(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    assert main(["--repo", str(root), "set", goal, "tags=a,b", "--no-input"]) == 0
    assert main(["--repo", str(root), "set", goal, "tags+=c", "--no-input"]) == 0
    assert main(["--repo", str(root), "set", goal, "tags-=a", "--no-input"]) == 0
    assert main(["--repo", str(root), "set", goal, "extra.owner=me", "--no-input"]) == 0
    document = read_doc(root, goal)
    assert document.tags == ["b", "c"]
    assert document.extra == {"owner": "me"}


def test_set_unknown_key_refused_exits_4(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    assert main(["--repo", str(root), "set", goal, "title=X", "--no-input"]) == 4
    captured = capsys.readouterr().err
    assert "E-SET-KEY" in captured
    assert "gregraph edit" in captured


def test_set_no_input_missing_args_is_usage_error(sample_graph: SampleGraph) -> None:
    assert main(["--repo", str(sample_graph.root), "set", "--no-input"]) == 2
    goal = sample_graph.ids["goal"]
    assert main(["--repo", str(sample_graph.root), "set", goal, "--no-input"]) == 2
