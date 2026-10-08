"""Tests for ``gregraph template`` (spec §13.17, §7.7): template management.

``list``/``add``/``bump``/``show`` via the CLI, refusal of unknown templates,
and the subcommand requirement. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_hook import install_templates

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.storage import config_path


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def test_template_list_shows_names_and_versions(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "list"]) == 0
    captured = capsys.readouterr().out
    assert "user-story" in captured
    assert "v1" in captured
    assert "change-request" in captured


def test_template_add_copies_builtin_as_next_version(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "add", "user-story"]) == 0
    assert "added user-story v2" in capsys.readouterr().out
    descriptor = json.loads(
        (
            repo / ".gregraph" / "templates" / "user-story" / "v2" / "template.json"
        ).read_text(encoding="utf-8")
    )
    assert descriptor["version"] == 2


def test_template_add_unknown_builtin_refused(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "add", "no-such"]) == 4
    assert "E-TEMPLATE-UNKNOWN" in capsys.readouterr().err


def test_template_bump_marks_breaking(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "template", "bump", "user-story", "--breaking"]) == 0
    )
    captured = capsys.readouterr().out
    assert "bumped user-story to v2" in captured
    assert "edit the new version's files" in captured
    descriptor = json.loads(
        (
            repo / ".gregraph" / "templates" / "user-story" / "v2" / "template.json"
        ).read_text(encoding="utf-8")
    )
    assert descriptor["breaking"] is True


def test_template_show_prints_descriptor_and_skeleton(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "show", "user-story"]) == 0
    captured = capsys.readouterr().out
    assert "user-story v1" in captured
    assert "description" in captured
    assert "# {{ title }}" in captured
    assert "## Story" in captured


def test_template_show_unknown_version_refused(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "template", "show", "user-story", "--version", "9"])
        == 4
    )
    assert "E-TEMPLATE-UNKNOWN" in capsys.readouterr().err


def test_template_unknown_name_refused(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "show", "no-such"]) == 4
    assert "E-TEMPLATE-UNKNOWN" in capsys.readouterr().err


def test_template_without_subcommand_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "template"]) == 2
