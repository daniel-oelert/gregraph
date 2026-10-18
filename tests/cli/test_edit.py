"""Tests for ``gregraph edit`` (spec §13.23): open the Markdown in the editor.

``$VISUAL``/``$EDITOR`` handling (missing/failing editor is an environment
error, exit 3), ID prompting via the picker, and refusals. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``sample_graph`` fixture.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gregraph.cli.main import main

if TYPE_CHECKING:
    from conftest import SampleGraph


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:  # noqa: D102
        return True


@pytest.fixture
def template_repo(tmp_repo: Path) -> Path:
    """The shipped ``user-story`` template installed (spec §5.5)."""
    from test_new import install_templates

    install_templates(tmp_repo, "user-story")
    return tmp_repo


def recorder_editor(tmp_path: Path, monkeypatch) -> Path:
    """Install an ``$EDITOR`` that records the opened file into ``editor.log``."""
    log = tmp_path / "editor.log"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(sys.argv[2])\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EDITOR", f"{sys.executable} {recorder} {log}")
    monkeypatch.delenv("VISUAL", raising=False)
    return log


def test_edit_opens_editor_on_body(
    sample_graph: SampleGraph, monkeypatch, tmp_path: Path
) -> None:
    log = recorder_editor(tmp_path, monkeypatch)
    story = sample_graph.ids["story"]
    assert main(["--repo", str(sample_graph.root), "edit", story]) == 0
    opened = log.read_text(encoding="utf-8")
    assert opened.endswith(f"{story}.md")
    assert "documents" in opened


def test_edit_prefers_visual(
    sample_graph: SampleGraph, monkeypatch, tmp_path: Path
) -> None:
    log = recorder_editor(tmp_path, monkeypatch)
    visual_log = tmp_path / "visual.log"
    recorder = tmp_path / "recorder.py"
    monkeypatch.setenv("VISUAL", f"{sys.executable} {recorder} {visual_log}")
    story = sample_graph.ids["story"]
    assert main(["--repo", str(sample_graph.root), "edit", story]) == 0
    assert visual_log.is_file()
    assert not log.is_file()


def test_edit_without_editor_is_environment_error(
    sample_graph: SampleGraph, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    assert (
        main(["--repo", str(sample_graph.root), "edit", sample_graph.ids["story"]]) == 3
    )
    assert "EDITOR" in capsys.readouterr().err


def test_edit_failing_editor_is_environment_error(
    sample_graph: SampleGraph, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "false")
    assert (
        main(["--repo", str(sample_graph.root), "edit", sample_graph.ids["story"]]) == 3
    )
    assert "error" in capsys.readouterr().err


def test_edit_unknown_id_refused(
    sample_graph: SampleGraph, monkeypatch, tmp_path: Path, capsys
) -> None:
    recorder_editor(tmp_path, monkeypatch)
    assert main(["--repo", str(sample_graph.root), "edit", "RE-STORY-ZZZZZZ"]) == 4
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_edit_missing_id_without_input_is_usage_error(
    sample_graph: SampleGraph,
) -> None:
    assert main(["--repo", str(sample_graph.root), "edit", "--no-input"]) == 2


def test_edit_picker_selects_document(
    sample_graph: SampleGraph, monkeypatch, tmp_path: Path, capsys
) -> None:
    log = recorder_editor(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", FakeTTY("q\n"))
    assert main(["--repo", str(sample_graph.root), "edit"]) == 2
    out = capsys.readouterr().out
    assert sample_graph.ids["story"] in out
    assert "user-story" in out
    story = sample_graph.ids["story"]
    monkeypatch.setattr("sys.stdin", FakeTTY(f"{story}\n"))
    assert main(["--repo", str(sample_graph.root), "edit"]) == 0
    assert log.read_text(encoding="utf-8").endswith(f"{story}.md")


# --------------------------------------------------------------------------
# content flags: --section / --section-file / --body / --body-file / --strict
# (AGENT_READINESS §3.4, §2.4.1)
# --------------------------------------------------------------------------


def create_story(root: Path, title: str, *extra: str) -> str:
    """A filled user-story via the CLI; returns its ID (title lookup)."""
    from gregraph.core.workspace import Workspace

    argv = [
        "--repo",
        str(root),
        "new",
        "user-story",
        "--title",
        title,
        "--section",
        "Story=As an agent, I want a story.",
        "--section",
        "Acceptance criteria=Given x, When y, Then z.",
        "--no-input",
        *extra,
    ]
    assert main(argv) == 0
    workspace = Workspace.open(root)
    return next(
        entry.model.id
        for entry in workspace.index.documents.values()
        if entry.model.title == title
    )


def test_edit_section_updates_one_section_and_json_payload(
    template_repo: Path, capsys
) -> None:
    doc_id = create_story(template_repo, "Story")
    body_path = next((template_repo / "documents").rglob(f"{doc_id}.md"))
    before = body_path.read_text(encoding="utf-8")
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(template_repo),
            "edit",
            doc_id,
            "--section",
            "Notes=My own notes.",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {
        "id",
        "md_path",
        "json_path",
        "body",
        "body_hash",
        "title",
        "changed",
        "sections",
        "findings",
        "notices",
    }
    assert payload["id"] == doc_id
    assert payload["changed"] is True
    assert payload["md_path"] == str(body_path.relative_to(template_repo))
    assert payload["body"] == body_path.read_text(encoding="utf-8")
    assert "My own notes." in payload["body"]
    # AGENT-016: unmentioned sections keep their bytes verbatim.
    for line in before.splitlines():
        if line.startswith("As an agent") or line.startswith("Given x"):
            assert line in payload["body"]
    assert [s["heading"] for s in payload["sections"]][:2] == [
        "Story",
        "Acceptance criteria",
    ]


def test_edit_body_flag_owns_the_h1(template_repo: Path, capsys) -> None:
    """AGENT-019/§3.4 rule 8: no H1 in the text prepends ``# <title>``; an H1
    in the text is stored as sent and the sidecar title follows it."""
    doc_id = create_story(template_repo, "Story")
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(template_repo),
            "edit",
            doc_id,
            "--body",
            "No heading here.\n",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert payload["body"].startswith("# Story\n")
    assert payload["title"] == "Story"
    assert payload["notices"] == []
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(template_repo),
            "edit",
            doc_id,
            "--body",
            "# Renamed story\n\nReplaced.\n",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert payload["body"].startswith("# Renamed story\n")
    assert payload["title"] == "Renamed story"


def test_edit_body_file_and_stdin(template_repo: Path, tmp_path, monkeypatch) -> None:
    doc_id = create_story(template_repo, "Story")
    source = tmp_path / "body.md"
    source.write_text("From a file.\n", encoding="utf-8")
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "edit",
                doc_id,
                "--body-file",
                str(source),
                "--no-input",
            ]
        )
        == 0
    )
    body_path = next((template_repo / "documents").rglob(f"{doc_id}.md"))
    assert "From a file." in body_path.read_text(encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO("From stdin.\n"))
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "edit",
                doc_id,
                "--body-file",
                "-",
                "--no-input",
            ]
        )
        == 0
    )
    assert "From stdin." in body_path.read_text(encoding="utf-8")


def test_edit_strict_without_flags_checks_required_sections(
    template_repo: Path, capsys
) -> None:
    """§3.4 rule 6: ``--strict`` alone validates the current body at write
    time."""
    doc_id = create_story(
        template_repo,
        "Skeleton story",
    )
    # Overwrite the body with placeholder text (as a plain ``new`` leaves it).
    body_path = next((template_repo / "documents").rglob(f"{doc_id}.md"))
    body_path.write_text(
        "# Skeleton story\n\n## Story\n\n*As a <role>, I want "
        "<capability>, so that <benefit>.*\n\n## Acceptance criteria\n\n"
        "*Given … When … Then …*\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(template_repo),
            "edit",
            doc_id,
            "--strict",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 4
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-SECTION-REQUIRED-EMPTY"
    assert sorted(payload["error"]["finding"]["details"]["missing_required"]) == [
        "Acceptance criteria",
        "Story",
    ]


def test_edit_strict_passes_when_sections_are_filled(
    template_repo: Path, capsys
) -> None:
    doc_id = create_story(template_repo, "Story")
    capsys.readouterr()
    assert (
        main(["--repo", str(template_repo), "edit", doc_id, "--strict", "--no-input"])
        == 0
    )


def test_edit_json_without_content_flags_is_usage_error(
    template_repo: Path, capsys
) -> None:
    """§2.4.1: ``edit --json`` without content flags is refused E-USAGE."""
    doc_id = create_story(template_repo, "Story")
    capsys.readouterr()
    assert (
        main(["--repo", str(template_repo), "edit", doc_id, "--no-input", "--json"])
        == 2
    )
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-USAGE"
    assert "--body" in payload["error"]["message"]


def test_edit_body_and_section_together_is_usage_error(
    template_repo: Path,
) -> None:
    doc_id = create_story(template_repo, "Story")
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "edit",
                doc_id,
                "--body",
                "x",
                "--section",
                "Story=y",
                "--no-input",
            ]
        )
        == 2
    )


def test_edit_unknown_section_heading_refused_with_details(
    template_repo: Path, capsys
) -> None:
    doc_id = create_story(template_repo, "Story")
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(template_repo),
            "edit",
            doc_id,
            "--section",
            "Nonexistent=content",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 4
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-SECTION-UNKNOWN"
    details = payload["error"]["finding"]["details"]
    assert details["given_heading"] == "Nonexistent"
    assert [s["heading"] for s in details["template_sections"]] == [
        "Story",
        "Acceptance criteria",
        "Rationale",
        "Notes",
    ]
