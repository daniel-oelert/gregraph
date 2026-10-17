"""``gregraph sync`` (spec §13.7, AGENT_READINESS §2.4.3, §3.3): reconcile all.

Bumps versions in degraded mode or with ``--bump``; otherwise reports what
``--bump`` would record. Uncommitted-``v1`` items in the initial-grace state
(§3.3) are *initialised* (version stays ``1``) instead of bumped. Also
normalises body line endings, rewrites sidecars whose serialisation is not
canonical, rebuilds the index cache (§16.5) and refreshes the agent files
(§7.3). ``--json`` emits the full report including the ``initialised`` bucket.
Thin: parse → :func:`gregraph.core.operations.sync` → format.
"""

from __future__ import annotations

import argparse
import dataclasses
from typing import Any

from gregraph.cli.main import App
from gregraph.core.operations import SyncResult, sync
from gregraph.core.validation import report_payload


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    result = sync(workspace, bump=args.bump)
    if app.out.json_mode:
        app.out.json(_payload(app, result))
        return 0
    _print_report(app, result)
    return 0


def _payload(app: App, result: SyncResult) -> dict[str, Any]:
    """The ``sync --json`` payload (§2.4.3) with the Pillar 2B bucket."""
    return {
        "mode": result.mode,
        "bumped": list(result.bumped),
        "initialised": list(result.initialised),
        "changed": list(result.changed),
        "normalised": [path.as_posix() for path in result.normalised],
        "rewritten": [path.as_posix() for path in result.rewritten],
        "agents_files_changed": [
            path.as_posix() for path in result.agents_files_changed
        ],
        "newly_outdated": [
            dataclasses.asdict(entry) for entry in result.newly_outdated
        ],
        "previously_outdated": [
            dataclasses.asdict(entry) for entry in result.previously_outdated
        ],
        "stale": [dataclasses.asdict(entry) for entry in result.stale],
        "pending": [dataclasses.asdict(entry) for entry in result.pending],
        "findings": report_payload(result.findings),
        "notices": [*app.recorded_notes, *result.notices],
    }


def _print_report(app: App, result: SyncResult) -> None:
    out = app.out
    if result.bumped:
        out.line(f"bumped {len(result.bumped)}: {', '.join(result.bumped)}")
    if result.initialised:
        # §3.3: uncommitted-v1 population is reported in its own bucket.
        out.line(
            f"initialised {len(result.initialised)}: {', '.join(result.initialised)}"
        )
    elif result.mode == "bump" and not result.bumped:
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
