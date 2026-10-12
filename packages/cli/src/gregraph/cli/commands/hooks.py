"""``gregraph hooks`` (spec §13.22, §12.3): manage the Git pre-commit hook.

``install`` writes or refreshes ``.git/hooks/pre-commit`` (appending a clearly
delimited block to an existing hook), ``uninstall`` removes the block, and
``status`` reports whether the hook is installed and up to date. Thin: parse →
``gregraph.core.operations.hooks_*`` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.main import App, UsageError
from gregraph.core.hooks import HookStatus
from gregraph.core.operations import hooks_install, hooks_status, hooks_uninstall


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "hooks_cmd", None)
    if command == "install":
        hooks_install(workspace)
        app.out.line("pre-commit hook installed")
        return 0
    if command == "uninstall":
        hooks_uninstall(workspace)
        app.out.line("pre-commit hook uninstalled")
        return 0
    if command == "status":
        if not workspace.git.is_repo():
            app.note("not a git repository — hooks unavailable")
        _report_status(app, hooks_status(workspace))
        return 0
    raise UsageError("hooks takes exactly one subcommand: install, uninstall, status")


def _report_status(app: App, status: HookStatus) -> None:
    if not status.installed:
        app.out.line("pre-commit hook: not installed")
    elif status.up_to_date:
        app.out.line("pre-commit hook: installed and up to date")
    else:
        app.out.line("pre-commit hook: installed but out of date")
        app.out.line("run `gregraph hooks install` to refresh it")
