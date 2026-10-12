"""``gregraph show`` (spec §13.11): one document in full.

Sidecar fields, derived status, outbound/inbound edges with freshness, one
level upstream (hierarchical), unlimited-depth downstream tree (directed,
``--depth`` limits the printed tree), assets and template info; ``--body``
prints the Markdown. CR IDs delegate to ``cr show`` (spec §13.11). Thin:
parse → :func:`gregraph.core.operations.show_document` → format.
"""

from __future__ import annotations

import argparse
import dataclasses
from typing import Any

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.main import App, UsageError
from gregraph.cli.output import document_payload
from gregraph.cli.prompts import pick
from gregraph.core.operations import LinkView, ShowResult, show_document


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    if args.depth is not None and args.depth < 0:
        raise ValueError("depth must be zero or positive")
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
    result = show_document(workspace, doc_id, body=args.body)
    if result.change_request is not None:
        return _show_change_request(app, result)
    if app.out.json_mode:
        app.out.json(_json_payload(result, depth=args.depth, include_body=args.body))
        return 0
    _print_document(app, result, depth=args.depth)
    return 0


def _limited(result: ShowResult, depth: int | None) -> tuple[tuple[str, int], ...]:
    if depth is None:
        return result.downstream
    return tuple(item for item in result.downstream if item[1] <= depth)


def _view_payload(view: LinkView) -> dict[str, object]:
    return {
        "source": view.source,
        "type": view.type,
        "target": view.target,
        "target_version": view.target_version,
        "effective": view.effective,
        "state": view.state,
    }


def _json_payload(
    result: ShowResult, *, depth: int | None, include_body: bool
) -> dict[str, Any]:
    document = result.document
    assert document is not None
    payload: dict[str, Any] = document_payload(
        document, status=result.status, kind=result.kind
    )
    payload["outbound"] = [_view_payload(view) for view in result.outbound]
    payload["inbound"] = [_view_payload(view) for view in result.inbound]
    payload["upstream"] = [
        {"type": link_type, "target": target} for link_type, target in result.upstream
    ]
    payload["downstream"] = [
        {"id": item_id, "depth": item_depth}
        for item_id, item_depth in _limited(result, depth)
    ]
    payload["template_info"] = {
        "description": result.template_description,
        "deprecated": result.template_deprecated,
    }
    if include_body:
        payload["body"] = result.body_text
    return payload


def _format_link(view: LinkView) -> str:
    effective = "?" if view.effective is None else str(view.effective)
    return (
        f"{view.type}  {view.target}  "
        f"target_version {view.target_version}/{effective}  {view.state}"
    )


def _format_inbound(view: LinkView) -> str:
    effective = "?" if view.effective is None else str(view.effective)
    return (
        f"{view.source}  {view.type}  "
        f"target_version {view.target_version}/{effective}  {view.state}"
    )


def _print_document(app: App, result: ShowResult, *, depth: int | None) -> None:
    document = result.document
    assert document is not None
    out = app.out
    created_by = ""
    if document.created_by is not None:
        identity = document.created_by
        created_by = f"  by  {identity.name} <{identity.email}>"
    template_note = ""
    if result.template_description:
        template_note = f"  ({result.template_description})"
        if result.template_deprecated:
            template_note += "  [deprecated]"
    created_stamp = document.created.isoformat().replace("+00:00", "Z")
    template_pin = f"{document.template.name}/v{document.template.version}"
    out.line(f"{document.id}  {document.type}  {document.title}")
    fields: dict[str, str] = {
        "status": str(result.status),
        "type": f"{document.type} ({result.kind})",
        "version": str(document.version),
        "created": f"{created_stamp}{created_by}",
        "template": f"{template_pin}{template_note}",
    }
    if document.tags:
        fields["tags"] = ", ".join(document.tags)
    if document.origin_cr:
        fields["origin_cr"] = document.origin_cr
    for name, value in sorted(document.extra.items()):
        fields[f"extra.{name}"] = value
    out.mapping_lines(fields)
    if document.assets:
        out.line("  assets")
        for asset in document.assets:
            out.line(f"    {asset.path}  {asset.hash}")
    out.line()
    out.line("  outbound:")
    for view in result.outbound:
        out.line(f"    {_format_link(view)}")
    out.line("  inbound:")
    for view in result.inbound:
        out.line(f"    {_format_inbound(view)}")
    out.line("  upstream:")
    for link_type, target in result.upstream:
        out.line(f"    {link_type}  {target}")
    out.line("  downstream:")
    for item_id, item_depth in _limited(result, depth):
        out.line(f"    {'  ' * item_depth}{item_id}  (depth {item_depth})")
    if result.body_text is not None:
        out.line()
        out.line(result.body_text.rstrip("\n"))


def _show_change_request(app: App, result: ShowResult) -> int:
    cr = result.change_request
    assert cr is not None
    out = app.out
    if out.json_mode:
        payload: dict[str, Any] = {
            "kind": "change-request",
            "id": cr.id,
            "title": cr.title,
            "status": cr.status,
            "effective": cr.effective,
            "decisions": [
                decision.model_dump(mode="json") for decision in cr.decisions
            ],
            "scope": [dataclasses.asdict(entry) for entry in cr.scope],
            "introduces": [dataclasses.asdict(entry) for entry in cr.introduces],
            "impact": list(cr.impact),
            "branch": cr.branch,
            "external_ref": cr.external_ref,
            "tags": list(cr.tags),
            "extra": dict(cr.extra),
        }
        out.json(payload)
        return 0
    out.line(f"{cr.id}  {cr.title}")
    fields: dict[str, str] = {"status": f"{cr.status} (effective: {cr.effective})"}
    if cr.branch:
        fields["branch"] = cr.branch
    if cr.external_ref:
        fields["external_ref"] = cr.external_ref
    if cr.tags:
        fields["tags"] = ", ".join(cr.tags)
    out.mapping_lines(fields)
    out.line("  decisions:")
    for decision in cr.decisions:
        who = decision.by.name if decision.by is not None else "?"
        stamp = decision.at.isoformat().replace("+00:00", "Z")
        out.line(f"    {decision.status}  {stamp}  by {who}  at v{decision.at_version}")
    out.line("  scope:")
    for entry in cr.scope:
        out.line(
            f"    {entry.id}  intent={entry.intent}  base={entry.base_version}  "
            f"baseline={entry.baseline_version}  working={entry.working_version}  "
            f"live={entry.live}  drift={'yes' if entry.drift else 'no'}"
        )
    if cr.introduces:
        out.line("  introduces:")
        for introduced in cr.introduces:
            out.line(f"    {introduced.doc_id}  status={introduced.status}")
    if cr.impact:
        out.line("  impact:")
        for item in cr.impact:
            out.line(f"    {item}")
    return 0
