"""``gregraph edit`` (spec §13.23, AGENT_READINESS §2.4.1, §3.4): edit a body.

Without content flags the command opens the Markdown in ``$VISUAL``/``$EDITOR``
(prompting for the ID when interactive) — unchanged human behaviour. With
``--section``/``--section-file`` (per-section assembly), ``--body``/
``--body-file`` (whole-body replacement through :func:`~...operations.update_body`,
staleness-guarded by ``base_hash``) or ``--strict`` alone (write-time
required-section check) the write goes through the §21.5 update path and the
sidecar title is synced from the H1. ``edit --json`` without content flags is
refused ``E-USAGE`` (§2.4.1). Thin: parse → ``operations.body_state`` +
``update_body``/``update_sections`` → format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.commands.sections import parse_content_args
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick
from gregraph.core.markdown import extract_title
from gregraph.core.operations import (
    BodyUpdateResult,
    body_state,
    edit_document,
    update_body,
    update_sections,
)
from gregraph.core.templates import prepare_whole_body
from gregraph.core.validation import report_payload
from gregraph.core.workspace import Workspace


def run(args: argparse.Namespace, app: App) -> int:
    content = parse_content_args(args, allow_body=True)
    strict = bool(getattr(args, "strict", False))
    workspace = app.open_workspace()

    if not content.has_content_flags and not strict:
        if app.out.json_mode:
            raise UsageError(
                "edit with --json requires --body, --body-file, --section, "
                "or --section-file"
            )
        return _editor_flow(app, workspace, args.id)

    doc_id = _resolve_id(app, workspace, args.id)
    state = body_state(workspace, doc_id=doc_id)
    if content.body_text is not None:
        # §3.4 rule 8: the sidecar title follows the H1. When the whole-body
        # input already starts with an H1 it is stored as sent; otherwise the
        # tool-owned ``# <title>`` is prepended (notice when it differed).
        if extract_title(content.body_text) is not None:
            text = content.body_text
            notices: list[str] = []
        else:
            text, notices = prepare_whole_body(
                content.body_text,
                title=workspace.index.documents[state.id].model.title,
            )
        res = update_body(
            workspace,
            doc_id=state.id,
            text=text,
            base_hash=state.body_hash,
            strict=strict,
            notices=notices,
        )
    elif content.sections:
        res = update_sections(
            workspace,
            doc_id=state.id,
            content=content.sections,
            base_hash=state.body_hash,
            strict=strict,
        )
    else:
        res = update_body(
            workspace,
            doc_id=state.id,
            text=state.text,
            base_hash=state.body_hash,
            strict=True,
        )
    final = body_state(workspace, doc_id=state.id)
    for finding in res.findings:
        app.out.finding(finding)
    for notice in res.notices:
        app.out.warn(notice)
    if app.out.json_mode:
        app.out.json(_payload(res, final.text, [*app.recorded_notes, *res.notices]))
        return 0
    app.out.line(f"edited {res.id}  {res.md_path.as_posix()}")
    return 0


def _payload(
    res: BodyUpdateResult, body_text: str, notices: list[str]
) -> dict[str, Any]:
    """The ``edit --json`` payload (§2.4.1): ``BodyUpdateResult`` + paths.

    ``body`` is the body as written on disk (re-read through core so the
    assembled ``--section`` result is covered too).
    """
    return {
        "id": res.id,
        "md_path": res.md_path.as_posix(),
        "json_path": res.json_path.as_posix(),
        "body": body_text,
        "body_hash": res.body_hash,
        "title": res.title,
        "changed": res.changed,
        "sections": [section.model_dump(mode="json") for section in res.sections],
        "findings": report_payload(res.findings),
        "notices": notices,
    }


def _editor_flow(app: App, workspace: Workspace, doc_id: str | None) -> int:
    resolved = _resolve_id(app, workspace, doc_id)
    result = edit_document(workspace, resolved)
    app.out.detail(f"edited {result.id} ({result.body.as_posix()}) via {result.editor}")
    return 0


def _resolve_id(app: App, workspace: Workspace, doc_id: str | None) -> str:
    if doc_id is not None:
        return doc_id
    if not app.interactive:
        raise UsageError("missing document ID (pass ID or drop --no-input)")
    picked = pick(
        "pick a document",
        document_pick_rows(workspace),
        stdout=app.out.stdout,
    )
    if picked is None:
        raise UsageError("cancelled: no document selected")
    return picked.key
