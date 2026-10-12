"""``gregraph unlink`` (spec §13.4): remove one edge.

Symmetric edges are found on either endpoint. Prompts for source, type and
target when interactive (pickers over the source's stored edges). Thin:
parse → :func:`gregraph.core.operations.unlink` → format.
"""

from __future__ import annotations

import argparse
from typing import cast

from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import PickRow, pick
from gregraph.core.models import LinkType
from gregraph.core.operations import unlink
from gregraph.core.rules import SYMMETRIC_EDGE_TYPES
from gregraph.core.workspace import Workspace


def _edge_rows(workspace: Workspace, source: str) -> list[tuple[str, str, str]]:
    """``(source, type, target)`` of every edge the given node stores or owns."""
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in workspace.graph.edges_of(source):
        if edge.source == source:
            key = (edge.source, edge.type, edge.target)
        elif edge.type in SYMMETRIC_EDGE_TYPES:
            key = (source, edge.type, edge.source)
        else:
            continue
        if key not in seen:
            seen.add(key)
            rows.append(key)
    return sorted(rows)


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    source = args.source
    link_type = args.type
    target = args.target

    if source is None or link_type is None or target is None:
        if not app.interactive:
            raise UsageError("unlink needs SOURCE TYPE TARGET (or drop --no-input)")
        if source is None:
            picked = pick(
                "pick the source document",
                [
                    PickRow(key=key, type="", title="", status="")
                    for key in sorted(workspace.index.documents)
                ],
                stdout=app.out.stdout,
            )
            if picked is None:
                raise UsageError("cancelled: no document selected")
            source = picked.key
        edges = [
            row
            for row in _edge_rows(workspace, source)
            if link_type is None or row[1] == link_type
        ]
        if link_type is None:
            type_rows: dict[str, PickRow] = {}
            for _edge_source, edge_type, edge_target in edges:
                type_rows.setdefault(
                    edge_type, PickRow(key=edge_type, title=edge_target, status="")
                )
            picked = pick(
                "pick an edge type",
                [type_rows[name] for name in sorted(type_rows)],
                stdout=app.out.stdout,
            )
            if picked is None:
                raise UsageError("cancelled: no edge type selected")
            link_type = picked.key
            edges = [row for row in edges if row[1] == link_type]
        if target is None:
            picked = pick(
                "pick the target document",
                [
                    PickRow(key=edge_target, type=link_type, title="", status="")
                    for _, _, edge_target in edges
                ],
                stdout=app.out.stdout,
            )
            if picked is None:
                raise UsageError("cancelled: no target selected")
            target = picked.key

    result = unlink(
        workspace,
        source=source,
        link_type=cast("LinkType", link_type),
        target=target,
    )
    if result.notice is not None:
        app.out.warn(result.notice)
    if result.removed:
        app.out.line(
            f"removed {result.source} {result.type} → {result.target} "
            f"(from {result.removed_from})"
        )
    return 0
