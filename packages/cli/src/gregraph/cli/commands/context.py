"""``gregraph context`` (AGENT_READINESS §6.1, AGENT-027/028): context bundle.

One call packs the requested documents (full ``show`` payloads plus parsed
sections), their BFS neighbours with the connecting edge, direction, depth
and freshness, the glossary terms occurring in the bundle bodies, and the
validation/freshness findings affecting the bundle. ``--json`` emits the
canonical bundle object; human mode prints one combined LLM-friendly
Markdown document (no colour codes). Thin: parse →
:func:`gregraph.core.operations.build_context` → format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.commands.show import cr_json_payload, json_payload
from gregraph.cli.main import App
from gregraph.core.operations import (
    ContextNeighbor,
    ContextResult,
    ContextTarget,
    ContextTerm,
    build_context,
)
from gregraph.core.validation import report_payload


def _targets_payload(result: ContextResult) -> list[dict[str, Any]]:
    """Per-target ``show`` payload plus ``body`` and parsed ``sections``."""
    payloads: list[dict[str, Any]] = []
    for target in result.targets:
        show = target.show
        if show.change_request is not None:
            payload = cr_json_payload(show)
            payload["body"] = show.change_request.body
        else:
            payload = json_payload(show, depth=None, include_body=True)
        payload["sections"] = [
            {"heading": section.heading, "content": section.content}
            for section in target.sections
        ]
        payloads.append(payload)
    return payloads


def _neighbors_payload(result: ContextResult) -> list[dict[str, Any]]:
    return [
        {
            "id": neighbour.id,
            "via": {
                "source": neighbour.via.source,
                "type": neighbour.via.type,
                "target": neighbour.via.target,
            },
            "direction": neighbour.direction,
            "depth": neighbour.depth,
            "freshness": neighbour.freshness,
            "sidecar": neighbour.sidecar.model_dump(mode="json", by_alias=True),
            "body": neighbour.body,
        }
        for neighbour in result.neighbors
    ]


def _terms_payload(result: ContextResult) -> list[dict[str, Any]]:
    return [
        {
            "term": entry.term,
            "slug": entry.slug,
            "aliases": list(entry.aliases),
            "body": entry.body,
        }
        for entry in result.terms
    ]


def _json_payload(result: ContextResult) -> dict[str, Any]:
    """The §6.1 ``context --json`` bundle object."""
    return {
        "requested": list(result.requested),
        "depth": result.depth,
        "direction": result.direction,
        "targets": _targets_payload(result),
        "neighbors": _neighbors_payload(result),
        "terms": _terms_payload(result),
        "findings": report_payload(result.findings),
    }


def _freshness_suffix(view_state: str) -> str:
    return f" ({view_state})" if view_state != "fresh" else ""


def _target_block(target: ContextTarget) -> str:
    """One target as a Markdown block: H1, status line, body, edges."""
    show = target.show
    lines: list[str] = []
    if show.change_request is not None:
        cr = show.change_request
        lines.append(f"# {cr.id} — {cr.title}")
        lines.append("")
        lines.append(f"status: {cr.status} (effective: {cr.effective})")
        lines.append("")
        if cr.body:
            lines.append(cr.body.rstrip("\n"))
        return "\n".join(lines).rstrip()
    document = show.document
    assert document is not None
    lines.append(f"# {document.id} — {document.title}")
    lines.append("")
    lines.append(
        f"status: {show.status}  type: {document.type} ({show.kind})  "
        f"version: {document.version}"
    )
    lines.append("")
    if show.body_text:
        lines.append(show.body_text.rstrip("\n"))
        lines.append("")
    if show.outbound:
        lines.append("outbound:")
        for view in show.outbound:
            lines.append(
                f"- {view.type} → {view.target} "
                f"(target_version {view.target_version})"
                f"{_freshness_suffix(view.state)}"
            )
    if show.inbound:
        lines.append("inbound:")
        for view in show.inbound:
            lines.append(
                f"- {view.type} ← {view.source} "
                f"(target_version {view.target_version})"
                f"{_freshness_suffix(view.state)}"
            )
    return "\n".join(lines).rstrip()


def _neighbour_block(neighbour: ContextNeighbor) -> str:
    """One neighbour as a Markdown block: H3 with edge facts, then the body."""
    title = neighbour.sidecar.title
    head = (
        f"### {neighbour.id} — {title} "
        f"({neighbour.direction}, depth {neighbour.depth}, {neighbour.freshness})"
    )
    body = neighbour.body.rstrip("\n")
    if body:
        return f"{head}\n\n{body}"
    return head


def _term_block(entry: ContextTerm) -> str:
    """One glossary term as a Markdown block: H3, then the term body."""
    aliases = f" (aliases: {', '.join(entry.aliases)})" if entry.aliases else ""
    head = f"### {entry.term} ({entry.slug}){aliases}"
    body = entry.body.rstrip("\n")
    if body:
        return f"{head}\n\n{body}"
    return head


def _print_markdown(app: App, result: ContextResult) -> None:
    """One combined LLM-friendly Markdown document (AGENT_READINESS §6.1).

    Plain text — no colour codes inside the Markdown block.
    """
    blocks = [_target_block(target) for target in result.targets]
    if result.neighbors:
        blocks.append(
            "## Neighbours\n\n"
            + "\n\n".join(_neighbour_block(item) for item in result.neighbors)
        )
    if result.terms:
        blocks.append(
            "## Glossary\n\n" + "\n\n".join(_term_block(item) for item in result.terms)
        )
    app.out.line("\n\n---\n\n".join(blocks))


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    result = build_context(
        workspace,
        ids=args.ids,
        depth=args.depth,
        direction=args.direction,
        include_terms=args.include_terms,
    )
    if app.out.json_mode:
        app.out.json(_json_payload(result))
        return 0
    _print_markdown(app, result)
    return 0
