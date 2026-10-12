"""``gregraph edit`` (spec §13.23): open the Markdown in ``$VISUAL``/``$EDITOR``.

Convenience only; the ID is prompted with a picker when missing and
interactive. Thin: parse → :func:`gregraph.core.operations.edit_document`.
"""

from __future__ import annotations

import argparse

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick
from gregraph.core.operations import edit_document


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    doc_id = args.id
    if doc_id is None:
        if not app.interactive:
            raise UsageError("missing document ID (pass ID or drop --no-input)")
        picked = pick(
            "pick a document",
            document_pick_rows(workspace),
            stdout=app.out.stdout,
        )
        if picked is None:
            raise UsageError("cancelled: no document selected")
        doc_id = picked.key
    result = edit_document(workspace, doc_id)
    app.out.detail(f"edited {result.id} ({result.body.as_posix()}) via {result.editor}")
    return 0
