"""Tests for ``gregraph hooks`` (spec §13.22, §12.3): hook management CLI.

Install/status/uninstall round trip through the CLI, idempotence, preserving
foreign hook content, and refusals outside a Git repository. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import GitIdentity

from gregraph.cli.main import main

OTHER_HOOK = "#!/bin/sh\necho other-hook\n"


def hook_path(root: Path) -> Path:
    return root / ".git" / "hooks" / "pre-commit"


def test_install_creates_hook(tmp_repo: Path, identity: GitIdentity, capsys) -> None:
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    assert "pre-commit hook installed" in capsys.readouterr().out
    hook = hook_path(tmp_repo)
    assert hook.is_file()
    text = hook.read_text(encoding="utf-8")
    assert "# >>> gregraph pre-commit hook >>>" in text
    assert "hook pre-commit" in text


def test_status_reports_installed_and_up_to_date(
    tmp_repo: Path, identity: GitIdentity, capsys
) -> None:
    assert main(["--repo", str(tmp_repo), "hooks", "status"]) == 0
    assert "not installed" in capsys.readouterr().out
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "hooks", "status"]) == 0
    assert "installed and up to date" in capsys.readouterr().out


def test_status_reports_out_of_date_block(
    tmp_repo: Path, identity: GitIdentity, capsys
) -> None:
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    hook = hook_path(tmp_repo)
    hook.write_text(
        hook.read_text(encoding="utf-8").replace(
            "hook pre-commit", "hook pre-commit --stale"
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "hooks", "status"]) == 0
    captured = capsys.readouterr().out
    assert "installed but out of date" in captured
    assert "gregraph hooks install" in captured


def test_uninstall_removes_hook(tmp_repo: Path, identity: GitIdentity, capsys) -> None:
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    capsys.readouterr()
    assert main(["--repo", str(tmp_repo), "hooks", "uninstall"]) == 0
    assert "pre-commit hook uninstalled" in capsys.readouterr().out
    assert not hook_path(tmp_repo).exists()
    assert main(["--repo", str(tmp_repo), "hooks", "status"]) == 0
    assert "not installed" in capsys.readouterr().out


def test_uninstall_preserves_foreign_hook_content(
    tmp_repo: Path, identity: GitIdentity
) -> None:
    hook = hook_path(tmp_repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(OTHER_HOOK, encoding="utf-8")
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    text = hook.read_text(encoding="utf-8")
    assert text.startswith(OTHER_HOOK)
    assert main(["--repo", str(tmp_repo), "hooks", "uninstall"]) == 0
    assert hook.read_text(encoding="utf-8") == OTHER_HOOK


def test_install_is_idempotent(tmp_repo: Path, identity: GitIdentity) -> None:
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    first = hook_path(tmp_repo).read_bytes()
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    assert hook_path(tmp_repo).read_bytes() == first


def test_install_refuses_without_git(tmp_repo: Path, capsys) -> None:
    if (tmp_repo / ".git").exists():
        pytest.skip("needs the no-git tmp_repo")
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 4
    assert "E-GIT-UNAVAILABLE" in capsys.readouterr().err


def test_status_without_git_is_not_installed(tmp_repo: Path, capsys) -> None:
    if (tmp_repo / ".git").exists():
        pytest.skip("needs the no-git tmp_repo")
    assert main(["--repo", str(tmp_repo), "hooks", "status"]) == 0
    captured = capsys.readouterr()
    assert "not installed" in captured.out
    assert "not a git repository" in captured.err


def test_hooks_without_subcommand_is_usage_error(tmp_repo: Path) -> None:
    assert main(["--repo", str(tmp_repo), "hooks"]) == 2


# --------------------------------------------------------------------------
# --json payloads (AGENT_READINESS §2.4.3)
# --------------------------------------------------------------------------


def test_hooks_install_json_payload(
    tmp_repo: Path, identity: GitIdentity, capsys
) -> None:
    """§2.4.3: ``{hook, path, installed, up_to_date, findings, notices}``."""
    exit_code = main(["--repo", str(tmp_repo), "hooks", "install", "--json"])
    out = capsys.readouterr()
    assert exit_code == 0
    assert out.err == ""
    payload = json.loads(out.out)
    assert set(payload) == {
        "hook",
        "path",
        "installed",
        "up_to_date",
        "findings",
        "notices",
    }
    assert payload["hook"] == "pre-commit"
    assert payload["path"] == ".git/hooks/pre-commit"
    assert payload["installed"] is True
    assert payload["up_to_date"] is True
    assert payload["findings"] == []
    assert payload["notices"] == []


def test_hooks_status_json_payload(
    tmp_repo: Path, identity: GitIdentity, capsys
) -> None:
    assert main(["--repo", str(tmp_repo), "hooks", "status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["installed"] is False
    assert payload["up_to_date"] is False
    assert not hook_path(tmp_repo).exists()


def test_hooks_uninstall_json_payload(
    tmp_repo: Path, identity: GitIdentity, capsys
) -> None:
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    capsys.readouterr()
    exit_code = main(["--repo", str(tmp_repo), "hooks", "uninstall", "--json"])
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert payload["installed"] is False
    assert payload["up_to_date"] is False
    assert payload["notices"] == []


def test_hooks_status_json_carries_the_degraded_note(tmp_repo: Path, capsys) -> None:
    """R3: the degraded-mode note travels inside ``notices`` (stderr empty)."""
    if (tmp_repo / ".git").exists():
        pytest.skip("degraded mode only")
    exit_code = main(["--repo", str(tmp_repo), "hooks", "status", "--json"])
    out = capsys.readouterr()
    assert exit_code == 0
    assert out.err == ""
    payload = json.loads(out.out)
    assert payload["notices"] == ["not a git repository — hooks unavailable"]
    assert payload["installed"] is False
