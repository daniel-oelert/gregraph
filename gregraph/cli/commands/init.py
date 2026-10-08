"""``gregraph init`` (spec §13.1): create a requirements repository.

Layout per spec §3; built-in templates copied per spec §5.5; ``git init`` and
pre-commit hook installation unless ``--no-git``. Thin: parse →
:func:`gregraph.core.operations.init_repository` → format.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gregraph.cli.main import App
from gregraph.core.operations import init_repository


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
    app.out.line(f"initialised gregraph repository at {result.root}")
    app.out.line(f"templates copied: {', '.join(result.templates)}")
    if result.git_initialised:
        app.out.line("git repository created")
    if result.hooks_installed:
        app.out.line("pre-commit hook installed")
    return 0
