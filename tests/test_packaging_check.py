"""Unit tests for the wheel-contract helpers in ``tests/packaging_check.py``.

The full build-and-install verification is the dedicated CI step; these tests
only exercise the pure helpers on synthetic wheel archives (spec §16.4).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import packaging_check as pc


def _wheel(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "")
    return path


def test_find_overlaps_reports_shared_members(tmp_path: Path) -> None:
    core = _wheel(tmp_path / "core.whl", ["gregraph/__init__.py", "gregraph/core/a.py"])
    cli = _wheel(tmp_path / "cli.whl", ["gregraph/__init__.py", "gregraph/cli/b.py"])
    assert pc.find_overlaps([core, cli]) == ["gregraph/__init__.py"]


def test_find_overlaps_empty_for_disjoint_wheels(tmp_path: Path) -> None:
    core = _wheel(tmp_path / "core.whl", ["gregraph/__init__.py"])
    cli = _wheel(tmp_path / "cli.whl", ["gregraph/__main__.py", "gregraph/cli/b.py"])
    assert pc.find_overlaps([core, cli]) == []


def test_contract_accepts_split_layout() -> None:
    core = {
        "gregraph/__init__.py",
        "gregraph/core/operations.py",
        "gregraph/builtin_templates/term/v1/template.json",
    }
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py"}
    assert pc.wheel_contract_violations(core, cli) == []


def test_contract_flags_missing_namespace_init_in_core() -> None:
    core = {"gregraph/core/operations.py"}
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py"}
    violations = pc.wheel_contract_violations(core, cli)
    assert any("gregraph/__init__.py" in v for v in violations)


def test_contract_flags_cli_leaking_into_core_or_init_into_cli() -> None:
    core = {
        "gregraph/__init__.py",
        "gregraph/core/operations.py",
        "gregraph/cli/main.py",
    }
    cli = {"gregraph/__init__.py", "gregraph/__main__.py", "gregraph/cli/main.py"}
    violations = pc.wheel_contract_violations(core, cli)
    assert any("core" in v and "gregraph/cli/main.py" in v for v in violations)
    assert any("cli" in v and "gregraph/__init__.py" in v for v in violations)


def test_contract_requires_builtin_templates_in_core() -> None:
    core = {"gregraph/__init__.py", "gregraph/core/operations.py"}
    cli = {"gregraph/__main__.py", "gregraph/cli/main.py"}
    violations = pc.wheel_contract_violations(core, cli)
    assert any("builtin_templates" in v for v in violations)
