"""Tests for ``gregraph new`` (spec §13.2): document creation via the CLI.

Flag-driven and interactive (type picker, title prompt, optional initial
links); every prompt has a flag equivalent; ``--edit`` opens the editor;
refusals exit 4 and write nothing. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from gregraph.cli.main import main
from gregraph.core.hashing import body_hash
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


# --------------------------------------------------------------------------
# --json payload and authoring flags (AGENT_READINESS §2.4.1, §3.4)
# --------------------------------------------------------------------------


def read_json(main_argv: list[str], capsys) -> tuple[int, dict]:
    capsys.readouterr()
    exit_code = main(main_argv)
    out = capsys.readouterr()
    assert out.err == "", out.err
    return exit_code, json.loads(out.out)


def test_new_json_payload_is_the_rich_authoring_payload(
    template_repo: Path, capsys
) -> None:
    """AGENT-010: paths, template sections, body and sidecar in one payload."""
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "Upload from the desktop",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert set(payload) == {
        "id",
        "uuid",
        "type",
        "kind",
        "md_path",
        "json_path",
        "template",
        "version",
        "body_hash",
        "sections",
        "body",
        "sidecar",
        "links",
        "findings",
        "notices",
    }
    body = template_repo / payload["md_path"]
    assert payload["body"] == body.read_text(encoding="utf-8")
    assert payload["json_path"] == str(
        body.with_suffix(".json").relative_to(template_repo)
    )
    assert payload["kind"] == "requirement"
    assert payload["version"] == 1
    assert payload["template"] == {"name": "user-story", "version": 1}
    assert [section["heading"] for section in payload["sections"]] == [
        "Story",
        "Acceptance criteria",
        "Rationale",
        "Notes",
    ]
    assert payload["sections"][0]["required"] is True
    sidecar = json.loads(body.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["sidecar"]["id"] == sidecar["id"] == payload["id"]
    assert payload["sidecar"]["title"] == "Upload from the desktop"
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["notices"], list)


def test_new_section_flags_assemble_the_body(template_repo: Path, capsys) -> None:
    """AGENT-015: canonical template order; unmentioned sections keep their
    placeholders."""
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "Story",
            "--section",
            "Acceptance criteria=Given x When y Then z",
            "--section",
            "Story=As a tester, I want speed.",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert payload["body"].splitlines() == [
        "# Story",
        "",
        "## Story",
        "",
        "As a tester, I want speed.",
        "",
        "## Acceptance criteria",
        "",
        "Given x When y Then z",
        "",
        "## Rationale",
        "",
        "*Explain why this story matters.*",
        "",
        "## Notes",
        "",
        "*Add supporting notes, links, or open questions.*",
    ]
    document = read_sidecar(template_repo / payload["json_path"], Document)
    assert document.body_hash == body_hash(payload["body"])


def test_new_section_file_reads_content_from_a_file(
    template_repo: Path, tmp_path: Path, capsys
) -> None:
    source = tmp_path / "rationale.md"
    source.write_text("Because speed matters.\n", encoding="utf-8")
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "Story",
            "--section",
            "Story=S.",
            "--section",
            "Acceptance criteria=G.",
            "--section-file",
            f"Rationale={source}",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert "Because speed matters." in payload["body"]


def test_new_body_file_reads_stdin(template_repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Whole new prose.\n"))
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "Story",
            "--body-file",
            "-",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 0
    # §3.4 rule 4: the tool owns the H1; the text is stored as sent.
    assert payload["body"] == "# Story\n\nWhole new prose.\n"
    assert payload["body_hash"].startswith("sha256:")


def test_new_body_flag_replaces_a_differing_h1_with_a_notice(
    template_repo: Path, capsys
) -> None:
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "Canonical title",
            "--body",
            "# Wrong title\n\nContent.\n",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert payload["body"].startswith("# Canonical title\n")
    assert any("title" in notice.lower() for notice in payload["notices"])


def test_new_duplicate_section_heading_is_usage_error(template_repo: Path) -> None:
    """§3.4 rule 1: content is never silently merged (exit 2)."""
    assert (
        main(
            [
                "--repo",
                str(template_repo),
                "new",
                "user-story",
                "--title",
                "T",
                "--section",
                "Story=one",
                "--section",
                "Story=two",
                "--no-input",
            ]
        )
        == 2
    )
    assert list((template_repo / "documents").rglob("*.md")) == []


def test_new_unknown_section_refusal_is_self_describing(
    template_repo: Path, capsys
) -> None:
    """AGENT-017: E-SECTION-UNKNOWN carries the template's section spec."""
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "T",
            "--section",
            "Acceptance Criteria=wrong case",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 4
    error = payload["error"]
    assert error["code"] == "E-SECTION-UNKNOWN"
    details = error["finding"]["details"]
    assert details["given_heading"] == "Acceptance Criteria"
    assert details["template"] == {"name": "user-story", "version": 1}
    headings = [s["heading"] for s in details["template_sections"]]
    assert headings == ["Story", "Acceptance criteria", "Rationale", "Notes"]
    assert list((template_repo / "documents").rglob("*.md")) == []


def test_new_strict_refuses_placeholder_required_sections(
    template_repo: Path, capsys
) -> None:
    """AGENT-018: ``--strict`` checks the assembled body at write time."""
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "T",
            "--strict",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 4
    error = payload["error"]
    assert error["code"] == "E-SECTION-REQUIRED-EMPTY"
    details = error["finding"]["details"]
    assert sorted(details["missing_required"]) == [
        "Acceptance criteria",
        "Story",
    ]
    headings = [s["heading"] for s in details["template_sections"]]
    assert "Story" in headings
    assert list((template_repo / "documents").rglob("*.md")) == []


def test_new_section_mode_requires_every_required_section(
    template_repo: Path, capsys
) -> None:
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "T",
            "--section",
            "Story=filled",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 4
    details = payload["error"]["finding"]["details"]
    assert details["missing_required"] == ["Acceptance criteria"]
    assert list((template_repo / "documents").rglob("*.md")) == []


def test_new_filled_sections_pass_strict(template_repo: Path, capsys) -> None:
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "T",
            "--section",
            "Story=S",
            "--section",
            "Acceptance criteria=A",
            "--strict",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 0
    assert payload["id"]
    assert list((template_repo / "documents").rglob("*.md"))


def test_new_json_quiet_still_prints_payload(template_repo: Path, capsys) -> None:
    """AGENT-006: ``--json`` takes precedence over ``--quiet``."""
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "T",
            "--section",
            "Story=S",
            "--section",
            "Acceptance criteria=A",
            "--no-input",
            "--json",
            "-q",
        ],
        capsys,
    )
    assert exit_code == 0
    assert payload["id"]


def test_new_without_git_identity_carries_the_finding_in_the_payload(
    template_repo: Path, capsys, monkeypatch
) -> None:
    """AGENT-004: findings travel in the payload; stderr stays empty."""
    # Hide any global/system git identity so the finding is deterministic.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    exit_code, payload = read_json(
        [
            "--repo",
            str(template_repo),
            "new",
            "user-story",
            "--title",
            "T",
            "--no-input",
            "--json",
        ],
        capsys,
    )
    assert exit_code == 0
    codes = [finding["code"] for finding in payload["findings"]]
    assert "W-NO-GIT-IDENTITY" in codes
