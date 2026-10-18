"""Tests for ``gregraph supersede`` (spec §13.14, §7.6): replace documents.

Single and multi-target supersession (compromise, §11.2), copied links, stale
inbound reporting with ``link refresh --follow`` commands, ``--cr`` origin
tracking (§9.5), and refusals. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from test_hook import install_templates, link, write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.models import ChangeRequest, Document
from gregraph.core.storage import config_path, read_sidecar


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:  # noqa: D102
        return True


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def new_documents(root: Path) -> tuple[str, str, str]:
    """(source → old → target) chain with one inbound and one outbound link."""
    target = write_doc(root, "feature", "Upload documents")
    old = write_doc(
        root, "user-story", "Upload from the desktop", [link("depends-on", target)]
    )
    source = write_doc(root, "user-story", "Scan uploads", [link("depends-on", old)])
    return source, old, target


def document_by_title(root: Path, title: str) -> Document:
    for path in (root / "documents").rglob("*.json"):
        model = read_sidecar(path, Document)
        if model.title == title:
            return model
    raise AssertionError(f"no document titled {title!r}")


def test_supersede_creates_replacement_and_lists_stale_inbound(
    repo: Path, capsys
) -> None:
    source, old, target = new_documents(repo)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "supersede",
                old,
                "--title",
                "Upload from the desktop (v2)",
                "--no-input",
            ]
        )
        == 0
    )
    captured = capsys.readouterr().out
    created = document_by_title(repo, "Upload from the desktop (v2)")
    assert f"created {created.id}" in captured
    assert f"supersedes: {old}" in captured
    assert "stale inbound links" in captured
    assert f"gregraph link refresh {source} depends-on {old} --follow" in captured

    types = [(item.type, item.target) for item in created.links]
    assert ("supersedes", old) in types
    assert ("depends-on", target) in types


def test_supersede_multi_target_compromise(repo: Path, capsys) -> None:
    left = write_doc(root=repo, type_name="user-story", title="Left story")
    right = write_doc(root=repo, type_name="user-story", title="Right story")
    assert (
        main(
            [
                "--repo",
                str(repo),
                "supersede",
                left,
                right,
                "--title",
                "Compromise story",
                "--no-input",
            ]
        )
        == 0
    )
    created = document_by_title(repo, "Compromise story")
    supersedes = [item.target for item in created.links if item.type == "supersedes"]
    assert sorted(supersedes) == sorted([left, right])
    assert f"created {created.id}" in capsys.readouterr().out


def test_supersede_no_copy_body_renders_template(repo: Path) -> None:
    _source, old, _target = new_documents(repo)
    old_body = (repo / "documents" / "user-story" / f"{old}.md").read_text(
        encoding="utf-8"
    )
    assert (
        main(
            [
                "--repo",
                str(repo),
                "supersede",
                old,
                "--title",
                "Fresh story",
                "--no-copy-body",
                "--no-input",
            ]
        )
        == 0
    )
    created = document_by_title(repo, "Fresh story")
    new_body = (repo / "documents" / "user-story" / f"{created.id}.md").read_text(
        encoding="utf-8"
    )
    assert "Filled content" not in new_body
    assert new_body != old_body


def test_supersede_with_cr_records_origin_and_suggests_scope(
    repo: Path, capsys
) -> None:
    _source, old, _target = new_documents(repo)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "cr",
                "new",
                "--title",
                "Replace the story",
            ]
        )
        == 0
    )
    cr_id = next(path.stem for path in (repo / "changes").rglob("*.md"))
    capsys.readouterr()
    assert (
        main(
            [
                "--repo",
                str(repo),
                "supersede",
                old,
                "--title",
                "Replacement story",
                "--cr",
                cr_id,
                "--no-input",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert f"gregraph cr scope add {cr_id} {old} --intent supersede" in captured.err
    created = document_by_title(repo, "Replacement story")
    assert created.origin_cr == cr_id
    cr = read_sidecar(repo / "changes" / f"{cr_id}.json", ChangeRequest)
    assert cr.introduces == [created.id]


def test_supersede_unknown_id_refused(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "supersede", "RE-STORY-ZZZZZZ", "--no-input"]) == 4
    )
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_supersede_without_targets_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "supersede", "--no-input"]) == 2


def test_supersede_picker_selects_target(repo: Path, monkeypatch, capsys) -> None:
    _source, old, _target = new_documents(repo)
    monkeypatch.setattr("sys.stdin", FakeTTY(f"{old}\nq\n"))
    assert main(["--repo", str(repo), "supersede"]) == 0
    replacements = [
        model
        for model in (
            read_sidecar(path, Document)
            for path in (repo / "documents").rglob("*.json")
        )
        if any(item.type == "supersedes" and item.target == old for item in model.links)
    ]
    assert len(replacements) == 1
    assert replacements[0].id != old


# --------------------------------------------------------------------------
# --json payload and authoring flags (AGENT_READINESS §2.4.1, §3.4)
# --------------------------------------------------------------------------


def test_supersede_json_payload_embeds_the_new_document(repo: Path, capsys) -> None:
    _source, old, _target = new_documents(repo)
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(repo),
            "supersede",
            old,
            "--title",
            "Upload from the desktop (v2)",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {
        "old",
        "new",
        "supersedes",
        "copied_links",
        "skipped_links",
        "stale_inbound",
        "findings",
        "notices",
    }
    assert payload["old"] == [old]
    assert payload["supersedes"] == [old]
    new = payload["new"]
    assert set(new) == {
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
    }
    assert new["body"] == (repo / new["md_path"]).read_text(encoding="utf-8")
    assert ("supersedes", old, old) in [
        (link["type"], link["target"], old) for link in new["links"]
    ]
    stale = payload["stale_inbound"][0]
    assert stale["source"] == _source
    assert stale["type"] == "depends-on"
    assert stale["target"] == old


def test_supersede_section_flags_shape_the_new_body(repo: Path, capsys) -> None:
    _source, old, _target = new_documents(repo)
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(repo),
            "supersede",
            old,
            "--title",
            "Fresh sections",
            "--no-copy-body",
            "--section",
            "Story=As an agent, I want a rewrite.",
            "--section",
            "Acceptance criteria=Given rewrite, When run, Then ok.",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    body = payload["new"]["body"]
    assert "As an agent, I want a rewrite." in body
    assert "Given rewrite, When run, Then ok." in body
    assert "*Explain why this story matters.*" in body  # unmentioned → placeholder


def test_supersede_strict_refuses_placeholder_copies(repo: Path, capsys) -> None:
    """§3.4 rule 6: ``--strict`` validates the assembled body at write time."""
    _source, old, _target = new_documents(repo)
    # A skeleton target: --no-copy-body renders placeholders; strict refuses.
    skeleton = write_doc(repo, "user-story", "Skeleton")
    next((repo / "documents").rglob(f"{skeleton}.md")).write_text(
        "# Skeleton\n\n## Story\n\n*As a <role>, I want <capability>, so that "
        "<benefit>.*\n\n## Acceptance criteria\n\n*Given … When … Then …*\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(repo),
            "supersede",
            skeleton,
            "--title",
            "Strict replacement",
            "--no-copy-body",
            "--strict",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 4
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-SECTION-REQUIRED-EMPTY"
    details = payload["error"]["finding"]["details"]
    assert sorted(details["missing_required"]) == ["Acceptance criteria", "Story"]
    assert document_by_title_safe(repo, "Strict replacement") is None


def document_by_title_safe(root: Path, title: str) -> Document | None:
    for path in (root / "documents").rglob("*.json"):
        model = read_sidecar(path, Document)
        if model.title == title:
            return model
    return None


def test_supersede_unknown_section_refusal_is_self_describing(
    repo: Path, capsys
) -> None:
    _source, old, _target = new_documents(repo)
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(repo),
            "supersede",
            old,
            "--title",
            "T",
            "--section",
            "Wrong Heading=x",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 4
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-SECTION-UNKNOWN"
    details = payload["error"]["finding"]["details"]
    assert details["given_heading"] == "Wrong Heading"
    assert [s["heading"] for s in details["template_sections"]] == [
        "Story",
        "Acceptance criteria",
        "Rationale",
        "Notes",
    ]
