"""``gregraph validate`` (spec §13.9): the full validation report.

``--strict`` treats warnings as errors for the exit code; ``--only-errors``
keeps errors in the display report; ``--json`` emits the §14 payload
(``[{code, severity, id|path, message, fix?}]``). Intended for CI. Thin:
parse → :func:`gregraph.core.operations.validate` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.main import App
from gregraph.core.operations import validate as validate_workspace_op
from gregraph.core.validation import report_payload


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    result = validate_workspace_op(
        workspace, strict=args.strict, only_errors=args.only_errors
    )
    if app.out.json_mode:
        app.out.json(report_payload(result.findings))
    else:
        app.out.report(result.findings)
        if app.out.verbose:
            app.out.line(
                f"validate: {result.errors} error(s), {result.warnings} warning(s)"
            )
    return 1 if result.failed else 0
