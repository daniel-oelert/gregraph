"""``gregraph migrate`` (spec §13.16, §7.7): migrate template versions.

Exactly one selection: document IDs, ``--all`` or ``--template NAME``. Each
selected document is migrated in place when every version step to the target
is non-breaking, or by supersession when a step is breaking or ``--supersede``
is given. ``--dry-run`` prints the plan without writing. Thin: parse →
:func:`gregraph.core.operations.migrate` → plan output.
"""

from __future__ import annotations

import argparse

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick
from gregraph.core.operations import MigrateResult, MigrationItem, migrate
from gregraph.core.workspace import Workspace


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    ids = list(args.ids)
    if not ids and not args.all and args.template is None:
        if not app.interactive:
            raise UsageError(
                "migrate takes exactly one selection: document IDs, --all "
                "or --template NAME"
            )
        ids = _pick_documents(app, workspace)
    result = migrate(
        workspace,
        doc_ids=ids,
        select_all=args.all,
        template=args.template,
        to_version=args.to_version,
        supersede=args.supersede,
        dry_run=args.dry_run,
    )
    _print_plan(app, result)
    return 0


def _pick_documents(app: App, workspace: Workspace) -> list[str]:
    """Interactive document picker (spec §13): repeated picks until ``q``."""
    picked_ids: list[str] = []
    rows = document_pick_rows(workspace)
    while True:
        picked = pick(
            "pick a document to migrate (q to finish)",
            rows,
            stdout=app.out.stdout,
        )
        if picked is None:
            if not picked_ids:
                raise UsageError("cancelled: no document selected")
            return picked_ids
        if picked.key not in picked_ids:
            picked_ids.append(picked.key)


def _print_plan(app: App, result: MigrateResult) -> None:
    out = app.out
    if result.dry_run:
        out.line("dry run: nothing written")
    for item in result.items:
        _print_item(app, item)
    for notice in result.notices:
        out.warn(notice)


def _print_item(app: App, item: MigrationItem) -> None:
    out = app.out
    if item.kind == "skipped":
        out.line(f"{item.id}  skipped")
    else:
        start = f"v{item.from_version}" if item.from_version is not None else "?"
        end = f"v{item.to_version}" if item.to_version is not None else "?"
        line = f"{item.id}  {item.kind}  {start} -> {end}"
        if item.new_id:
            line += f"  (new {item.new_id})"
        out.line(line)
    for old, new in item.renamed:
        out.line(f"  renamed: {old} -> {new}")
    for heading in item.inserted:
        out.line(f"  inserted: {heading}")
    for heading in item.unknown:
        out.line(f"  left in place: {heading}")
    for heading in item.unmapped:
        out.line(f"  unmapped: {heading}")
    for attention in item.manual_attention:
        out.line(f"  manual: {attention}")
    for item_finding in item.findings:
        out.finding(item_finding)
    for notice in item.notices:
        out.warn(notice)
