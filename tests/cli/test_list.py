"""Tests for ``gregraph list`` (spec §13.10): table, filters, JSON.

Columns ID, type, status, version, title; filter flags (``--type/--kind/
--status/--tag/--roots/--orphans/--outdated/--stale/--deprecated-templates``),
``--sort``, and ``--json`` (sidecars plus derived fields). CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``sample_graph`` fixture.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from gregraph.cli.main import main
from gregraph.core.models import Document
from gregraph.core.operations import deprecate, set_fields
from gregraph.core.storage import read_sidecar, write_sidecar
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import SampleGraph


def list_json(root: Path, *extra: str) -> list[dict[str, object]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "list", "--json", *extra]) == 0
    return json.loads(buffer.getvalue())


def test_list_table_lists_every_document(sample_graph: SampleGraph, capsys) -> None:
    assert main(["--repo", str(sample_graph.root), "list"]) == 0
    out = capsys.readouterr().out
    assert "ID" in out.splitlines()[0]
    assert "TYPE" in out.splitlines()[0]
    assert "STATUS" in out.splitlines()[0]
    assert "VERSION" in out.splitlines()[0]
    assert "TITLE" in out.splitlines()[0]
    for doc_id in sample_graph.ids.values():
        assert doc_id in out
    assert "Upload from the desktop" in out
    assert "deprecated" in out
    assert "superseded" in out


def test_list_json_sidecars_plus_derived(sample_graph: SampleGraph) -> None:
    rows = list_json(sample_graph.root)
    assert len(rows) == len(sample_graph.ids)
    by_id = {row["id"]: row for row in rows}
    story = by_id[sample_graph.ids["story"]]
    assert story["schema"] == 1
    assert story["type"] == "user-story"
    assert story["kind"] == "requirement"
    assert story["status"] in {"active", "draft", "unknown"}
    assert by_id[sample_graph.ids["stale_note"]]["status"] == "deprecated"
    assert by_id[sample_graph.ids["story_old"]]["status"] == "superseded"
    assert "links" in story
    assert "body_hash" in story


def test_list_filters_by_type_and_kind(sample_graph: SampleGraph, capsys) -> None:
    root = sample_graph.root
    assert main(["--repo", str(root), "list", "--type", "user-story"]) == 0
    out = capsys.readouterr().out
    for role in ("story", "story_old", "scan_story"):
        assert sample_graph.ids[role] in out
    assert sample_graph.ids["goal"] not in out

    assert main(["--repo", str(root), "list", "--kind", "goal"]) == 0
    out = capsys.readouterr().out
    for role in ("goal", "compliance", "epic"):
        assert sample_graph.ids[role] in out
    assert sample_graph.ids["feature"] not in out


def test_list_filters_combine_with_and(sample_graph: SampleGraph) -> None:
    rows = list_json(sample_graph.root, "--type", "goal", "--kind", "goal")
    assert {row["id"] for row in rows} == {
        sample_graph.ids["goal"],
        sample_graph.ids["compliance"],
    }


def test_list_status_filter(sample_graph: SampleGraph) -> None:
    rows = list_json(sample_graph.root, "--status", "deprecated")
    assert {row["id"] for row in rows} == {sample_graph.ids["stale_note"]}


def test_list_tag_filter_is_any_of(sample_graph: SampleGraph) -> None:
    workspace = Workspace.open(sample_graph.root)
    set_fields(
        workspace,
        doc_id=sample_graph.ids["goal"],
        assignments=["tags=alpha,beta"],
    )
    set_fields(
        workspace,
        doc_id=sample_graph.ids["feature"],
        assignments=["tags=beta"],
    )
    rows = list_json(sample_graph.root, "--tag", "alpha", "--tag", "beta")
    assert {row["id"] for row in rows} == {
        sample_graph.ids["goal"],
        sample_graph.ids["feature"],
    }
    rows = list_json(sample_graph.root, "--tag", "alpha")
    assert {row["id"] for row in rows} == {sample_graph.ids["goal"]}


def test_list_roots_and_orphans(sample_graph: SampleGraph) -> None:
    roots = {row["id"] for row in list_json(sample_graph.root, "--roots")}
    assert sample_graph.ids["goal"] in roots
    assert sample_graph.ids["nfr"] in roots
    assert sample_graph.ids["feature"] not in roots
    assert sample_graph.ids["story"] not in roots

    orphans = {row["id"] for row in list_json(sample_graph.root, "--orphans")}
    assert orphans == {sample_graph.ids["orphan"]}


def test_list_outdated_and_stale(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    goal_sidecar = root / "documents" / "goal" / f"{sample_graph.ids['goal']}.json"
    document = read_sidecar(goal_sidecar, Document)
    write_sidecar(
        goal_sidecar, document.model_copy(update={"version": document.version + 1})
    )
    outdated = {row["id"] for row in list_json(root, "--outdated")}
    assert sample_graph.ids["epic"] in outdated
    assert sample_graph.ids["stakeholder"] in outdated
    assert sample_graph.ids["story"] not in outdated

    workspace = Workspace.open(root)
    deprecate(workspace, doc_id=sample_graph.ids["goal"], reason="obsolete")
    stale = {row["id"] for row in list_json(root, "--stale")}
    assert sample_graph.ids["epic"] in stale
    assert sample_graph.ids["stakeholder"] in stale


def test_list_deprecated_templates_filter(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    directory = root / ".gregraph" / "templates" / "user-story" / "v1"
    directory.mkdir(parents=True)
    (directory / "template.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "name": "user-story",
                "version": 1,
                "description": "old",
                "deprecated": True,
                "breaking": False,
                "sections": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "template.md").write_text("# {{ title }}\n", encoding="utf-8")
    rows = {row["id"] for row in list_json(root, "--deprecated-templates")}
    assert rows == {
        sample_graph.ids["story"],
        sample_graph.ids["story_old"],
        sample_graph.ids["scan_story"],
    }


def test_list_sort_keys(sample_graph: SampleGraph) -> None:
    rows = list_json(sample_graph.root, "--sort", "title")
    titles = [row["title"] for row in rows]
    assert titles == sorted(titles)
    rows = list_json(sample_graph.root, "--sort", "version")
    versions = [row["version"] for row in rows]
    assert versions == sorted(versions)
    rows = list_json(sample_graph.root)
    ids = [row["id"] for row in rows]
    assert ids == sorted(ids)


def test_list_empty_filters_yield_empty_table(
    sample_graph: SampleGraph, capsys
) -> None:
    assert main(["--repo", str(sample_graph.root), "list", "--status", "nope"]) == 0
    out = capsys.readouterr().out
    assert sample_graph.ids["goal"] not in out
