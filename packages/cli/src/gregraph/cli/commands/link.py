"""``gregraph link`` (spec §13.3): add one edge.

Interactive flow: pick the source (all nodes), pick the edge type (filtered to
types whose source-kind rule the source satisfies), pick the target (kind rule,
not deprecated/superseded, cycle candidates precomputed and excluded — §13.3).
Refusals (``E-CYCLE``, ``E-EDGE-RULE``, ``E-TARGET-SUPERSEDED``,
``E-TARGET-DEPRECATED``, ``E-EDGE-EXCLUSIVE``, …) exit 4; a duplicate is a
no-op notice (exit 0). ``link --help`` prints the §6.1 edge guidelines (the
parser epilog in :mod:`gregraph.cli.main`). Thin: parse →
:func:`gregraph.core.operations.link` → format.
"""

from __future__ import annotations

import argparse
from typing import cast

from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import PickRow, pick
from gregraph.core.ids import normalise_id
from gregraph.core.models import Finding, LinkType, OperationRefused
from gregraph.core.operations import LinkResult, link
from gregraph.core.rules import EDGE_RULES, Kind, edge_kind_allowed
from gregraph.core.workspace import Workspace

#: Short §6.1 guidance shown in the type picker's title column.
_EDGE_HINTS: dict[str, str] = {
    "refines": "more concrete version of the target (decomposition)",
    "derives-from": "new requirement caused by the target",
    "depends-on": "source cannot be built before the target",
    "satisfies": "design realises the target",
    "verifies": "verification evidence for the target",
    "constrains": "cross-cutting constraint on the target",
    "supersedes": "source replaces the target",
    "conflicts-with": "the two cannot both be satisfied as written",
    "relates-to": "weak association (last resort)",
}


def _unknown_source(raw: str) -> OperationRefused:
    return OperationRefused(
        Finding(
            code="E-ID-UNKNOWN",
            severity="E",
            subject=raw,
            message=f"no document with id {raw!r}",
            fix="gregraph list",
        )
    )


def _resolve_source(workspace: Workspace, raw: str) -> str:
    resolved = normalise_id(
        raw, workspace.config.ids.prefix, known=workspace.index.documents
    )
    if resolved is None:
        raise _unknown_source(raw)
    return resolved


def _type_rows(workspace: Workspace, source_id: str) -> list[PickRow]:
    kind = workspace.graph.kind_of(source_id)
    rows: list[PickRow] = []
    for edge_type, rule in sorted(EDGE_RULES.items()):
        if kind is not None and kind not in rule.source_kinds:
            continue
        rows.append(
            PickRow(
                key=edge_type,
                type=rule.direction,
                title=_EDGE_HINTS.get(edge_type, ""),
                status="",
            )
        )
    return rows


def _target_rows(
    workspace: Workspace,
    source_id: str,
    edge_type: LinkType,
    source_kind: Kind | None,
) -> list[PickRow]:
    """Pickable targets: kind rule, live, and no cycle back to the source.

    Cycle candidates are precomputed (spec §13.3) via
    :meth:`gregraph.core.graph.Graph.check_link` and excluded from the picker.
    """
    graph = workspace.graph
    rows: list[PickRow] = []
    for target_id in sorted(workspace.index.documents):
        target_kind = graph.kind_of(target_id)
        if source_kind is not None and target_kind is not None:
            if not edge_kind_allowed(edge_type, source_kind, target_kind):
                continue
        loaded = workspace.index.documents[target_id]
        if loaded.model.deprecated is not None or graph.is_superseded(target_id):
            continue
        check = graph.check_link(source_id, edge_type, target_id)
        if (
            check.outcome == "refused"
            and check.refusal is not None
            and check.refusal.code == "E-CYCLE"
        ):
            continue
        rows.append(
            PickRow(
                key=target_id,
                type=loaded.model.type,
                title=loaded.model.title,
                status="",
            )
        )
    return rows


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    source = args.source
    link_type = args.type
    target = args.target

    if source is not None and link_type is not None and target is not None:
        return _finish(
            app,
            link(
                workspace,
                source=source,
                link_type=cast("LinkType", link_type),
                target=target,
            ),
        )

    if not app.interactive:
        raise UsageError(
            "link needs SOURCE TYPE TARGET (or drop --no-input to be prompted)"
        )

    if source is None:
        picked = pick(
            "pick the source document",
            [
                PickRow(
                    key=key,
                    type=workspace.index.documents[key].model.type,
                    title=workspace.index.documents[key].model.title,
                    status="",
                )
                for key in sorted(workspace.index.documents)
            ],
            stdout=app.out.stdout,
        )
        if picked is None:
            raise UsageError("cancelled: no document selected")
        source = picked.key
    source_id = _resolve_source(workspace, source)
    source_kind = workspace.graph.kind_of(source_id)

    if link_type is None:
        picked = pick(
            "pick the edge type",
            _type_rows(workspace, source_id),
            stdout=app.out.stdout,
        )
        if picked is None:
            raise UsageError("cancelled: no edge type selected")
        link_type = picked.key
    if link_type not in EDGE_RULES:
        raise UsageError(f"unknown edge type: {link_type!r}")
    edge_type = cast("LinkType", link_type)

    if target is None:
        picked = pick(
            "pick the target document",
            _target_rows(workspace, source_id, edge_type, source_kind),
            stdout=app.out.stdout,
        )
        if picked is None:
            raise UsageError("cancelled: no target selected")
        target = picked.key

    return _finish(
        app, link(workspace, source=source_id, link_type=edge_type, target=target)
    )


def _finish(app: App, result: LinkResult) -> int:
    if result.notice is not None:
        app.out.line(result.notice)
        return 0
    entry = result.link
    assert entry is not None
    app.out.line(
        f"linked {result.source} {result.type} → {result.target} "
        f"(target_version {entry.target_version})"
    )
    return 0
