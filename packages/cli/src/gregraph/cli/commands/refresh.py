"""``gregraph link refresh`` (spec §13.5): re-confirm ``target_version`` values.

Selection: one edge (``SOURCE TYPE TARGET``), ``--from`` (outbound of one
document), ``--to`` (inbound of one document — the common case after editing
the target) or ``--all``. ``--follow`` re-points stale links to the end of the
supersedes chain (a fork refuses ``E-SUPERSEDE-FORK``); without it stale links
are offered interactively (immediate chain leaves) or reported untouched.
``--dry-run`` reports without writing. Thin: parse →
:func:`gregraph.core.operations.link_refresh` (+ ``link``/``unlink`` for the
interactive re-point) → format.
"""

from __future__ import annotations

import argparse
from typing import Any, cast

from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import PickRow, pick
from gregraph.core.models import LinkType
from gregraph.core.operations import (
    RefreshResult,
    StaleLink,
    link,
    link_refresh,
    unlink,
)
from gregraph.core.validation import report_payload
from gregraph.core.workspace import Workspace

#: Edge types never re-pointed by refresh (spec §7.6, §11.2, D-S12 (3)).
_NEVER_REPOINT = frozenset({"supersedes", "conflicts-with"})

#: Why a link is stale (§13.5): its target was superseded.
_STALE_REASON = "superseded"


def _link_rows(workspace: Workspace) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for source in sorted(workspace.index.documents):
        for entry in workspace.index.documents[source].model.links:
            rows.append((source, entry.type, entry.target))
    return rows


def _pick_link(app: App, workspace: Workspace) -> tuple[str, str, str] | None:
    rows = [
        PickRow(key=f"{source} {edge_type} {target}", type=edge_type, title=target)
        for source, edge_type, target in _link_rows(workspace)
    ]
    picked = pick("pick a link to refresh", rows, stdout=app.out.stdout)
    if picked is None:
        return None
    source, edge_type, target = picked.key.split(" ")
    return source, edge_type, target


def _successor_choices(entry: StaleLink, workspace: Workspace) -> list[str]:
    """The chain leaves offered interactively (D-S12 (3): core never prompts)."""
    chain = entry.chain
    if chain.end is not None:
        return [chain.end]
    return list(chain.fork_successors)


def _repoint(
    workspace: Workspace, source: str, edge_type: LinkType, old: str, new: str
) -> str:
    """Re-point one stale edge to a chosen successor via ``link`` + ``unlink``.

    A duplicate successor edge just drops the stale edge (mirroring
    ``--follow``); ``link`` runs the rule/cycle checks first so a refusal
    leaves the stale edge untouched.
    """
    created = link(workspace, source=source, link_type=edge_type, target=new).created
    unlink(workspace, source=source, link_type=edge_type, target=old)
    if created:
        return f"re-pointed {source} {edge_type} {old} → {new}"
    return f"{source} already has {edge_type} → {new}; removed the stale edge to {old}"


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    source = args.source
    link_type = args.type
    target = args.target
    edge_given = source is not None or link_type is not None or target is not None
    modes = (
        int(edge_given)
        + int(args.from_id is not None)
        + int(args.to_id is not None)
        + int(args.all)
    )
    if modes > 1:
        raise UsageError(
            "use exactly one of: SOURCE TYPE TARGET, --from ID, --to ID, --all"
        )
    if edge_given and not (source and link_type and target):
        raise UsageError("link refresh by edge needs SOURCE TYPE TARGET")
    if modes == 0:
        if not app.interactive:
            raise UsageError("specify SOURCE TYPE TARGET, --from ID, --to ID, or --all")
        picked = _pick_link(app, workspace)
        if picked is None:
            raise UsageError("cancelled: no link selected")
        source, link_type, target = picked

    result = link_refresh(
        workspace,
        source=source,
        link_type=cast("LinkType", link_type) if link_type is not None else None,
        target=target,
        from_id=args.from_id,
        to_id=args.to_id,
        select_all=args.all,
        follow=args.follow,
        dry_run=args.dry_run,
    )
    if app.out.json_mode:
        # The interactive re-point of stale links cannot be part of a
        # machine-readable call; stale links travel in the payload instead.
        app.out.json(_payload(app, result))
        return 0
    _print_refreshed(app, result)
    _handle_stale(app, workspace, result)
    return 0


def _payload(app: App, result: RefreshResult) -> dict[str, Any]:
    """The ``link refresh --json`` payload (AGENT_READINESS §2.4.2)."""
    return {
        "refreshed": [
            {
                "source": entry.source,
                "type": entry.type,
                "old_target": entry.old_target,
                "new_target": entry.new_target,
                "old_target_version": entry.old_target_version,
                "new_target_version": entry.new_target_version,
                "repointed": entry.repointed,
            }
            for entry in result.refreshed
        ],
        "stale": [_stale_payload(entry) for entry in result.stale],
        "dry_run": result.dry_run,
        "findings": report_payload(result.findings),
        "notices": [*app.recorded_notes, *result.notices],
    }


def _stale_payload(entry: StaleLink) -> dict[str, Any]:
    return {
        "source": entry.source,
        "type": entry.type,
        "target": entry.target,
        "reason": _STALE_REASON,
        "chain": list(entry.chain.path),
        "fork_at": entry.fork_at,
        "fork_successors": list(entry.fork_successors),
    }


def _print_refreshed(app: App, result: RefreshResult) -> None:
    for notice in result.notices:
        app.out.warn(notice)
    for finding in result.findings:
        app.out.finding(finding)
    for entry in result.refreshed:
        verb = "re-pointed" if entry.repointed else "refreshed"
        if entry.repointed:
            detail = f"{entry.old_target} → {entry.new_target}"
        else:
            detail = (
                f"target_version {entry.old_target_version} → "
                f"{entry.new_target_version}"
            )
        app.out.line(f"{verb}: {entry.source} {entry.type} {detail}")
    if result.dry_run:
        app.out.line("dry run: nothing written")


def _handle_stale(app: App, workspace: Workspace, result: RefreshResult) -> None:
    for entry in result.stale:
        label = f"{entry.source} {entry.type} → {entry.target}"
        choices = _successor_choices(entry, workspace)
        if result.dry_run:
            app.out.line(
                f"stale: {label} (target superseded; successor(s): "
                f"{', '.join(choices) or 'none'})"
            )
            continue
        if entry.type in _NEVER_REPOINT or not choices:
            app.out.line(f"stale: {label} (target superseded; not auto-repointed)")
            continue
        if not app.interactive:
            app.out.line(
                f"stale: {label} (target superseded; successor(s): "
                f"{', '.join(choices)} — run interactively or with --follow)"
            )
            continue
        rows = [
            PickRow(
                key=choice,
                type=workspace.index.documents[choice].model.type,
                title=workspace.index.documents[choice].model.title,
                status="",
            )
            for choice in choices
            if choice in workspace.index.documents
        ]
        picked = pick(
            f"re-point {label} (target superseded) to",
            rows,
            stdout=app.out.stdout,
        )
        if picked is None:
            app.out.line(f"stale: {label} left untouched")
            continue
        app.out.line(
            _repoint(
                workspace,
                entry.source,
                entry.type,
                entry.target,
                picked.key,
            )
        )
