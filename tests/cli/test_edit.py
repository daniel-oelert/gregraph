"""Tests for ``gregraph edit`` (spec §13.23): open the Markdown in the editor.

``$VISUAL``/``$EDITOR`` handling (missing/failing editor is an environment
error, exit 3), ID prompting via the picker, and refusals. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``sample_graph`` fixture.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from gregraph.cli.main import main

if TYPE_CHECKING:
    from conftest import SampleGraph


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:  # noqa: D102
        return True


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
    assert main(["--repo", str(sample_graph.root), "edit", "RE-NOSUCH"]) == 4
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
