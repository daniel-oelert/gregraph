"""``gregraph check`` (spec §13.8): the pre-commit hook simulation.

Runs the §7.5 reconcile in report mode over all working-tree changes (staged
or not) and exits 1 iff the hook would block: any validation error; newly
outdated links when ``versioning.on_outdated_links = "block"``; open conflicts
on the baseline branch when ``graph.open_conflicts = "block"``; change
requests modified after their last decision when ``versioning.on_cr_modified =
"block"``. Warnings never block. Thin: parse →
:func:`gregraph.core.operations.check` → format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.main import App
from gregraph.core.operations import CheckResult, check
from gregraph.core.validation import report_payload


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    result = check(workspace)
    if app.out.json_mode:
        app.out.json(_payload(result))
    else:
        _print_report(app, result)
    return 1 if result.blocked else 0


def _refresh_command(entry: Any) -> str:
    return f"gregraph link refresh {entry.source} {entry.type} {entry.target}"


def _payload(result: CheckResult) -> dict[str, Any]:
    return {
        "blocked": result.blocked,
        "block_reasons": list(result.block_reasons),
        "would_bump": list(result.would_bump),
        "findings": report_payload(result.findings),
        "newly_outdated": [
            {
                "source": entry.source,
                "type": entry.type,
                "target": entry.target,
                "target_version": entry.link_target_version,
                "new_version": entry.effective,
                "fix": _refresh_command(entry),
            }
            for entry in result.newly_outdated
        ],
    }


def _print_report(app: App, result: CheckResult) -> None:
    out = app.out
    out.report(result.findings)
    for entry in result.newly_outdated:
        out.line(
            f"newly outdated: {entry.source} {entry.type} → {entry.target} "
            f"(target_version {entry.link_target_version} → {entry.effective})  "
            f"fix: {_refresh_command(entry)}"
        )
    for entry in result.stale:
        out.line(f"stale: {entry.source} {entry.type} → {entry.target}")
    if result.pending:
        out.line(f"pending-outdated: {len(result.pending)} link(s)")
    if result.blocked:
        out.line(f"check: blocked ({'; '.join(result.block_reasons)})")
    else:
        out.line("check: ok")
