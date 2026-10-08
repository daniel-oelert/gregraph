"""Tests for ``gregraph repair`` (spec §13.19, §7.2, §12.6, §4.4).

``repair`` without a subcommand prints the §12.6 merge-conflict guidance;
``versions`` repairs conflicted sidecars; ``regenerate-id PATH`` fixes ID
collisions; ``cache`` rebuilds the index cache. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_hook import doc_body, doc_sidecar, install_templates, write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.models import Document
from gregraph.core.storage import config_path, read_sidecar
from gregraph.core.versioning import repair_guidance


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def test_repair_bare_prints_merge_conflict_guidance(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "repair"]) == 2
    captured = capsys.readouterr()
    assert "usage: gregraph repair" in captured.out
    for line in repair_guidance():
        assert line in captured.out
    assert "repair takes exactly one subcommand" in captured.err


def test_repair_versions_clean_repo_is_a_noop(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "repair", "versions"]) == 0
    assert "no conflicted sidecars" in capsys.readouterr().err


def test_repair_versions_resolves_conflict_markers(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "feature", "Upload documents")
    sidecar = doc_sidecar(repo, doc_id)
    model = read_sidecar(sidecar, Document)
    payload = model.model_dump(mode="json", by_alias=True)
    payload.pop("version")
    text = json.dumps(payload, indent=2, sort_keys=True)
    marker = '<<<<<<< HEAD\n  "version": 2,\n=======\n  "version": 3,\n>>>>>>> branch\n'
    text = text.replace('"schema": 1,', '"schema": 1,\n' + marker.rstrip("\n"), 1)
    sidecar.write_text(text + "\n", encoding="utf-8")

    assert main(["--repo", str(repo), "repair", "versions"]) == 0
    captured = capsys.readouterr().out
    assert "repaired" in captured
    assert "version 4" in captured
    repaired = read_sidecar(sidecar, Document)
    assert repaired.version == 4
    assert repaired.id == doc_id


def test_repair_regenerate_id_renames_files(repo: Path, capsys) -> None:
    doc_id = write_doc(repo, "feature", "Upload documents")
    body = doc_body(repo, doc_id)
    rel = body.relative_to(repo)
    assert main(["--repo", str(repo), "repair", "regenerate-id", str(rel)]) == 0
    captured = capsys.readouterr().out
    assert f"{doc_id} -> RE-" in captured
    assert not body.exists()
    assert not list((repo / "documents").rglob(f"{doc_id}.json"))
    models = [
        read_sidecar(path, Document) for path in (repo / "documents").rglob("*.json")
    ]
    assert len(models) == 1
    assert models[0].id != doc_id


def test_repair_regenerate_id_unknown_path_refused(repo: Path, capsys) -> None:
    assert (
        main(
            [
                "--repo",
                str(repo),
                "repair",
                "regenerate-id",
                "documents/user-story/x.md",
            ]
        )
        == 4
    )
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_repair_cache_rebuilds(repo: Path, capsys) -> None:
    write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "repair", "cache"]) == 0
    captured = capsys.readouterr().out
    assert "cache rebuilt" in captured
    assert "file(s)" in captured
    assert (repo / ".gregraph" / "cache" / "index.json").is_file()


def test_repair_without_subcommand_outside_repo(tmp_path: Path) -> None:
    assert main(["--repo", str(tmp_path), "repair"]) == 2
