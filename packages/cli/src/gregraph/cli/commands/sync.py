"""``gregraph sync`` (spec §13.7): reconcile all per §7.5.

Bumps versions in degraded mode or with ``--bump``; otherwise reports what
``--bump`` would record. Also normalises body line endings, rewrites sidecars
whose serialisation is not canonical and rebuilds the index cache (§16.5).
Thin: parse → :func:`gregraph.core.operations.sync` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.main import App
from gregraph.core.operations import SyncResult, sync


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    result = sync(workspace, bump=args.bump)
    _print_report(app, result)
    return 0


def _print_report(app: App, result: SyncResult) -> None:
    out = app.out
    if result.bumped:
        out.line(f"bumped {len(result.bumped)}: {', '.join(result.bumped)}")
    elif result.mode == "bump":
        out.line("sync: nothing to bump")
    if result.mode == "report" and result.changed:
        out.line(
            f"sync: {len(result.changed)} change(s) pending "
            f"({', '.join(result.changed)}); run with --bump to record versions"
        )
    if result.normalised:
        out.line(f"normalised {len(result.normalised)} body/bodies")
    if result.rewritten:
        out.line(f"rewrote {len(result.rewritten)} sidecar(s)")
    for entry in result.newly_outdated:
        command = f"gregraph link refresh {entry.source} {entry.type} {entry.target}"
        out.line(
            f"newly outdated: {entry.source} {entry.type} → {entry.target} "
            f"(target_version {entry.link_target_version} → {entry.effective})  "
            f"fix: {command}"
        )
    out.line(
        "links: "
        f"{len(result.newly_outdated)} newly outdated, "
        f"{len(result.previously_outdated)} outdated, "
        f"{len(result.stale)} stale, "
        f"{len(result.pending)} pending-outdated"
    )
    out.report(result.findings)
