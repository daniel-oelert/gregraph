"""Tests for ``gregraph context`` (AGENT_READINESS §6.1, AGENT-027/028/404).

One-call bundle: ``--json`` targets (show payloads + bodies + sections),
neighbours with via/direction/depth/freshness, glossary terms and findings;
``--depth``/``--direction``/``--no-include-terms``; the human mode's single
Markdown document; and the ``E-ID-UNKNOWN`` refusal for unknown IDs. CLI
tests invoke ``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from test_hook import install_templates

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.operations import create_document, link, term_add
from gregraph.core.storage import config_path, write_body
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import SampleGraph


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


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def context_json(root: Path, *extra: str) -> dict[str, object]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "context", *extra]) == 0
    return json.loads(buffer.getvalue())


def _chain(repo: Path) -> dict[str, str]:
    """A → B → C (``refines``) with a glossary term mentioned in A's body."""
    workspace = Workspace.open(repo)
    a = create_document(workspace, type="feature", title="Alpha")
    b = create_document(workspace, type="feature", title="Beta")
    c = create_document(workspace, type="feature", title="Gamma")
    link(workspace, source=a.id, link_type="refines", target=b.id)
    link(workspace, source=b.id, link_type="refines", target=c.id)
    write_body(
        repo / "documents" / "feature" / f"{a.id}.md",
        f"# Alpha\n\n## Story\n\nUses the knowledge base for [[{b.id}]].\n",
    )
    term_add(workspace, term="Knowledge base", aliases=["KB"])
    workspace.reload()
    return {"a": a.id, "b": b.id, "c": c.id}


def test_context_json_bundle_shape(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["a"], "--json")
    assert set(payload) == {
        "requested",
        "depth",
        "direction",
        "targets",
        "neighbors",
        "terms",
        "findings",
    }
    assert payload["requested"] == [ids["a"]]
    assert payload["depth"] == 1
    assert payload["direction"] == "both"


def test_context_target_is_show_payload_plus_body_and_sections(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["a"], "--json")
    targets = payload["targets"]
    assert isinstance(targets, list)
    assert len(targets) == 1
    target = targets[0]
    assert target["id"] == ids["a"]
    assert target["title"] == "Alpha"
    assert "Uses the knowledge base" in str(target["body"])
    sections = target["sections"]
    assert isinstance(sections, list)
    assert [s["heading"] for s in sections] == ["Story"]
    outbound = target["outbound"]
    assert any(view["target"] == ids["b"] for view in outbound)
    story_section = next(s for s in sections if s["heading"] == "Story")
    assert "Uses the knowledge base" in str(story_section["content"])


def test_context_neighbors_carry_edge_direction_depth_freshness(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["a"], "--json")
    neighbors = payload["neighbors"]
    assert isinstance(neighbors, list)
    assert [n["id"] for n in neighbors] == [ids["b"]]
    neighbour = neighbors[0]
    assert neighbour["via"] == {
        "source": ids["a"],
        "type": "refines",
        "target": ids["b"],
    }
    assert neighbour["direction"] == "downstream"
    assert neighbour["depth"] == 1
    assert neighbour["freshness"] == "fresh"
    assert neighbour["sidecar"]["id"] == ids["b"]
    assert "Beta" in str(neighbour["body"])


def test_context_terms_and_no_include_terms(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["a"], "--json")
    terms = payload["terms"]
    assert isinstance(terms, list)
    assert [t["slug"] for t in terms] == ["knowledge-base"]
    term = terms[0]
    assert term["term"] == "Knowledge base"
    assert term["aliases"] == ["KB"]
    assert "# Knowledge base" in str(term["body"])

    without = context_json(repo, ids["a"], "--no-include-terms", "--json")
    assert without["terms"] == []


def test_context_pending_outdated_neighbour_and_findings(repo: Path) -> None:
    # AGENT-404 shape: a 3-document chain, the middle document edited
    # unbumped; the neighbour is reached via the edge into it, so its
    # freshness is pending-outdated and the findings carry the pending state.
    # The initial state is committed first (git mode): an uncommitted v1
    # document is in the grace period where populating it is never "pending".
    ids = _chain(repo)
    if (repo / ".git").exists():
        _git_commit_all(repo)
    body = repo / "documents" / "feature" / f"{ids['b']}.md"
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    payload = context_json(repo, ids["a"], ids["c"], "--json")
    assert payload["requested"] == [ids["a"], ids["c"]]
    targets = payload["targets"]
    assert isinstance(targets, list)
    assert [t["id"] for t in targets] == [ids["a"], ids["c"]]
    assert all("body" in t for t in targets)
    neighbors = payload["neighbors"]
    assert isinstance(neighbors, list)
    assert [n["id"] for n in neighbors] == [ids["b"]]
    neighbour = neighbors[0]
    assert neighbour["freshness"] == "pending-outdated"
    assert neighbour["depth"] == 1
    findings = payload["findings"]
    assert isinstance(findings, list)
    assert any(f["code"] == "W-LINK-PENDING" for f in findings)


def test_context_multiple_targets_deduplicated(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["a"], ids["a"].lower(), "--json")
    assert payload["requested"] == [ids["a"]]


def test_context_depth_zero_has_no_neighbours(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["a"], "--depth", "0", "--json")
    assert payload["depth"] == 0
    assert payload["neighbors"] == []


def test_context_depth_two_reaches_grandparent(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["a"], "--depth", "2", "--json")
    neighbors = payload["neighbors"]
    assert isinstance(neighbors, list)
    assert [n["id"] for n in neighbors] == [ids["b"], ids["c"]]
    assert [n["depth"] for n in neighbors] == [1, 2]


def test_context_direction_upstream_only(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["b"], "--direction", "upstream", "--json")
    neighbors = payload["neighbors"]
    assert isinstance(neighbors, list)
    assert [n["id"] for n in neighbors] == [ids["a"]]
    assert all(n["direction"] == "upstream" for n in neighbors)


def test_context_direction_downstream_only(repo: Path) -> None:
    ids = _chain(repo)
    payload = context_json(repo, ids["b"], "--direction", "downstream", "--json")
    neighbors = payload["neighbors"]
    assert isinstance(neighbors, list)
    assert [n["id"] for n in neighbors] == [ids["c"]]


def test_context_cr_target_uses_cr_payload(repo: Path) -> None:
    from gregraph.core.operations import cr_new

    ids = _chain(repo)
    workspace = Workspace.open(repo)
    created = cr_new(
        workspace, title="Switch to shared storage", scope=[f"{ids['a']}:modify"]
    )
    payload = context_json(repo, created.id, "--json")
    targets = payload["targets"]
    assert isinstance(targets, list)
    target = targets[0]
    assert target["kind"] == "change-request"
    assert target["title"] == "Switch to shared storage"
    assert "body" in target
    neighbors = payload["neighbors"]
    assert isinstance(neighbors, list)
    # the CR's scope targets (and their downstream impact set) are its
    # downstream neighbours, reached via the synthetic "scope" edge
    assert {n["id"] for n in neighbors} == {ids["a"], ids["b"]}
    scope_neighbour = next(n for n in neighbors if n["id"] == ids["a"])
    assert scope_neighbour["via"]["type"] == "scope"
    assert scope_neighbour["direction"] == "downstream"


def test_context_unknown_id_refused_exits_4(repo: Path, capsys) -> None:
    _chain(repo)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        assert main(["--repo", str(repo), "context", "RE-STORY-ZZZZZZ", "--json"]) == 4
    envelope = json.loads(buffer.getvalue())
    assert envelope["error"]["code"] == "E-ID-UNKNOWN"
    assert capsys.readouterr().err == ""


def test_context_negative_depth_is_usage_error(repo: Path) -> None:
    ids = _chain(repo)
    assert main(["--repo", str(repo), "context", ids["a"], "--depth", "-1"]) == 2


def test_context_human_mode_markdown(repo: Path, capsys) -> None:
    ids = _chain(repo)
    assert main(["--repo", str(repo), "context", ids["a"]]) == 0
    out = capsys.readouterr().out
    assert f"# {ids['a']} — Alpha" in out
    assert "status:" in out
    assert "Uses the knowledge base" in out
    assert "outbound:" in out
    assert f"- refines → {ids['b']}" in out
    assert "## Neighbours" in out
    assert f"### {ids['b']} — Beta (downstream, depth 1, fresh)" in out
    assert "## Glossary" in out
    assert "### Knowledge base (knowledge-base) (aliases: KB)" in out
    assert "\x1b[" not in out  # no ANSI colour codes


def test_context_human_mode_separator_between_targets(repo: Path, capsys) -> None:
    ids = _chain(repo)
    assert main(["--repo", str(repo), "context", ids["a"], ids["c"]]) == 0
    out = capsys.readouterr().out
    assert "\n\n---\n\n" in out
    assert f"# {ids['a']} — Alpha" in out
    assert f"# {ids['c']} — Gamma" in out


def test_context_human_mode_no_neighbours_section_at_depth_zero(
    repo: Path, capsys
) -> None:
    ids = _chain(repo)
    assert main(["--repo", str(repo), "context", ids["a"], "--depth", "0"]) == 0
    out = capsys.readouterr().out
    assert "## Neighbours" not in out
    assert "## Glossary" in out


def test_context_human_mode_suppressed_under_json(repo: Path, capsys) -> None:
    ids = _chain(repo)
    buffer_out, buffer_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buffer_out), contextlib.redirect_stderr(buffer_err):
        assert main(["--repo", str(repo), "context", ids["a"], "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "## Neighbours" not in buffer_out.getvalue()


def test_context_sample_graph_bundle(sample_graph: SampleGraph) -> None:
    story = sample_graph.ids["story"]
    payload = context_json(sample_graph.root, story, "--json")
    targets = payload["targets"]
    assert isinstance(targets, list)
    assert targets[0]["id"] == story
    neighbors = payload["neighbors"]
    assert isinstance(neighbors, list)
    neighbour_ids = {n["id"] for n in neighbors}
    assert sample_graph.ids["feature"] in neighbour_ids  # downstream
    assert sample_graph.ids["fr"] in neighbour_ids  # upstream
    assert sample_graph.ids["test"] in neighbour_ids  # upstream
    assert sample_graph.ids["orphan"] not in neighbour_ids
