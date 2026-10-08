"""Tests for the ``gregraph.cli.main`` argparse tree (spec §13 general rules).

Global options, the complete §13 command registration (S18/S19 commands as
stubs), and the exit-code mapping: 0 ok, 1 validation/blocked, 2 usage,
3 no repository/environment, 4 refused, 5 internal. ``--version`` keeps the S0
contract of raising ``SystemExit(0)`` (tests/test_scaffold.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gregraph.cli.main import build_parser, main

ALL_COMMANDS = [
    "init",
    "new",
    "link",
    "unlink",
    "set",
    "sync",
    "check",
    "validate",
    "list",
    "show",
    "edit",
    "status",
    "graph",
    "supersede",
    "deprecate",
    "undeprecate",
    "migrate",
    "template",
    "repair",
    "term",
    "baseline",
    "hooks",
    "cr",
]


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_command_registered(command: str) -> None:
    args = build_parser().parse_args([command])
    assert args.command == command


def test_link_refresh_registered() -> None:
    args = build_parser().parse_args(["link-refresh", "--all", "--follow"])
    assert args.command == "link-refresh"
    assert args.all is True
    assert args.follow is True


def test_hook_registered_but_hidden() -> None:
    args = build_parser().parse_args(["hook", "pre-commit"])
    assert args.command == "hook"
    assert args.hook_cmd == "pre-commit"
    help_text = build_parser().format_help()
    assert re.search(r"(?m)^\s*hook\s", help_text) is None
    assert "hooks" in help_text


def test_help_lists_all_command_groups() -> None:
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0


def test_command_options_registered() -> None:
    parser = build_parser()
    assert (
        parser.parse_args(
            [
                "init",
                "--prefix",
                "XX",
                "--baseline-branch",
                "trunk",
                "--templates",
                "minimal",
                "--no-git",
            ]
        ).prefix
        == "XX"
    )
    assert (
        parser.parse_args(
            [
                "new",
                "user-story",
                "--title",
                "T",
                "--tag",
                "a",
                "--link",
                "refines:RE-1",
                "--cr",
                "CR-1",
                "--edit",
            ]
        ).title
        == "T"
    )
    assert parser.parse_args(["show", "RE-1", "--body", "--depth", "2"]).depth == 2
    assert (
        parser.parse_args(
            [
                "list",
                "--type",
                "goal",
                "--kind",
                "design",
                "--status",
                "draft",
                "--tag",
                "x",
                "--roots",
                "--orphans",
                "--outdated",
                "--stale",
                "--deprecated-templates",
                "--sort",
                "title",
            ]
        ).sort
        == "title"
    )
    assert parser.parse_args(["validate", "--strict", "--only-errors"]).strict is True
    assert (
        parser.parse_args(
            [
                "graph",
                "--root",
                "RE-1",
                "--depth",
                "3",
                "--types",
                "a,b",
                "--edges",
                "refines",
                "--include-superseded",
                "--direction",
                "LR",
                "-o",
                "g.mmd",
            ]
        ).direction
        == "LR"
    )
    assert (
        parser.parse_args(
            ["supersede", "RE-1", "RE-2", "--title", "T", "--no-copy-body"]
        ).copy_body
        is False
    )
    assert parser.parse_args(["deprecate", "RE-1", "--reason", "r"]).reason == "r"
    assert parser.parse_args(["undeprecate", "RE-1"]).command == "undeprecate"
    assert (
        parser.parse_args(
            ["migrate", "--all", "--to", "2", "--supersede", "--dry-run"]
        ).all
        is True
    )
    assert parser.parse_args(["set", "RE-1", "tags=a,b", "extra.x=y"]).assignments == [
        "tags=a,b",
        "extra.x=y",
    ]
    assert parser.parse_args(["sync", "--bump"]).bump is True
    assert parser.parse_args(
        ["cr", "new", "--title", "T", "--scope", "RE-1:modify", "--external-ref", "J-1"]
    ).scope == ["RE-1:modify"]
    assert (
        parser.parse_args(
            ["cr", "scope", "add", "CR-1", "RE-1", "--intent", "supersede"]
        ).intent
        == "supersede"
    )
    assert (
        parser.parse_args(["cr", "list", "--effective", "--pending", "--drift"]).pending
        is True
    )
    assert parser.parse_args(["template", "add", "user-story"]).builtin == "user-story"
    assert (
        parser.parse_args(["template", "bump", "user-story", "--breaking"]).breaking
        is True
    )
    assert (
        parser.parse_args(["template", "show", "user-story", "--version", "2"]).version
        == 2
    )
    assert (
        parser.parse_args(["term", "add", "Term", "--alias", "A", "--edit"]).term
        == "Term"
    )
    assert (
        parser.parse_args(["term", "rename", "slug", "New term"]).new_term == "New term"
    )
    assert parser.parse_args(["baseline", "create", "v1", "-m", "msg"]).message == "msg"
    assert parser.parse_args(["hooks", "install"]).hooks_cmd == "install"
    assert (
        parser.parse_args(["repair", "regenerate-id", "documents/x.md"]).path
        == "documents/x.md"
    )
    assert (
        parser.parse_args(["link-refresh", "--from", "RE-1", "--dry-run"]).dry_run
        is True
    )


# --------------------------------------------------------------------------
# usage errors (exit 2)
# --------------------------------------------------------------------------


def test_unknown_command_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bogus"]) == 2
    assert "error" in capsys.readouterr().err


def test_unknown_option_is_usage_error() -> None:
    assert main(["list", "--bogus"]) == 2


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    captured = capsys.readouterr()
    assert "usage:" in captured.out


def test_version_raises_system_exit_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


def test_help_raises_system_exit_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


# --------------------------------------------------------------------------
# environment errors (exit 3)
# --------------------------------------------------------------------------


def test_exit_3_outside_repository(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["list"]) == 3
    assert main(["--repo", str(tmp_path), "show", "RE-1"]) == 3


def test_exit_3_repo_option_must_be_root(tmp_repo: Path) -> None:
    assert main(["--repo", str(tmp_repo / "documents"), "list"]) == 3


def test_root_discovered_from_current_directory(
    tmp_repo: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_repo / "documents")
    assert main(["list"]) == 0
    assert "ID" in capsys.readouterr().out.splitlines()[0]


def test_exit_3_message_mentions_repository(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["list"]) == 3
    assert ".gregraph" in capsys.readouterr().err


# --------------------------------------------------------------------------
# refusals (exit 4) and stubs (exit 5)
# --------------------------------------------------------------------------


def test_operation_refused_exits_4_with_finding(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "--repo",
                str(tmp_repo),
                "new",
                "no-such-type",
                "--title",
                "X",
                "--no-input",
            ]
        )
        == 4
    )
    captured = capsys.readouterr()
    assert "E-TYPE-UNKNOWN" in captured.err
    assert "no-such-type" in captured.err


def test_unimplemented_command_exits_5(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    import gregraph.cli.main as cli_main

    monkeypatch.setitem(
        cli_main._COMMAND_MODULES, "sync", "gregraph.cli.commands.missing_module"
    )
    assert main(["--repo", str(tmp_repo), "sync"]) == 5
    assert "not implemented" in capsys.readouterr().err


def test_link_refresh_routes_to_refresh_command(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--repo", str(tmp_repo), "link", "refresh", "--all"]) == 0
    assert "no matching links" in capsys.readouterr().err


# --------------------------------------------------------------------------
# global options
# --------------------------------------------------------------------------


def test_global_options_accepted_before_and_after_command(
    tmp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--json", "--repo", str(tmp_repo), "list"]) == 0
    out = capsys.readouterr().out
    assert out.lstrip().startswith("[")
    assert main(["list", "--json", "--repo", str(tmp_repo)]) == 0


def test_no_input_is_global(tmp_repo: Path) -> None:
    assert main(["--repo", str(tmp_repo), "new", "--no-input"]) == 2
