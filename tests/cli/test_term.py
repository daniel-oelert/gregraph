"""Tests for ``gregraph term`` (spec §13.20, §10): glossary CLI.

``add``/``list``/``show``/``usage``/``rename``/``deprecate`` through the CLI:
slug derivation, alias clashes, word-boundary usage matching, rename listing
mentions without rewriting prose, and refusals. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

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
