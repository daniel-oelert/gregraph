"""``gregraph init`` (spec §13.1, AGENT_READINESS §2.4.3, §7.1): create a repo.

Layout per spec §3; built-in templates copied per spec §5.5; ``git init`` and
pre-commit hook installation unless ``--no-git``; the agent instruction files
``AGENTS.md`` and ``.agents/skills/gregraph/SKILL.md`` are written and
reported (Pillar 6, AGENT-031). ``--json`` emits ``{root, created, templates,
git_initialised, hooks_installed, agents_files, findings, notices}``. Thin:
parse → :func:`gregraph.core.operations.init_repository` → format.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from gregraph.cli.main import App
from gregraph.core.operations import InitResult, init_repository
from gregraph.core.validation import report_payload


def run(args: argparse.Namespace, app: App) -> int:
    result = init_repository(
        Path(args.path),
        prefix=args.prefix,
        baseline_branch=args.baseline_branch,
        templates=args.templates,
        no_git=args.no_git,
    )
    for notice in result.notices:
        app.out.warn(notice)
    if app.out.json_mode:
        app.out.json(_payload(app, result))
        return 0
    app.out.line(f"initialised gregraph repository at {result.root}")
    app.out.line(f"templates copied: {', '.join(result.templates)}")
    if result.git_initialised:
        app.out.line("git repository created")
    if result.hooks_installed:
        app.out.line("pre-commit hook installed")
    if result.agents_files:
        # §7.1 item 3: report both agent instruction files in human mode.
        app.out.line(
            f"agents files written: "
            f"{', '.join(path.as_posix() for path in result.agents_files)}"
        )
    return 0


def _payload(app: App, result: InitResult) -> dict[str, Any]:
    """The ``init --json`` payload (§2.4.3) with the Pillar 6 file list."""
    return {
        "root": result.root.as_posix(),
        "created": [path.as_posix() for path in result.created],
        "templates": list(result.templates),
        "git_initialised": result.git_initialised,
        "hooks_installed": result.hooks_installed,
        "agents_files": [path.as_posix() for path in result.agents_files],
        "findings": report_payload(result.findings),
        "notices": [*app.recorded_notes, *result.notices],
    }
