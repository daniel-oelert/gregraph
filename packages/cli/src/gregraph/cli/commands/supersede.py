"""``gregraph supersede`` (spec §13.14, §7.6, AGENT_READINESS §2.4.1): replace.

One new document supersedes every target (multi-target = conflict compromise,
§11.2). ``--copy-body`` defaults on when the resolved template matches the
targets', ``--copy-links`` copies their outbound edges, ``--cr`` records the
new document as introduced by that CR (§9.5). The template-guided authoring
flags (``--section*``/``--body*``/``--strict``, §3.4) shape the new document's
body and are parsed before any prompt. Inbound links of the old documents
become stale and are listed with the ``link refresh --follow`` commands that
re-point them. Thin: parse → :func:`gregraph.core.operations.supersede` →
format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.commands.new import create_payload
from gregraph.cli.commands.sections import parse_content_args
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick
from gregraph.core.operations import (
    CreateResult,
    SupersedeResult,
    edit_document,
    supersede,
)
from gregraph.core.validation import report_payload
from gregraph.core.workspace import Workspace


def run(args: argparse.Namespace, app: App) -> int:
    content = parse_content_args(args, allow_body=True)
    strict = bool(getattr(args, "strict", False))
    workspace = app.open_workspace()
    targets = list(args.old)
    if not targets:
        if not app.interactive:
            raise UsageError("missing supersede target (pass OLD or drop --no-input)")
        targets = _pick_targets(app, workspace)
    try:
        result = supersede(
            workspace,
            targets=targets,
            title=args.title,
            type=args.type,
            copy_body=args.copy_body,
            copy_links=args.copy_links,
            cr=args.cr,
            sections=content.sections,
            body_text=content.body_text,
            strict=strict,
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    out = app.out
    for finding in result.findings:
        out.finding(finding)
    for notice in result.notices:
        out.warn(notice)
    for finding in result.skipped_links:
        out.finding(finding)
    if app.out.json_mode:
        out.json(_payload(app, result))
        return 0
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


def _payload(app: App, result: SupersedeResult) -> dict[str, Any]:
    """The ``supersede --json`` payload (§2.4.1): old IDs + the new document's
    rich authoring payload + copied/skipped links and stale inbound edges."""
    new = result.new if result.new is not None else _fallback_new(result)
    return {
        "old": list(result.supersedes),
        "new": create_payload(new),
        "supersedes": list(result.supersedes),
        "copied_links": [link.model_dump(mode="json") for link in result.copied_links],
        "skipped_links": report_payload(result.skipped_links),
        "stale_inbound": [
            {
                "source": item.source,
                "type": item.type,
                "target": item.target,
                "target_version": item.target_version,
            }
            for item in result.stale_inbound
        ],
        "findings": report_payload(result.findings),
        "notices": [*app.recorded_notes, *result.notices],
    }


def _fallback_new(result: SupersedeResult) -> CreateResult:
    """Defensive fallback: core always populates ``new`` (S12 contract)."""
    return CreateResult(
        id=result.id,
        uuid=result.uuid,
        body=result.body,
        sidecar=result.sidecar,
        type=result.type,
        template=result.template,
        links=(),
    )


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
