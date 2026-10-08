"""Tests for ``gregraph validate`` (spec §13.9, §14).

Exit 1 on errors, exit 0 on warnings alone, ``--strict`` exits 1 on warnings
only, ``--only-errors`` filters the display report and ``--json`` emits the §14
payload ``[{code, severity, id|path, message, fix?}]``. CLI tests invoke
``gregraph.cli.main.main([...])``.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from gregraph.cli.main import main
from gregraph.core.operations import create_document
from gregraph.core.workspace import Workspace


def add_template(root: Path, name: str) -> None:
    directory = root / ".gregraph" / "templates" / name / "v1"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = {
        "schema": 1,
        "name": name,
        "version": 1,
        "description": f"{name} v1",
        "deprecated": False,
        "breaking": False,
        "sections": [{"heading": "Notes", "required": False, "placeholder": ""}],
    }
    (directory / "template.json").write_text(json.dumps(descriptor), encoding="utf-8")
    (directory / "template.md").write_text(
        "# {{ title }}\n\n## Notes\n", encoding="utf-8"
    )


def validate_json(root: Path, *extra: str) -> list[dict[str, object]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        main(["--repo", str(root), "validate", "--json", *extra])
    return json.loads(buffer.getvalue())


def test_validate_clean_repo_exits_0(tmp_repo: Path) -> None:
    add_template(tmp_repo, "goal")
    workspace = Workspace.open(tmp_repo)
    goal = create_document(workspace, type="goal", title="Goal")
    create_document(workspace, type="goal", title="Child", links=[("refines", goal.id)])
    assert main(["--repo", str(tmp_repo), "validate"]) == 0


def test_validate_warnings_exit_0_and_strict_exits_1(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "goal")
    workspace = Workspace.open(tmp_repo)
    create_document(workspace, type="goal", title="Orphan")  # W-ORPHAN
    assert main(["--repo", str(tmp_repo), "validate"]) == 0
    out = capsys.readouterr().out
    assert "W-ORPHAN" in out
    assert main(["--repo", str(tmp_repo), "validate", "--strict"]) == 1
    assert "W-ORPHAN" in capsys.readouterr().out


def test_validate_error_exits_1(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "goal")
    workspace = Workspace.open(tmp_repo)
    goal = create_document(workspace, type="goal", title="Goal")
    sidecar = next((tmp_repo / "documents").rglob(f"{goal.id}.json"))
    sidecar.write_text("{not json", encoding="utf-8")
    assert main(["--repo", str(tmp_repo), "validate"]) == 1
    assert "E-SIDECAR-INVALID" in capsys.readouterr().out


def test_validate_only_errors_filters_warnings(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_template(tmp_repo, "goal")
    workspace = Workspace.open(tmp_repo)
    create_document(workspace, type="goal", title="Orphan")
    goal = create_document(workspace, type="goal", title="Broken")
    sidecar = next((tmp_repo / "documents").rglob(f"{goal.id}.json"))
    sidecar.write_text("{not json", encoding="utf-8")
    assert main(["--repo", str(tmp_repo), "validate", "--only-errors"]) == 1
    out = capsys.readouterr().out
    assert "E-SIDECAR-INVALID" in out
    assert "W-ORPHAN" not in out


def test_validate_json_shape(tmp_repo: Path) -> None:
    add_template(tmp_repo, "goal")
    workspace = Workspace.open(tmp_repo)
    create_document(workspace, type="goal", title="Orphan")
    rows = validate_json(tmp_repo)
    orphan = next(row for row in rows if row["code"] == "W-ORPHAN")
    assert orphan["severity"] == "W"
    assert "message" in orphan
    assert "id" in orphan or "path" in orphan
    assert "fix" in orphan  # W-ORPHAN suggests an action
