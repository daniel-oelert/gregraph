"""Tests for ``gregraph.core.hooks`` (spec §12.3).

Hook installation round-trip: script generation, install onto fresh and
pre-existing hooks, idempotence, uninstall, and status. ``pathlib`` throughout;
the executable-bit assertion is POSIX-only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from gregraph.core.hooks import (
    HookStatus,
    install,
    pre_commit_script,
    status,
    uninstall,
)

OTHER_HOOK = "#!/bin/sh\necho other-hook\n"
STALE_INTERPRETER = "/nonexistent/gregraph-test-python"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Bare root directory; ``install`` creates ``.git/hooks`` itself."""
    return tmp_path


def hook_path(root: Path) -> Path:
    return root / ".git" / "hooks" / "pre-commit"


class TestPreCommitScript:
    def test_runs_module_via_recorded_interpreter(self) -> None:
        script = pre_commit_script("/venv/bin/python")
        assert "'/venv/bin/python' -m gregraph hook pre-commit" in script

    def test_defaults_to_current_interpreter(self) -> None:
        script = pre_commit_script()
        assert f"'{sys.executable}' -m gregraph hook pre-commit" in script

    def test_falls_back_to_gregraph_on_path(self) -> None:
        script = pre_commit_script("/venv/bin/python")
        assert "else" in script
        assert "\n    gregraph hook pre-commit || exit $?\n" in script

    def test_is_a_shell_script_with_delimited_block(self) -> None:
        script = pre_commit_script()
        assert script.startswith("#!/bin/sh\n")
        assert "# >>> gregraph pre-commit hook >>>" in script
        assert "# <<< gregraph pre-commit hook <<<" in script
        assert script.endswith("\n")


class TestInstall:
    def test_creates_hook(self, root: Path) -> None:
        install(root)
        hook = hook_path(root)
        assert hook.is_file()
        text = hook.read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh\n")
        assert "# >>> gregraph pre-commit hook >>>" in text
        assert "# <<< gregraph pre-commit hook <<<" in text
        assert f"'{sys.executable}' -m gregraph hook pre-commit" in text

    def test_creates_parent_directories(self, root: Path) -> None:
        install(root)
        assert (root / ".git" / "hooks").is_dir()

    @pytest.mark.skipif(os.name != "posix", reason="executable bit is POSIX-only")
    def test_makes_hook_executable(self, root: Path) -> None:
        install(root)
        assert os.access(hook_path(root), os.X_OK)

    def test_appends_to_pre_existing_hook(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(OTHER_HOOK, encoding="utf-8")
        install(root)
        text = hook.read_text(encoding="utf-8")
        assert text.startswith(OTHER_HOOK)
        assert text.index("# >>> gregraph pre-commit hook >>>") >= len(OTHER_HOOK)

    def test_creates_hook_when_file_is_empty(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text("", encoding="utf-8")
        install(root)
        assert hook.read_text(encoding="utf-8").startswith("#!/bin/sh\n")

    def test_twice_is_idempotent(self, root: Path) -> None:
        install(root)
        first = hook_path(root).read_bytes()
        install(root)
        assert hook_path(root).read_bytes() == first

    def test_twice_on_pre_existing_hook_is_idempotent(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(OTHER_HOOK, encoding="utf-8")
        install(root)
        first = hook.read_bytes()
        install(root)
        assert hook.read_bytes() == first

    def test_replaces_out_of_date_block(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(pre_commit_script(STALE_INTERPRETER), encoding="utf-8")
        install(root)
        text = hook.read_text(encoding="utf-8")
        assert text.count("# >>> gregraph pre-commit hook >>>") == 1
        assert STALE_INTERPRETER not in text
        assert status(root) == HookStatus(installed=True, up_to_date=True)


class TestUninstall:
    def test_removes_block_and_deletes_bare_hook(self, root: Path) -> None:
        install(root)
        uninstall(root)
        assert not hook_path(root).exists()

    def test_keeps_other_content(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(OTHER_HOOK, encoding="utf-8")
        install(root)
        uninstall(root)
        assert hook.read_text(encoding="utf-8") == OTHER_HOOK

    def test_noop_when_hook_absent(self, root: Path) -> None:
        uninstall(root)
        assert not hook_path(root).exists()

    def test_noop_when_hook_has_no_block(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(OTHER_HOOK, encoding="utf-8")
        uninstall(root)
        assert hook.read_text(encoding="utf-8") == OTHER_HOOK

    def test_removes_only_the_gregraph_block(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(OTHER_HOOK, encoding="utf-8")
        install(root)
        hook.write_text(
            hook.read_text(encoding="utf-8") + "echo after\n", encoding="utf-8"
        )
        uninstall(root)
        text = hook.read_text(encoding="utf-8")
        assert "# >>> gregraph pre-commit hook >>>" not in text
        assert "echo after" in text
        assert "echo other-hook" in text


class TestStatus:
    def test_not_installed(self, root: Path) -> None:
        assert status(root) == HookStatus(installed=False, up_to_date=False)

    def test_not_installed_when_hook_has_no_block(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(OTHER_HOOK, encoding="utf-8")
        assert status(root) == HookStatus(installed=False, up_to_date=False)

    def test_installed_and_up_to_date(self, root: Path) -> None:
        install(root)
        assert status(root) == HookStatus(installed=True, up_to_date=True)

    def test_out_of_date_when_interpreter_changed(self, root: Path) -> None:
        hook = hook_path(root)
        hook.parent.mkdir(parents=True)
        hook.write_text(pre_commit_script(STALE_INTERPRETER), encoding="utf-8")
        assert status(root) == HookStatus(installed=True, up_to_date=False)

    def test_out_of_date_when_block_edited(self, root: Path) -> None:
        install(root)
        hook = hook_path(root)
        hook.write_text(
            hook.read_text(encoding="utf-8").replace(
                "-m gregraph hook pre-commit", "-m gregraph hook pre-commit --old"
            ),
            encoding="utf-8",
        )
        assert status(root) == HookStatus(installed=True, up_to_date=False)
