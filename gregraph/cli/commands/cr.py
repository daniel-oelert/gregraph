"""``gregraph cr``: change requests.

CRs are first-class entities outside the graph with scope, base
versions, origin tracking and a decision history. Commands refuse
``E-CR-DISABLED`` while ``cr.enabled = false``. ``show`` is the §9.8 impact
view; ``list`` filters on proposed/effective status, pending decisions or
drift. Thin: parse → ``gregraph.core.operations.cr_*`` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.commands.term import open_editor
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import prompt_text
from gregraph.core.changes import (
    CrDecisionResult,
    CrShowResult,
)
from gregraph.core.operations import (
    cr_list,
    cr_new,
    cr_reaffirm,
    cr_reanalyze,
    cr_scope_add,
    cr_scope_remove,
    cr_set,
    cr_show,
)
from gregraph.core.workspace import Workspace


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "cr_cmd", None)
    if command == "new":
        return _new(args, app, workspace)
    if command == "scope":
        return _scope(args, app, workspace)
    if command == "set":
        return _set(args, app, workspace)
    if command == "reaffirm":
        return _reaffirm(app, workspace, args.cr)
    if command == "reanalyze":
        return _reanalyze(app, workspace, args.cr, args.targets)
    if command == "list":
        return _list(args, app, workspace)
    if command == "show":
        return _show(app, workspace, args.cr)
    raise UsageError(
        "cr takes exactly one subcommand: new, scope, set, reaffirm, reanalyze, "
        "list, show"
    )


def _new(args: argparse.Namespace, app: App, workspace: Workspace) -> int:
    title = args.title
    if title is None:
        if not app.interactive:
            raise UsageError("missing title (pass --title or drop --no-input)")
        title = prompt_text("title", required=True, stdout=app.out.stdout)
        if title is None:
            raise UsageError("cancelled: no title given")
    result = cr_new(
        workspace,
        title=title,
        scope=args.scope,
        external_ref=args.external_ref,
    )
    out = app.out
    for finding in result.findings:
        out.finding(finding)
    for notice in result.notices:
        out.warn(notice)
    out.line(f"created {result.id}  {result.body.as_posix()}  status {result.status}")
    for entry in result.scope:
        out.line(
            f"  scope: {entry.id}  intent={entry.intent}  base={entry.base_version}"
        )
    if args.edit:
        open_editor(app, workspace.root, result.body)
    return 0


def _scope(args: argparse.Namespace, app: App, workspace: Workspace) -> int:
    sub = getattr(args, "scope_cmd", None)
    if sub == "add":
        result = cr_scope_add(
            workspace, cr_id=args.cr, target=args.target, intent=args.intent
        )
    elif sub == "remove":
        result = cr_scope_remove(workspace, cr_id=args.cr, target=args.target)
    else:
        raise UsageError("cr scope takes exactly one subcommand: add, remove")
    out = app.out
    for notice in result.notices:
        out.warn(notice)
    if result.changed:
        out.line(f"{result.id} scope updated (version {result.version}):")
        for entry in result.scope:
            out.line(f"  {entry.id}  intent={entry.intent}  base={entry.base_version}")
    return 0


def _set(args: argparse.Namespace, app: App, workspace: Workspace) -> int:
    if not args.assignments:
        raise UsageError("missing key=value assignments")
    result = cr_set(workspace, cr_id=args.cr, assignments=args.assignments)
    out = app.out
    for notice in result.notices:
        out.warn(notice)
    if result.decision is not None:
        decision = result.decision
        who = decision.by.name if decision.by is not None else "?"
        out.line(
            f"{result.id}  status {result.status}  (decision by {who} at "
            f"v{decision.at_version})"
        )
    elif result.changed:
        out.line(f"{result.id} updated  status {result.status}")
    else:
        out.line(f"{result.id} unchanged  status {result.status}")
    return 0


def _reaffirm(app: App, workspace: Workspace, cr_id: str) -> int:
    result = cr_reaffirm(workspace, cr_id=cr_id)
    for notice in result.notices:
        app.out.warn(notice)
    _print_decision(app, result)
    return 0


def _print_decision(app: App, result: CrDecisionResult) -> None:
    decision = result.decision
    if decision is None:
        app.out.line(f"{result.id}  status {result.status}")
        return
    who = decision.by.name if decision.by is not None else "?"
    app.out.line(
        f"{result.id}  status {result.status}  reaffirmed at v{decision.at_version} "
        f"by {who}"
    )


def _reanalyze(app: App, workspace: Workspace, cr_id: str, targets: list[str]) -> int:
    result = cr_reanalyze(workspace, cr_id=cr_id, targets=targets)
    out = app.out
    for notice in result.notices:
        out.warn(notice)
    if result.changed:
        out.line(f"{result.id} base versions refreshed (version {result.version}):")
        for entry in result.scope:
            out.line(f"  {entry.id}  intent={entry.intent}  base={entry.base_version}")
    else:
        out.line(f"{result.id} unchanged (base versions already current)")
    return 0


def _list(args: argparse.Namespace, app: App, workspace: Workspace) -> int:
    result = cr_list(
        workspace,
        statuses=args.status,
        effective=args.effective,
        pending=args.pending,
        drift=args.drift,
    )
    app.out.table(
        ["ID", "STATUS", "EFFECTIVE", "PENDING", "DRIFT", "TITLE"],
        [
            [
                entry.id,
                entry.status,
                entry.effective,
                "yes" if entry.pending else "",
                "yes" if entry.drift else "",
                entry.title,
            ]
            for entry in result.entries
        ],
    )
    return 0


def _show(app: App, workspace: Workspace, cr_id: str) -> int:
    _print_show(app, cr_show(workspace, cr_id))
    return 0


def _print_show(app: App, result: CrShowResult) -> None:
    out = app.out
    out.line(f"{result.id}  {result.title}")
    fields: dict[str, str] = {
        "status": f"{result.status} (effective: {result.effective})"
    }
    if result.branch:
        fields["branch"] = result.branch
    if result.external_ref:
        fields["external_ref"] = result.external_ref
    if result.tags:
        fields["tags"] = ", ".join(result.tags)
    for name, value in sorted(result.extra.items()):
        fields[f"extra.{name}"] = value
    out.mapping_lines(fields)
    out.line("  decisions:")
    for decision in result.decisions:
        who = decision.by.name if decision.by is not None else "?"
        stamp = decision.at.isoformat().replace("+00:00", "Z")
        out.line(f"    {decision.status}  {stamp}  by {who}  at v{decision.at_version}")
    out.line("  scope:")
    for entry in result.scope:
        out.line(
            f"    {entry.id}  intent={entry.intent}  base={entry.base_version}  "
            f"baseline={entry.baseline_version}  working={entry.working_version}  "
            f"live={entry.live}  drift={'yes' if entry.drift else 'no'}"
        )
    if result.introduces:
        out.line("  introduces:")
        for introduced in result.introduces:
            out.line(f"    {introduced.doc_id}  status={introduced.status}")
    if result.impact:
        out.line("  impact:")
        for item in result.impact:
            out.line(f"    {item}")
