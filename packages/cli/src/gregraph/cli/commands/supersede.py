"""``gregraph supersede`` (spec §13.14, §7.6): replace one or more documents.

One new document supersedes every target (multi-target = conflict compromise,
§11.2). ``--copy-body`` defaults on when the resolved template matches the
targets', ``--copy-links`` copies their outbound edges, ``--cr`` records the
new document as introduced by that CR (§9.5). Inbound links of the old
documents become stale and are listed with the ``link refresh --follow``
commands that re-point them. Thin: parse →
:func:`gregraph.core.operations.supersede` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick
from gregraph.core.operations import edit_document, supersede
from gregraph.core.workspace import Workspace


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    targets = list(args.old)
    if not targets:
        if not app.interactive:
            raise UsageError("missing supersede target (pass OLD or drop --no-input)")
        targets = _pick_targets(app, workspace)
    result = supersede(
        workspace,
        targets=targets,
        title=args.title,
        type=args.type,
        copy_body=args.copy_body,
        copy_links=args.copy_links,
        cr=args.cr,
    )
    out = app.out
    for finding in result.findings:
        out.finding(finding)
    for notice in result.notices:
        out.warn(notice)
    for finding in result.skipped_links:
        out.finding(finding)
    out.line(f"created {result.id}  {result.body.as_posix()}")
    out.line(f"supersedes: {', '.join(result.supersedes)}")
    if result.stale_inbound:
        out.line("stale inbound links (re-point with link refresh --follow):")
        for item in result.stale_inbound:
            out.line(
                f"  {item.source}  {item.type}  {item.target}  "
                f"target_version {item.target_version}"
            )
            out.line(
                f"    gregraph link refresh {item.source} {item.type} "
                f"{item.target} --follow"
            )
    if args.edit:
        edit_document(workspace, result.id)
    return 0


def _pick_targets(app: App, workspace: Workspace) -> list[str]:
    """Interactive multi-target picker (spec §13): repeated picks until ``q``."""
    targets: list[str] = []
    rows = document_pick_rows(workspace)
    while True:
        picked = pick(
            "pick a document to supersede (q to finish)",
            rows,
            stdout=app.out.stdout,
        )
        if picked is None:
            if not targets:
                raise UsageError("cancelled: no document selected")
            return targets
        if picked.key not in targets:
            targets.append(picked.key)
