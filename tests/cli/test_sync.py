"""Tests for ``gregraph sync`` (spec §13.7, §7.5).

Bump mode only in degraded mode or with ``--bump``; report mode lists the
pending changes; bodies are normalised (line endings, §5.2) and non-canonical
sidecars rewritten; the index cache is rebuilt (§16.5); the run is idempotent
including asset-hash change detection (§7.3). CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo``/``sample_graph``
fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gregraph.cli.main import main
from gregraph.core.models import Document
from gregraph.core.storage import canonical_json_bytes, read_sidecar
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import SampleGraph


def read_doc(root: Path, doc_id: str) -> Document:
    return read_sidecar(next((root / "documents").rglob(f"{doc_id}.json")), Document)


def edit_body(root: Path, doc_id: str, addition: str = "\nEdited.\n") -> Path:
    body = next((root / "documents").rglob(f"{doc_id}.md"))
    body.write_text(body.read_text(encoding="utf-8") + addition, encoding="utf-8")
    return body


def test_sync_bumps_only_in_degraded_mode_or_with_bump(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    edit_body(root, goal)
    assert main(["--repo", str(root), "sync"]) == 0
    document = read_doc(root, goal)
    out = capsys.readouterr().out
    if (root / ".git").exists():
        assert document.version == 1
        assert "pending" in out
        assert main(["--repo", str(root), "sync", "--bump"]) == 0
        assert read_doc(root, goal).version == 2
    else:
        assert document.version == 2
        assert "bumped" in out


def test_sync_is_idempotent_with_assets(sample_graph: SampleGraph) -> None:
    """§7.3: asset content is part of effective content — once per change."""
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    body = next((root / "documents").rglob(f"{goal}.md"))
    assets = root / "assets" / goal
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "img.png").write_bytes(b"png-bytes")
    body.write_text(
        body.read_text(encoding="utf-8") + f"\n![img](../../assets/{goal}/img.png)\n",
        encoding="utf-8",
    )
    assert main(["--repo", str(root), "sync", "--bump"]) == 0
    first = read_doc(root, goal)
    assert first.version == 2
    assert first.assets and first.assets[0].path == "img.png"
    assert first.assets[0].hash.startswith("sha256:")
    assert main(["--repo", str(root), "sync", "--bump"]) == 0
    assert read_doc(root, goal).version == 2


def test_sync_detects_asset_content_change(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    body = next((root / "documents").rglob(f"{goal}.md"))
    assets = root / "assets" / goal
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "img.png").write_bytes(b"png-bytes")
    body.write_text(
        body.read_text(encoding="utf-8") + f"\n![img](../../assets/{goal}/img.png)\n",
        encoding="utf-8",
    )
    assert main(["--repo", str(root), "sync", "--bump"]) == 0
    (assets / "img.png").write_bytes(b"new-png-bytes")
    assert main(["--repo", str(root), "sync", "--bump"]) == 0
    document = read_doc(root, goal)
    assert document.version == 3
    assert document.assets[0].hash.startswith("sha256:")


def test_sync_normalises_line_endings(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    body = next((root / "documents").rglob(f"{goal}.md"))
    body.write_bytes(body.read_bytes().replace(b"\n", b"\r\n"))
    assert main(["--repo", str(root), "sync"]) == 0
    assert b"\r" not in body.read_bytes()
    assert "normalised" in capsys.readouterr().out


def test_sync_rewrites_noncanonical_sidecar(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    goal = sample_graph.ids["goal"]
    sidecar = next((root / "documents").rglob(f"{goal}.json"))
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    sidecar.write_text(
        json.dumps(data, indent=4, sort_keys=False) + "\n", encoding="utf-8"
    )
    assert main(["--repo", str(root), "sync"]) == 0
    assert sidecar.read_bytes() == canonical_json_bytes(read_sidecar(sidecar, Document))


def test_sync_rebuilds_cache(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    cache = root / ".gregraph" / "cache" / "index.json"
    cache.unlink(missing_ok=True)
    assert main(["--repo", str(root), "sync"]) == 0
    assert cache.is_file()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["files"]
    Workspace.open(root)  # cache loadable


def test_sync_bump_reports_newly_outdated_links(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sample_graph.root
    feature = sample_graph.ids["feature"]
    story = sample_graph.ids["story"]
    edit_body(root, feature)
    assert main(["--repo", str(root), "sync", "--bump"]) == 0
    out = capsys.readouterr().out
    assert "newly outdated:" in out
    assert f"gregraph link refresh {story} refines {feature}" in out
    document = read_doc(root, story)
    entry = next(
        link
        for link in document.links
        if link.type == "refines" and link.target == feature
    )
    assert entry.target_version == 1  # refresh is a separate act (§7.4)
