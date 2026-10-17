"""``gregraph deprecate`` / ``gregraph undeprecate`` (spec §13.15, §8, §2.4.1).

Deprecation sets the one stored status flag (``deprecate ID --reason "…"``);
``undeprecate`` clears it. Inbound links of a newly deprecated document
become stale and are listed — the reviewer decides whether they move or go.
``--json`` emits ``{id, changed, deprecated, stale_inbound, findings,
notices}``. Thin: parse → :func:`gregraph.core.operations.deprecate` /
:func:`~gregraph.core.operations.undeprecate` → format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick, prompt_text
from gregraph.core.operations import (
    DeprecateResult,
    StaleInbound,
    deprecate,
    undeprecate,
)
from gregraph.core.validation import report_payload


def deprecate_payload(app: App, result: DeprecateResult) -> dict[str, Any]:
    """The ``deprecate``/``undeprecate --json`` payload (§2.4.1)."""
    return {
        "id": result.id,
        "changed": result.changed,
        "deprecated": (
            result.deprecated.model_dump(mode="json")
            if result.deprecated is not None
            else None
        ),
        "stale_inbound": [_stale_inbound_entry(item) for item in result.stale_inbound],
        "findings": report_payload(result.findings),
        "notices": [*app.recorded_notes, *result.notices],
    }


def _stale_inbound_entry(item: StaleInbound) -> dict[str, Any]:
    return {
        "source": item.source,
        "type": item.type,
        "target": item.target,
        "target_version": item.target_version,
    }


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
    out = app.out
    if getattr(args, "command", "") == "undeprecate":
        result = undeprecate(workspace, doc_id=doc_id)
        if app.out.json_mode:
            out.json(deprecate_payload(app, result))
            return 0
        if result.changed:
            out.line(f"undeprecated {result.id}")
        for notice in result.notices:
            out.warn(notice)
        return 0
    reason = args.reason
    if reason is None:
        if not app.interactive:
            raise UsageError("missing --reason (deprecation needs a reason)")
        reason = prompt_text("reason", required=True, stdout=out.stdout)
        if reason is None:
            raise UsageError("cancelled: no reason given")
    result = deprecate(workspace, doc_id=doc_id, reason=reason)
    if app.out.json_mode:
        out.json(deprecate_payload(app, result))
        return 0
    for notice in result.notices:
        out.warn(notice)
    if result.changed:
        out.line(f"deprecated {result.id}")
        _print_stale(app, result.id, result.stale_inbound)
    return 0


def _print_stale(app: App, doc_id: str, stale: tuple[StaleInbound, ...]) -> None:
    if not stale:
        return
    app.out.line("stale inbound links (review before removing or re-pointing):")
    for item in stale:
        app.out.line(
            f"  {item.source}  {item.type}  {doc_id}  "
            f"target_version {item.target_version}"
        )
