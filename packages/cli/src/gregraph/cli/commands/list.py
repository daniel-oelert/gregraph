"""``gregraph list`` (spec §13.10, AGENT_READINESS §6.3): tabular listing.

Columns ID, type, status, version, title; ``--json`` emits the sidecars plus
derived fields; ``--body`` adds the full Markdown text to each ``--json``
item (the human table is unchanged). Thin: parse →
:func:`gregraph.core.operations.list_documents` → format (tables/JSON in
:mod:`gregraph.cli.output`).
"""

from __future__ import annotations

import argparse

from gregraph.cli.main import App
from gregraph.cli.output import document_payload
from gregraph.core.operations import list_documents


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    include_body = bool(getattr(args, "body", False))
    result = list_documents(
        workspace,
        type_names=args.type,
        kinds=args.kind,
        statuses=args.status,
        tags=args.tag,
        roots=args.roots,
        orphans=args.orphans,
        outdated=args.outdated,
        stale=args.stale,
        deprecated_templates=args.deprecated_templates,
        sort=args.sort,
        include_body=include_body,
    )
    if app.out.json_mode:
        rows = [
            document_payload(row.document, status=row.status, kind=row.kind)
            for row in result.rows
        ]
        if include_body:
            for row, payload in zip(result.rows, rows, strict=True):
                payload["body"] = row.body
        app.out.json(rows)
        return 0
    app.out.table(
        ["ID", "TYPE", "STATUS", "VERSION", "TITLE"],
        [
            [row.id, row.type, row.status, str(row.version), row.title]
            for row in result.rows
        ],
    )
    return 0
