"""Tests for ``gregraph new`` (spec §13.2): document creation via the CLI.

Flag-driven and interactive (type picker, title prompt, optional initial
links); every prompt has a flag equivalent; ``--edit`` opens the editor;
refusals exit 4 and write nothing. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from gregraph.cli.main import main
from gregraph.core.models import Document
from gregraph.core.operations import create_document
from gregraph.core.storage import read_sidecar
from gregraph.core.workspace import Workspace


class FakeTTY(io.StringIO):
    """Scripted stdin that reports itself as a terminal."""

    def isatty(self) -> bool:  # noqa: D102
        return True


def install_templates(root: Path, *names: str) -> None:
    """Copy shipped built-in templates into the repository (spec §5.5)."""
    from importlib.resources import files as resource_files

    source_root = resource_files("gregraph").joinpath("builtin_templates")
    for name in names:
        source = source_root.joinpath(name).joinpath("v1")
        target = root / ".gregraph" / "templates" / name / "v1"
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            (target / child.name).write_bytes(child.read_bytes())


@pytest.fixture
def template_repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo, "user-story", "feature", "goal")
    return tmp_repo


def created_document(root: Path) -> tuple[Path, Document]:
    bodies = [
        path
        for path in (root / "documents").rglob("*.md")
        if path.with_suffix(".json").is_file()
    ]
    assert bodies
    body = bodies[0]
    return body, read_sidecar(body.with_suffix(".json"), Document)


# --------------------------------------------------------------------------
# flag-driven creation
# --------------------------------------------------------------------------


def test_new_creates_document_pair(template_repo: Path, capsys) -> None:
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "Upload from the desktop",
                "--no-input",
            ]
        )
        == 0
    )
    body, document = created_document(template_repo)
    assert document.title == "Upload from the desktop"
    assert body.read_text(encoding="utf-8").startswith("# Upload from the desktop\n")
    out = capsys.readouterr().out
    assert document.id in out
    assert body.name in out


def test_new_records_tags_and_template(template_repo: Path) -> None:
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "T",
                "--tag",
                "ux",
                "--tag",
                "api",
                "--no-input",
            ]
        )
        == 0
    )
    _, document = created_document(template_repo)
    assert document.tags == ["ux", "api"]
    assert document.template.name == "user-story"
    assert document.template.version == 1


def test_new_initial_link_recorded(template_repo: Path) -> None:
    workspace = Workspace.open(template_repo)
    feature = create_document(
        workspace, type="feature", title="Upload documents", tags=(), links=()
    )
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "Story",
                "--link",
                f"refines:{feature.id}",
                "--no-input",
            ]
        )
        == 0
    )
    workspace.reload()
    story = [
        entry.model
        for entry in workspace.index.documents.values()
        if entry.model.title == "Story"
    ][0]
    assert [(link.type, link.target) for link in story.links] == [
        ("refines", feature.id)
    ]
    assert story.links[0].target_version == 1


def test_new_no_input_missing_title_is_usage_error(template_repo: Path) -> None:
    assert main(["--repo", str(template_repo), "new", "user-story", "--no-input"]) == 2


def test_new_no_input_missing_type_is_usage_error(template_repo: Path) -> None:
    assert main(["--repo", str(template_repo), "new", "--no-input"]) == 2


def test_new_unknown_type_refused(template_repo: Path, capsys) -> None:
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "no-such-type",
                "--title",
                "T",
                "--no-input",
            ]
        )
        == 4
    )
    assert "E-TYPE-UNKNOWN" in capsys.readouterr().err
    assert list((template_repo / "documents").rglob("*.md")) == []


def test_new_invalid_link_spec_is_usage_error(template_repo: Path) -> None:
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "T",
                "--link",
                "bogus",
                "--no-input",
            ]
        )
        == 2
    )


def test_new_refused_initial_link_writes_nothing(template_repo: Path, capsys) -> None:
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "T",
                "--link",
                "refines:RE-NOSUCH",
                "--no-input",
            ]
        )
        == 4
    )
    assert "E-LINK-TARGET-MISSING" in capsys.readouterr().err
    assert list((template_repo / "documents").rglob("*.md")) == []


def test_new_invalid_tag_refused(template_repo: Path, capsys) -> None:
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "T",
                "--tag",
                "NOT VALID",
                "--no-input",
            ]
        )
        == 4
    )
    assert "E-TAG-INVALID" in capsys.readouterr().err


def test_new_deprecated_template_refused_unless_allowed(template_repo: Path) -> None:
    import json

    descriptor = (
        template_repo
        / ".gregraph"
        / "templates"
        / "user-story"
        / "v1"
        / "template.json"
    )
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    data["deprecated"] = True
    descriptor.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    argv = [
        "--repo",
        str(template_repo),
        "new",
        "user-story",
        "--title",
        "T",
        "--no-input",
    ]
    assert main(argv) == 4
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "T",
                "--template-version",
                "1",
                "--allow-deprecated",
                "--no-input",
            ]
        )
        == 0
    )


# --------------------------------------------------------------------------
# interactive flow (scripted stdin)
# --------------------------------------------------------------------------


def test_new_interactive_prompts_for_type_title_and_links(
    template_repo: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "sys.stdin", FakeTTY("user-story\nUpload from the desktop\nrefines:RE-X\n\n")
    )
    assert main(["--repo", str(template_repo), "new"]) == 4
    assert "E-LINK-TARGET-MISSING" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", FakeTTY("user-story\nMy title\n\n"))
    assert main(["--repo", str(template_repo), "new"]) == 0
    body, document = created_document(template_repo)
    assert document.type == "user-story"
    assert document.title == "My title"
    assert body.read_text(encoding="utf-8").startswith("# My title\n")


def test_new_interactive_type_picker_shows_columns(
    template_repo: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("sys.stdin", FakeTTY("q\n"))
    assert main(["--repo", str(template_repo), "new"]) == 2
    out = capsys.readouterr().out
    assert "user-story" in out
    assert "requirement" in out


def test_new_interactive_cancel_on_type_picker(
    template_repo: Path, monkeypatch
) -> None:
    monkeypatch.setattr("sys.stdin", FakeTTY("q\n"))
    assert main(["--repo", str(template_repo), "new"]) == 2
    assert list((template_repo / "documents").rglob("*.md")) == []


# --------------------------------------------------------------------------
# --edit
# --------------------------------------------------------------------------


def test_new_edit_opens_editor(
    template_repo: Path, monkeypatch, tmp_path: Path
) -> None:
    log = tmp_path / "editor.log"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(sys.argv[2])\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EDITOR", f"{sys.executable} {recorder} {log}")
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "T",
                "--no-input",
                "--edit",
            ]
        )
        == 0
    )
    _, document = created_document(template_repo)
    assert log.read_text(encoding="utf-8").endswith(f"{document.id}.md")
