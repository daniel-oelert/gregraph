"""``gregraph hooks`` (spec §13.22, §12.3, AGENT_READINESS §2.4.3): Git hooks.

``install`` writes or refreshes ``.git/hooks/pre-commit`` (appending a clearly
delimited block to an existing hook), ``uninstall`` removes the block, and
``status`` reports whether the hook is installed and up to date. Every
subcommand supports ``--json`` with the same payload shape. Thin: parse →
``gregraph.core.operations.hooks_*`` → format.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from gregraph.cli.main import App, UsageError
from gregraph.core.hooks import HookStatus
from gregraph.core.operations import hooks_install, hooks_status, hooks_uninstall

#: The managed hook's repository-relative path (spec §12.3); the payload's
#: ``path`` (§2.4.3). Core owns the absolute write; the CLI reports the shape.
_HOOK_RELPATH = Path(".git") / "hooks" / "pre-commit"


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "hooks_cmd", None)
    if command == "install":
        status = hooks_install(workspace)
        return _finish(app, status, "pre-commit hook installed")
    if command == "uninstall":
        status = hooks_uninstall(workspace)
        return _finish(app, status, "pre-commit hook uninstalled")
    if command == "status":
        if not workspace.git.is_repo():
            # ``App.note`` wraps the feature name in the degraded-mode note.
            app.note("hooks")
        status = hooks_status(workspace)
        return _finish(app, status, None)
    raise UsageError("hooks takes exactly one subcommand: install, uninstall, status")


def _finish(app: App, status: HookStatus, human_line: str | None) -> int:
    if app.out.json_mode:
        app.out.json(_payload(app, status))
        return 0
    if human_line is not None:
        app.out.line(human_line)
    else:
        _report_status(app, status)
    return 0


def _payload(app: App, status: HookStatus) -> dict[str, Any]:
    """The ``hooks … --json`` payload (§2.4.3); the same shape for all three
    subcommands."""
    return {
        "hook": "pre-commit",
        "path": _HOOK_RELPATH.as_posix(),
        "installed": status.installed,
        "up_to_date": status.up_to_date,
        "findings": [],
        "notices": list(app.recorded_notes),
    }


def _report_status(app: App, status: HookStatus) -> None:
    if not status.installed:
        app.out.line("pre-commit hook: not installed")
    elif status.up_to_date:
        app.out.line("pre-commit hook: installed and up to date")
    else:
        app.out.line("pre-commit hook: installed but out of date")
        app.out.line("run `gregraph hooks install` to refresh it")
