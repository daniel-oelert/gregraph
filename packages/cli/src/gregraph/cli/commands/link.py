"""``gregraph link`` (spec §13.3, AGENT_READINESS §4.3): add an edge.

Interactive flow: pick the source (all nodes), pick the edge type (filtered to
types whose source-kind rule the source satisfies), pick the target (kind rule,
not deprecated/superseded, cycle candidates precomputed and excluded — §13.3).
The filtering lives in :func:`gregraph.core.operations.link_candidates` so the
picker and ``link --candidates`` share one source of truth. Refusals
(``E-CYCLE``, ``E-EDGE-RULE``, ``E-TARGET-SUPERSEDED``,
``E-TARGET-DEPRECATED``, ``E-EDGE-EXCLUSIVE``, …) exit 4; a duplicate is a
no-op notice (exit 0). ``link --candidates SRC [--type EDGE_TYPE]`` lists the
admissible (type, target) pairs without writing. ``link --help`` prints the
§6.1 edge guidelines (the parser epilog in :mod:`gregraph.cli.main`). Thin:
parse → :func:`gregraph.core.operations.link` /
:func:`gregraph.core.operations.link_candidates` → format.
"""

from __future__ import annotations

import argparse
import dataclasses
from typing import cast

from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import PickRow, pick
from gregraph.core.ids import normalise_id
from gregraph.core.models import Finding, LinkType, OperationRefused
from gregraph.core.operations import (
    LinkResult,
    link,
    link_candidates,
)
from gregraph.core.rules import EDGE_RULES
from gregraph.core.validation import report_payload
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
    """Pickable edge types: the §6.1 kind rule, via core's ``link_candidates``."""
    result = link_candidates(workspace, source=source_id)
    return [
        PickRow(
            key=edge_type,
            type=EDGE_RULES[edge_type].direction,
            title=_EDGE_HINTS.get(edge_type, ""),
            status="",
        )
        for edge_type in sorted(result.allowed_edge_types)
    ]


def _target_rows(
    workspace: Workspace, source_id: str, edge_type: LinkType
) -> list[PickRow]:
    """Pickable targets: kind rule, live, and no cycle back to the source.

    Cycle candidates are precomputed (spec §13.3) via
    :meth:`gregraph.core.graph.Graph.check_link` and excluded from the picker;
    the filter is core's ``link_candidates`` (AGENT_READINESS §4.3).
    """
    result = link_candidates(workspace, source=source_id, edge_type=edge_type)
    return [
        PickRow(
            key=candidate.target,
            type=candidate.target_type,
            title=candidate.target_title,
            status="",
        )
        for candidate in result.candidates
    ]


def _run_candidates(args: argparse.Namespace, app: App) -> int:
    """``link --candidates SRC [--type EDGE_TYPE]`` (AGENT_READINESS §4.3)."""
    workspace = app.open_workspace()
    # §4.3: mutually exclusive with positional TARGET *and* positional TYPE;
    # ``--type`` (``candidate_type``) is the only type filter in this mode.
    if args.type is not None or args.target is not None:
        raise UsageError("link --candidates takes <SOURCE_ID> [--type EDGE_TYPE] only")
    source = args.source
    if source is None:
        raise UsageError("link --candidates requires a SOURCE_ID")
    edge_type = getattr(args, "candidate_type", None)
    try:
        result = link_candidates(workspace, source=source, edge_type=edge_type)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    if app.out.json_mode:
        app.out.json(
            {
                "source": result.source,
                "source_kind": result.source_kind,
                "allowed_edge_types": list(result.allowed_edge_types),
                "candidates": [
                    dataclasses.asdict(candidate) for candidate in result.candidates
                ],
            }
        )
        return 0
    if not result.candidates:
        app.out.line("no candidates")
        return 0
    for candidate in result.candidates:
        app.out.line(
            f"{candidate.type}  {candidate.target}  {candidate.target_type}  "
            f"({candidate.target_kind})  {candidate.target_title}"
        )
    return 0


def run(args: argparse.Namespace, app: App) -> int:
    if getattr(args, "candidates", False):
        return _run_candidates(args, app)
    if getattr(args, "candidate_type", None) is not None:
        raise UsageError("--type is only valid with --candidates")
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
            _target_rows(workspace, source_id, edge_type),
            stdout=app.out.stdout,
        )
        if picked is None:
            raise UsageError("cancelled: no target selected")
        target = picked.key

    return _finish(
        app, link(workspace, source=source_id, link_type=edge_type, target=target)
    )


def _target_version(result: LinkResult) -> int | None:
    """The recorded ``target_version`` (§2.4.2); ``None`` on the duplicate no-op.

    ``LinkResult`` carries it on the created :class:`~gregraph.core.models.Link`;
    the duplicate no-op writes nothing and has no edge.
    """
    return result.link.target_version if result.link is not None else None


def _finish(app: App, result: LinkResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "source": result.source,
                "type": result.type,
                "target": result.target,
                "created": result.created,
                "target_version": _target_version(result),
                "notice": result.notice,
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
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
