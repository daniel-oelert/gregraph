"""Tests for ``gregraph term`` (spec §13.20, §10): glossary CLI.

``add``/``list``/``show``/``usage``/``rename``/``deprecate`` through the CLI:
slug derivation, alias clashes, word-boundary usage matching, rename listing
mentions without rewriting prose, and refusals. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_hook import install_templates, write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.models import Term
from gregraph.core.storage import config_path, read_sidecar


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def term_model(root: Path, slug: str) -> Term:
    return read_sidecar(root / "glossary" / f"{slug}.json", Term)


def test_term_add_creates_pair_and_derives_slug(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "term", "add", "Knowledge base", "--alias", "KB"])
        == 0
    )
    captured = capsys.readouterr().out
    assert "added knowledge-base" in captured
    assert (repo / "glossary" / "knowledge-base.md").is_file()
    model = term_model(repo, "knowledge-base")
    assert model.term == "Knowledge base"
    assert model.aliases == ["KB"]


def test_term_add_duplicate_slug_refused(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "term", "add", "Knowledge base"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(repo), "term", "add", "Knowledge  base"]) == 4
    assert "E-TERM-SLUG" in capsys.readouterr().err


def test_term_add_alias_clash_refused(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "term", "add", "Knowledge base", "--alias", "KB"])
        == 0
    )
    capsys.readouterr()
    assert (
        main(["--repo", str(repo), "term", "add", "Other term", "--alias", "kb"]) == 4
    )
    assert "E-TERM-ALIAS-CLASH" in capsys.readouterr().err


def test_term_list_table(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "term", "add", "Knowledge base"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(repo), "term", "list"]) == 0
    captured = capsys.readouterr().out
    assert "SLUG" in captured
    assert "knowledge-base" in captured
    assert "Knowledge base" in captured


def test_term_show_fields(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "term", "add", "Knowledge base", "--alias", "KB"])
        == 0
    )
    capsys.readouterr()
    assert main(["--repo", str(repo), "term", "show", "knowledge-base"]) == 0
    captured = capsys.readouterr().out
    assert "knowledge-base  Knowledge base" in captured
    assert "KB" in captured
    assert "status" in captured
    assert "body_hash" in captured


def test_term_usage_matches_names_and_aliases(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "term", "add", "Knowledge base", "--alias", "KB"])
        == 0
    )
    doc_id = write_doc(repo, "feature", "Upload documents")
    body = repo / "documents" / "feature" / f"{doc_id}.md"
    body.write_text(
        body.read_text(encoding="utf-8")
        + "\nThis feature uses the KB and the knowledge base.\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    assert main(["--repo", str(repo), "term", "usage", "knowledge-base"]) == 0
    captured = capsys.readouterr().out
    assert doc_id in captured
    assert "Knowledge base" in captured
    assert "KB" in captured


def test_term_rename_lists_mentions_without_rewriting(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "term", "add", "Knowledge base"]) == 0
    doc_id = write_doc(repo, "feature", "Upload documents")
    body = repo / "documents" / "feature" / f"{doc_id}.md"
    body.write_text(
        body.read_text(encoding="utf-8") + "\nSee the knowledge base for details.\n",
        encoding="utf-8",
    )
    before = body.read_text(encoding="utf-8")
    capsys.readouterr()
    assert (
        main(["--repo", str(repo), "term", "rename", "knowledge-base", "KB System"])
        == 0
    )
    captured = capsys.readouterr().out
    assert "renamed knowledge-base -> kb-system" in captured
    assert "mentions of the old name" in captured
    assert doc_id in captured
    assert body.read_text(encoding="utf-8") == before
    assert (repo / "glossary" / "kb-system.md").is_file()
    assert not (repo / "glossary" / "knowledge-base.md").exists()
    assert term_model(repo, "kb-system").term == "KB System"


def test_term_deprecate_sets_flag(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "term", "add", "Knowledge base"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "--repo",
                str(repo),
                "term",
                "deprecate",
                "knowledge-base",
                "--reason",
                "obsolete term",
            ]
        )
        == 0
    )
    assert "deprecated knowledge-base" in capsys.readouterr().out
    model = term_model(repo, "knowledge-base")
    assert model.deprecated is not None
    assert model.deprecated.reason == "obsolete term"


def test_term_deprecate_without_reason_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "term", "add", "Knowledge base"]) == 0
    assert (
        main(["--repo", str(repo), "term", "deprecate", "knowledge-base", "--no-input"])
        == 2
    )


def test_term_show_unknown_slug_refused(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "term", "show", "no-such"]) == 4
    assert "E-TERM-UNKNOWN" in capsys.readouterr().err


def test_term_without_subcommand_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "term"]) == 2


# --------------------------------------------------------------------------
# --json payloads (AGENT_READINESS §2.4.4) and term add authoring flags (§3.4)
# --------------------------------------------------------------------------


def test_term_add_json_payload(repo: Path, capsys) -> None:
    exit_code = main(
        [
            "--repo",
            str(repo),
            "term",
            "add",
            "Knowledge base",
            "--alias",
            "KB",
            "--section",
            "Definition=A store of documents.",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {
        "term",
        "slug",
        "aliases",
        "md_path",
        "json_path",
        "sections",
        "body",
        "body_hash",
        "findings",
        "notices",
    }
    assert payload["term"] == "Knowledge base"
    assert payload["slug"] == "knowledge-base"
    assert payload["aliases"] == ["KB"]
    assert payload["md_path"] == "glossary/knowledge-base.md"
    assert payload["body"] == (repo / "glossary/knowledge-base.md").read_text(
        encoding="utf-8"
    )
    assert "A store of documents." in payload["body"]
    assert payload["body_hash"].startswith("sha256:")
    assert [s["heading"] for s in payload["sections"]] == ["Definition", "Notes"]


def test_term_add_strict_refuses_placeholder_definition(repo: Path, capsys) -> None:
    exit_code = main(
        [
            "--repo",
            str(repo),
            "term",
            "add",
            "Knowledge base",
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
    assert details["missing_required"] == ["Definition"]
    assert not (repo / "glossary" / "knowledge-base.md").exists()


def test_term_add_unknown_section_refusal(repo: Path, capsys) -> None:
    exit_code = main(
        [
            "--repo",
            str(repo),
            "term",
            "add",
            "Knowledge base",
            "--section",
            "Wrong=content",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 4
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-SECTION-UNKNOWN"
    details = payload["error"]["finding"]["details"]
    assert details["given_heading"] == "Wrong"


def test_term_list_show_usage_json(repo: Path, capsys) -> None:
    mentioning = write_doc(repo, "user-story", "Mentioning story")
    body = next((repo / "documents").rglob(f"{mentioning}.md"))
    body.write_text(
        body.read_text(encoding="utf-8") + "\nThe Knowledge base helps.\n",
        encoding="utf-8",
    )
    assert main(["--repo", str(repo), "term", "add", "Knowledge base"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(repo), "term", "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"terms"}
    assert payload["terms"] == [
        {
            "term": "Knowledge base",
            "slug": "knowledge-base",
            "aliases": [],
            "version": 1,
            "deprecated": None,
        }
    ]
    assert main(["--repo", str(repo), "term", "show", "knowledge-base", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "term",
        "slug",
        "aliases",
        "created",
        "created_by",
        "version",
        "body_hash",
        "deprecated",
        "template",
        "status",
    }
    assert payload["term"] == "Knowledge base"
    assert payload["template"] == {"name": "term", "version": 1}
    assert payload["created"].endswith("Z")
    assert main(["--repo", str(repo), "term", "usage", "knowledge-base", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"slug", "term", "documents"}
    assert payload["slug"] == "knowledge-base"
    assert payload["documents"] == [{"id": mentioning, "mentions": ["Knowledge base"]}]


def test_term_rename_and_deprecate_json(repo: Path, capsys) -> None:
    mentioning = write_doc(repo, "user-story", "Mentioning story")
    body = next((repo / "documents").rglob(f"{mentioning}.md"))
    body.write_text(
        body.read_text(encoding="utf-8") + "\nThe Knowledge base helps.\n",
        encoding="utf-8",
    )
    assert main(["--repo", str(repo), "term", "add", "Knowledge base"]) == 0
    capsys.readouterr()
    exit_code = main(
        ["--repo", str(repo), "term", "rename", "knowledge-base", "New name", "--json"]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {
        "old_slug",
        "new_slug",
        "term",
        "mentioning_documents",
        "findings",
        "notices",
    }
    assert payload["old_slug"] == "knowledge-base"
    assert payload["new_slug"] == "new-name"
    assert payload["term"] == "New name"
    assert len(payload["mentioning_documents"]) == 1
    exit_code = main(
        [
            "--repo",
            str(repo),
            "term",
            "deprecate",
            "new-name",
            "--reason",
            "obsolete",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert set(payload) == {"slug", "deprecated", "findings", "notices"}
    assert payload["slug"] == "new-name"
    assert payload["deprecated"]["reason"] == "obsolete"
