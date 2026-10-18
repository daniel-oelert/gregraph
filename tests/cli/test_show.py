"""Tests for ``gregraph show`` (spec §13.11): full document view.

Sidecar fields, derived status, outbound/inbound edges with freshness,
one-level upstream, ``--depth``-limited downstream tree, ``--body``, CR
delegation to ``cr show``, and ``--json``. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``sample_graph`` fixture.
"""

from __future__ import annotations

import contextlib
import io
import json
from importlib.resources import files as resource_files
from pathlib import Path
from typing import TYPE_CHECKING

from gregraph.cli.main import main
from gregraph.core.operations import cr_new

if TYPE_CHECKING:
    from conftest import SampleGraph


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:  # noqa: D102
        return True


def install_templates(root: Path, *names: str) -> None:
    """Copy shipped built-in templates into the repository (spec §5.5)."""
    source_root = resource_files("gregraph").joinpath("builtin_templates")
    for name in names:
        source = source_root.joinpath(name).joinpath("v1")
        target = root / ".gregraph" / "templates" / name / "v1"
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            (target / child.name).write_bytes(child.read_bytes())


def show_text(root: Path, *extra: str) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "show", *extra]) == 0
    return buffer.getvalue()


def show_json(root: Path, *extra: str) -> dict[str, object]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "show", "--json", *extra]) == 0
    return json.loads(buffer.getvalue())


def test_show_text_document_view(sample_graph: SampleGraph) -> None:
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    text = show_text(sample_graph.root, story)
    assert story in text
    assert "Upload from the desktop" in text
    assert "user-story (requirement)" in text
    assert "user-story/v1" in text
    assert f"refines  {feature}" in text
    assert "outbound:" in text
    assert "inbound:" in text
    assert "upstream:" in text
    assert "downstream:" in text
    assert sample_graph.ids["fr"] in text
    assert sample_graph.ids["test"] in text


def test_show_edges_carry_freshness(sample_graph: SampleGraph) -> None:
    story = sample_graph.ids["story"]
    text = show_text(sample_graph.root, story)
    assert "target_version 1/1  fresh" in text
    story_old = sample_graph.ids["story_old"]
    assert f"supersedes  {story_old}  target_version 1/1  stale" in text


def test_show_json_payload(sample_graph: SampleGraph) -> None:
    story = sample_graph.ids["story"]
    payload = show_json(sample_graph.root, story)
    assert payload["id"] == story
    assert payload["type"] == "user-story"
    assert payload["status"] in {"active", "draft", "unknown"}
    assert payload["kind"] == "requirement"
    outbound = payload["outbound"]
    assert isinstance(outbound, list)
    assert {item["type"] for item in outbound} == {"refines", "supersedes"}  # type: ignore[index]
    inbound = payload["inbound"]
    assert isinstance(inbound, list)
    assert {item["source"] for item in inbound} == {  # type: ignore[index]
        sample_graph.ids["fr"],
        sample_graph.ids["test"],
    }
    assert {"type": "refines", "target": sample_graph.ids["feature"]} in payload[
        "upstream"
    ]  # type: ignore[operator]
    downstream = {item["id"]: item["depth"] for item in payload["downstream"]}  # type: ignore[index]
    assert downstream == {
        sample_graph.ids["fr"]: 1,
        sample_graph.ids["test"]: 1,
    }
    assert payload["template_info"] == {  # type: ignore[operator]
        "description": None,
        "deprecated": None,
    }


def test_show_body_flag(sample_graph: SampleGraph) -> None:
    story = sample_graph.ids["story"]
    text = show_text(sample_graph.root, story, "--body")
    assert "# Upload from the desktop" in text
    assert "Sample body for Upload from the desktop." in text
    without = show_text(sample_graph.root, story)
    assert "Sample body for Upload from the desktop." not in without
    payload = show_json(sample_graph.root, story, "--body")
    assert "Sample body" in str(payload["body"])


def test_show_downstream_depth_limit(sample_graph: SampleGraph) -> None:
    feature = sample_graph.ids["feature"]
    text = show_text(sample_graph.root, feature, "--depth", "1")
    assert sample_graph.ids["story"] in text
    assert sample_graph.ids["scan_story"] in text
    assert sample_graph.ids["fr"] not in text
    assert sample_graph.ids["test"] not in text
    full = show_text(sample_graph.root, feature)
    assert sample_graph.ids["fr"] in full
    assert "(depth 2)" in full


def test_show_unknown_id_refused(sample_graph: SampleGraph, capsys) -> None:
    assert main(["--repo", str(sample_graph.root), "show", "RE-STORY-ZZZZZZ"]) == 4
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_show_missing_id_without_input_is_usage_error(
    sample_graph: SampleGraph,
) -> None:
    assert main(["--repo", str(sample_graph.root), "show", "--no-input"]) == 2


def test_show_negative_depth_is_usage_error(sample_graph: SampleGraph) -> None:
    assert (
        main(
            [
                "--repo",
                str(sample_graph.root),
                "show",
                sample_graph.ids["story"],
                "--depth",
                "-1",
            ]
        )
        == 2
    )


def test_show_picker_selects_by_number(
    sample_graph: SampleGraph, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("sys.stdin", FakeTTY("q\n"))
    assert main(["--repo", str(sample_graph.root), "show"]) == 2
    out = capsys.readouterr().out
    first_line = next(
        line for line in out.splitlines() if line.strip().startswith("1.")
    )
    first_id = first_line.split()[1]
    assert first_id in sample_graph.ids.values()
    monkeypatch.setattr("sys.stdin", FakeTTY("1\n"))
    assert main(["--repo", str(sample_graph.root), "show"]) == 0
    assert first_id in capsys.readouterr().out


def test_show_cr_delegates_to_cr_show(sample_graph: SampleGraph) -> None:
    install_templates(sample_graph.root, "change-request")
    created = cr_new(sample_graph.workspace, title="Switch to shared storage")
    text = show_text(sample_graph.root, created.id)
    assert created.id in text
    assert "Switch to shared storage" in text
    assert "effective" in text
    payload = show_json(sample_graph.root, created.id)
    assert payload["kind"] == "change-request"
    assert payload["title"] == "Switch to shared storage"
    assert payload["scope"] == []


# --------------------------------------------------------------------------
# multi-ID show (AGENT_READINESS §6.2, AGENT-029)
# --------------------------------------------------------------------------


def test_show_multiple_ids_print_sequential_documents(
    sample_graph: SampleGraph, capsys
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    goal = sample_graph.ids["goal"]
    text = show_text(root, story, goal)
    story_text = show_text(root, story)
    goal_text = show_text(root, goal)
    separator = "\n\n---\n"
    assert separator in text
    assert text == f"{story_text}\n---\n{goal_text}"


def test_show_single_id_output_is_unchanged_by_multi_support(
    sample_graph: SampleGraph,
) -> None:
    # Byte-for-byte backward compatibility (§6.2).
    root = sample_graph.root
    story = sample_graph.ids["story"]
    assert show_text(root, story) == show_text(root, story, story)


def test_show_multiple_ids_json_array(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    goal = sample_graph.ids["goal"]
    payload = show_json(root, story, goal)
    assert isinstance(payload, list)
    assert [item["id"] for item in payload] == [story, goal]
    single = show_json(root, story)
    assert payload[0] == single


def test_show_multiple_ids_deduplicate_preserving_order(
    sample_graph: SampleGraph,
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    goal = sample_graph.ids["goal"]
    payload = show_json(root, story, goal, story.lower())
    assert isinstance(payload, list)
    assert [item["id"] for item in payload] == [story, goal]


def test_show_multi_includes_cr_entry(sample_graph: SampleGraph) -> None:
    install_templates(sample_graph.root, "change-request")
    created = cr_new(sample_graph.workspace, title="Switch to shared storage")
    root = sample_graph.root
    story = sample_graph.ids["story"]
    payload = show_json(root, story, created.id)
    assert isinstance(payload, list)
    assert payload[0]["id"] == story
    assert payload[1]["kind"] == "change-request"
    assert payload[1]["title"] == "Switch to shared storage"


def test_show_multi_unknown_id_aborts_before_output(
    sample_graph: SampleGraph, capsys
) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    assert main(["--repo", str(root), "show", story, "RE-STORY-ZZZZZZ"]) == 4
    captured = capsys.readouterr()
    assert "E-ID-UNKNOWN" in captured.err
    assert story not in captured.out


def test_show_multi_body_flag(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    story = sample_graph.ids["story"]
    goal = sample_graph.ids["goal"]
    text = show_text(root, story, goal, "--body")
    assert "Sample body for Upload from the desktop." in text
    assert "Sample body for Increase self-service." in text
    payload = show_json(root, story, goal, "--body")
    assert isinstance(payload, list)
    assert all("body" in item for item in payload)
