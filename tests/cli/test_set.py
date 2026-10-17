"""Tests for ``gregraph set`` (spec §13.6, AGENT_READINESS §2.4.1).

Tag and extra-field assignments through the CLI, the ``--json`` payload with
its ``applied`` mapping (key of each given assignment → value), and refusals.
CLI tests invoke ``gregraph.cli.main.main([...])`` with the ``tmp_repo``
fixture.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from test_hook import write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.storage import config_path, read_sidecar


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    from test_hook import install_templates

    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def read_doc(root: Path, doc_id: str):
    from gregraph.core.models import Document

    return read_sidecar(next((root / "documents").rglob(f"{doc_id}.json")), Document)


def test_set_replaces_tags_and_sets_extra(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "user-story", "Tagged story")
    exit_code = main(
        [
            "--repo",
            str(repo),
            "set",
            doc_id,
            "tags=alpha,beta",
            "extra.owner=team-x",
            "--no-input",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    assert f"updated {doc_id}" in out.out
    document = read_doc(repo, doc_id)
    assert document.tags == ["alpha", "beta"]
    assert document.extra == {"owner": "team-x"}


def test_set_json_payload_reports_applied(repo: Path, capsys) -> None:
    """§2.4.1: ``{id, applied, findings, notices}`` with the given keys."""
    doc_id = write_doc(repo, "user-story", "Payload story")
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(repo),
            "set",
            doc_id,
            "tags=alpha",
            "extra.owner=team-x",
            "--no-input",
            "--json",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    assert out.err == ""
    payload = json.loads(out.out)
    assert set(payload) == {"id", "applied", "findings", "notices"}
    assert payload["id"] == doc_id
    assert payload["applied"] == {"tags": "alpha", "extra.owner": "team-x"}
    assert payload["findings"] == []
    assert payload["notices"] == []
    document = read_doc(repo, doc_id)
    assert document.tags == ["alpha"]


def test_set_json_no_change_still_succeeds(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "user-story", "Same story")
    capsys.readouterr()
    exit_code = main(
        ["--repo", str(repo), "set", doc_id, "tags=", "--no-input", "--json"]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert payload["applied"] == {"tags": ""}


def test_set_unknown_key_refused(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "user-story", "Refused story")
    capsys.readouterr()
    exit_code = main(
        ["--repo", str(repo), "set", doc_id, "title=nope", "--no-input", "--json"]
    )
    out = capsys.readouterr()
    assert exit_code == 4
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-SET-KEY"


def test_set_missing_assignment_is_usage_error(repo: Path) -> None:
    doc_id = write_doc(repo, "user-story", "Usage story")
    assert main(["--repo", str(repo), "set", doc_id, "--no-input"]) == 2


def test_set_interactive_prompts_for_document_and_assignment(
    repo: Path, monkeypatch, capsys
) -> None:
    doc_id = write_doc(repo, "user-story", "Prompted story")

    class FakeTTY(io.StringIO):
        def isatty(self) -> bool:  # noqa: D102
            return True

    monkeypatch.setattr("sys.stdin", FakeTTY(f"{doc_id}\ntags=ux\n\n"))
    exit_code = main(["--repo", str(repo), "set"])
    capsys.readouterr()
    assert exit_code == 0
    assert read_doc(repo, doc_id).tags == ["ux"]
