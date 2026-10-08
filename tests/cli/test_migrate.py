"""Tests for ``gregraph migrate`` (spec §13.16, §7.7) — M4 acceptance.

End-to-end migration scenarios via the CLI: additive (in-place), renamed
sections, breaking (superseding), ``--dry-run`` plan output, selections
(IDs / ``--all`` / ``--template``) and skips.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_hook import install_templates, write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.models import Document
from gregraph.core.storage import config_path, read_sidecar


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def write_template_version(
    root: Path,
    name: str,
    version: int,
    sections: list[dict[str, object]],
    *,
    breaking: bool = False,
    description: str = "test template version",
) -> None:
    target = root / ".gregraph" / "templates" / name / f"v{version}"
    target.mkdir(parents=True, exist_ok=True)
    descriptor = {
        "schema": 1,
        "name": name,
        "version": version,
        "description": description,
        "deprecated": False,
        "breaking": breaking,
        "sections": sections,
    }
    (target / "template.json").write_text(
        json.dumps(descriptor, indent=2) + "\n", encoding="utf-8"
    )
    body = "# {{ title }}\n"
    for section in sections:
        body += f"\n## {section['heading']}\n*{section['placeholder']}*\n"
    (target / "template.md").write_text(body, encoding="utf-8")


def section(
    heading: str,
    placeholder: str = "Fill this in.",
    *,
    required: bool = False,
    renamed_from: list[str] | None = None,
) -> dict[str, object]:
    return {
        "heading": heading,
        "placeholder": placeholder,
        "renamed_from": renamed_from or [],
        "required": required,
    }


STORY_SECTION = section(
    "Story", "As a <role>, I want <capability>, so that <benefit>.", required=True
)

USER_STORY_V2_ADDITIVE = [
    STORY_SECTION,
    section("Motivation", "Explain the motivation."),
    section("Acceptance criteria", "Given … When … Then …", required=True),
    section("Rationale", "Explain why this story matters."),
    section("Notes", "Add supporting notes, links, or open questions."),
]

USER_STORY_V2_RENAMED = [
    STORY_SECTION,
    section("Acceptance criteria", "Given … When … Then …", required=True),
    section("Why", "Explain why this story matters.", renamed_from=["Rationale"]),
    section("Notes", "Add supporting notes, links, or open questions."),
]

USER_STORY_V2_BREAKING = [
    STORY_SECTION,
    section("Acceptance criteria", "Given … When … Then …", required=True),
    section("Legacy notes", "Legacy content goes here."),
]


def only_document(root: Path) -> Document:
    models = [
        read_sidecar(path, Document) for path in (root / "documents").rglob("*.json")
    ]
    assert len(models) == 1
    return models[0]


def test_migrate_additive_in_place(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "user-story", "Upload from the desktop")
    write_template_version(repo, "user-story", 2, USER_STORY_V2_ADDITIVE)
    assert main(["--repo", str(repo), "migrate", doc_id, "--no-input"]) == 0
    captured = capsys.readouterr().out
    assert f"{doc_id}  in-place  v1 -> v2" in captured
    assert "inserted: Motivation" in captured

    model = only_document(repo)
    assert model.id == doc_id
    assert model.template.version == 2
    body = (repo / "documents" / "user-story" / f"{doc_id}.md").read_text(
        encoding="utf-8"
    )
    assert "## Motivation" in body
    assert "## Story" in body


def test_migrate_renamed_sections(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "user-story", "Upload from the desktop")
    write_template_version(repo, "user-story", 2, USER_STORY_V2_RENAMED)
    assert main(["--repo", str(repo), "migrate", doc_id, "--no-input"]) == 0
    captured = capsys.readouterr().out
    assert "renamed: Rationale -> Why" in captured
    body = (repo / "documents" / "user-story" / f"{doc_id}.md").read_text(
        encoding="utf-8"
    )
    assert "## Why" in body
    assert "## Rationale" not in body
    assert only_document(repo).template.version == 2


def test_migrate_breaking_supersedes(repo: Path, capsys) -> None:
    old_id = write_doc(repo, "user-story", "Upload from the desktop")
    write_template_version(repo, "user-story", 2, USER_STORY_V2_BREAKING, breaking=True)
    assert main(["--repo", str(repo), "migrate", old_id, "--no-input"]) == 0
    captured = capsys.readouterr().out
    assert f"{old_id}  superseding  v1 -> v2" in captured
    assert "(new " in captured

    models = [
        read_sidecar(path, Document) for path in (repo / "documents").rglob("*.json")
    ]
    assert len(models) == 2
    new_model = next(model for model in models if model.id != old_id)
    assert any(
        item.type == "supersedes" and item.target == old_id for item in new_model.links
    )
    assert new_model.template.version == 2
    new_body = (repo / "documents" / "user-story" / f"{new_model.id}.md").read_text(
        encoding="utf-8"
    )
    assert "Unmapped content (migration)" in new_body


def test_migrate_dry_run_writes_nothing(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "user-story", "Upload from the desktop")
    write_template_version(repo, "user-story", 2, USER_STORY_V2_ADDITIVE)
    before = (repo / "documents" / "user-story" / f"{doc_id}.md").read_text(
        encoding="utf-8"
    )
    assert (
        main(["--repo", str(repo), "migrate", doc_id, "--no-input", "--dry-run"]) == 0
    )
    captured = capsys.readouterr().out
    assert "dry run: nothing written" in captured
    assert "inserted: Motivation" in captured
    after = (repo / "documents" / "user-story" / f"{doc_id}.md").read_text(
        encoding="utf-8"
    )
    assert after == before
    assert only_document(repo).template.version == 1


def test_migrate_all_and_template_selection(repo: Path) -> None:
    story = write_doc(repo, "user-story", "Upload from the desktop")
    feature = write_doc(repo, "feature", "Upload documents")
    write_template_version(repo, "user-story", 2, USER_STORY_V2_ADDITIVE)
    assert main(["--repo", str(repo), "migrate", "--template", "user-story"]) == 0
    story_model = read_sidecar(
        repo / "documents" / "user-story" / f"{story}.json", Document
    )
    feature_model = read_sidecar(
        repo / "documents" / "feature" / f"{feature}.json", Document
    )
    assert story_model.template.version == 2
    assert feature_model.template.version == 1

    write_template_version(repo, "feature", 2, [section("Story", required=True)])
    assert main(["--repo", str(repo), "migrate", "--all"]) == 0
    feature_model = read_sidecar(
        repo / "documents" / "feature" / f"{feature}.json", Document
    )
    assert feature_model.template.version == 2


def test_migrate_already_current_is_skipped(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "user-story", "Upload from the desktop")
    write_template_version(repo, "user-story", 2, USER_STORY_V2_ADDITIVE)
    assert main(["--repo", str(repo), "migrate", doc_id, "--no-input"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(repo), "migrate", doc_id, "--no-input"]) == 0
    captured = capsys.readouterr()
    assert f"{doc_id}  skipped" in captured.out
    assert "already pins" in captured.err


def test_migrate_conflicting_selection_is_usage_error(repo: Path) -> None:
    doc_id = write_doc(repo, "user-story", "Upload from the desktop")
    assert main(["--repo", str(repo), "migrate", doc_id, "--all"]) == 2
    assert (
        main(["--repo", str(repo), "migrate", doc_id, "--template", "user-story"]) == 2
    )


def test_migrate_without_selection_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "migrate", "--no-input"]) == 2
