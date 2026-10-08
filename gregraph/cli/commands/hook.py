"""``gregraph hook pre-commit`` (spec §13.22, §7.5): the hidden hook body.

Invoked by the Git hook installed by ``gregraph hooks install`` (spec §12.3);
hidden from ``--help``. Runs the §7.5 reconcile pass over the staged scope
(mode ``bump``), prints the report with the exact ``gregraph link refresh …``
commands, and exits ``1`` when the commit must be aborted — validation
errors, newly outdated links under ``versioning.on_outdated_links = block``,
open conflicts under ``graph.open_conflicts = block`` on the baseline branch,
or ``W-CR-MODIFIED-AFTER-DECISION`` under ``versioning.on_cr_modified =
block``. Warnings never abort; drift and scope changes never abort
(BOOT-128, BOOT-303). Thin: parse →
:func:`gregraph.core.operations.hook_pre_commit` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.main import App, UsageError
from gregraph.core.operations import hook_pre_commit
from gregraph.core.versioning import Freshness


def run(args: argparse.Namespace, app: App) -> int:
    if getattr(args, "hook_cmd", None) != "pre-commit":
        raise UsageError("hook takes exactly one subcommand: pre-commit")
    workspace = app.open_workspace()
    result = hook_pre_commit(workspace)
    out = app.out
    for notice in result.notices:
        out.note(notice)
    for doc_id in result.bumped:
        out.line(f"bumped {doc_id}")
    _print_freshness(app, "newly outdated links", result.newly_outdated, fixes=True)
    _print_freshness(
        app, "previously outdated links", result.previously_outdated, fixes=False
    )
    _print_freshness(app, "stale links", result.stale, fixes=False)
    _print_freshness(app, "pending-outdated links", result.pending, fixes=False)
    out.report(result.findings)
    if result.blocked:
        for reason in result.block_reasons:
            out.error(f"commit blocked: {reason}")
        return 1
    return 0


def _print_freshness(
    app: App, label: str, entries: tuple[Freshness, ...], *, fixes: bool
) -> None:
    if not entries:
        return
    app.out.line(f"{label}:")
    for entry in entries:
        app.out.line(
            f"  {entry.source}  {entry.type}  {entry.target}  "
            f"target_version {entry.link_target_version} < {entry.target_version}"
        )
        if fixes:
            app.out.line(
                f"    gregraph link refresh {entry.source} {entry.type} {entry.target}"
            )
