"""``gregraph status`` (spec §13.12): repository status and WIP state.

WIP header (``WIP: yes (3 drafts, 1 modified)`` / ``WIP: no``, spec §8),
counts of documents by status, drafts with paths, modified-unbumped items,
the *pending initial version* note for uncommitted modified ``v1`` documents
with inbound links (AGENT_READINESS §3.3), outdated/stale/pending-outdated
links, open conflicts (§11.1), deprecated template pins (§7.7), change
requests by effective status with pending decisions and drift (§9.3, §9.6),
hook state (§12.3) and degraded mode. Exits 0 regardless. Thin: parse →
:func:`gregraph.core.operations.status` → format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.main import App
from gregraph.core.models import Finding
from gregraph.core.operations import DeprecatedTemplateUse, StatusResult, status
from gregraph.core.status import WipState

_STATUS_ORDER = ("active", "draft", "unknown", "superseded", "deprecated")


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    result = status(workspace)
    if app.out.json_mode:
        app.out.json(_payload(result))
    else:
        _print_report(app, result)
    return 0


def wip_header(wip: WipState) -> str:
    """The §8 header line: ``WIP: yes (3 drafts, 1 modified)`` or ``WIP: no``.

    Non-zero categories in order drafts, modified, uncommitted; ``draft``
    singularises (the spec example shows the plural form).
    """
    parts: list[str] = []
    if wip.draft_count:
        plural = "s" if wip.draft_count != 1 else ""
        parts.append(f"{wip.draft_count} draft{plural}")
    if wip.modified_count:
        parts.append(f"{wip.modified_count} modified")
    if wip.uncommitted_count:
        parts.append(f"{wip.uncommitted_count} uncommitted")
    if not parts:
        return "WIP: no"
    return f"WIP: yes ({', '.join(parts)})"


def _fresh_payload(entry: Any) -> dict[str, Any]:
    return {
        "source": entry.source,
        "type": entry.type,
        "target": entry.target,
        "target_version": entry.link_target_version,
        "version": entry.target_version,
        "effective": entry.effective,
    }


def _item_payload(item: Any) -> dict[str, Any]:
    return {
        "key": item.key,
        "status": item.status,
        "body": str(item.body),
        "sidecar": str(item.sidecar),
    }


def _template_payload(use: DeprecatedTemplateUse) -> dict[str, Any]:
    return {"id": use.id, "template": use.template, "version": use.version}


def _finding_payload(finding: Finding) -> dict[str, Any]:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "subject": str(finding.subject),
        "message": finding.message,
    }


def _payload(result: StatusResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "wip": {
            "header": wip_header(result.wip),
            "is_wip": result.wip.is_wip,
            "drafts": [_item_payload(item) for item in result.wip.drafts],
            "modified": [_item_payload(item) for item in result.wip.modified],
            "uncommitted": [str(path) for path in result.wip.uncommitted],
        },
        "documents": dict(result.document_counts),
        "links": {
            "outdated": [_fresh_payload(entry) for entry in result.outdated],
            "stale": [_fresh_payload(entry) for entry in result.stale],
            "pending": [_fresh_payload(entry) for entry in result.pending],
        },
        "conflicts": [list(pair) for pair in result.open_conflicts],
        "deprecated_templates": [
            _template_payload(use) for use in result.deprecated_templates
        ],
        "change_requests": {
            "counts": dict(result.cr_counts),
            "pending": list(result.cr_pending),
            "drift": list(result.cr_drift),
        },
        "hook": {
            "installed": result.hook_installed,
            "up_to_date": result.hook_up_to_date,
        },
        "degraded": result.degraded,
        "findings": [_finding_payload(finding) for finding in result.findings],
    }
    # AGENT_READINESS §3.3: only present when there is something to note.
    if result.pending_initial_version:
        payload["pending_initial_version"] = list(result.pending_initial_version)
    return payload


def _print_report(app: App, result: StatusResult) -> None:
    out = app.out
    out.line(wip_header(result.wip))
    counts = result.document_counts
    shown = [f"{counts[name]} {name}" for name in _STATUS_ORDER if counts.get(name)]
    extra = sorted(
        name for name in counts if name not in _STATUS_ORDER and counts[name]
    )
    shown.extend(f"{counts[name]} {name}" for name in extra)
    out.line(f"documents: {', '.join(shown) if shown else 'none'}")
    if result.wip.drafts:
        out.line("drafts:")
        for item in result.wip.drafts:
            out.line(f"  {item.key}  {item.body.as_posix()}")
    if result.wip.modified:
        out.line("modified, unbumped:")
        for item in result.wip.modified:
            out.line(f"  {item.key}  {item.body.as_posix()}")
    if result.wip.uncommitted:
        out.line("uncommitted:")
        for path in result.wip.uncommitted:
            out.line(f"  {path.as_posix()}")
    if result.pending_initial_version:
        # AGENT_READINESS §3.3: no new status is invented — just a note.
        out.line(
            "pending initial version (v1 with inbound links): "
            f"{', '.join(result.pending_initial_version)}"
        )
    out.line(
        "links: "
        f"{len(result.outdated)} outdated, "
        f"{len(result.stale)} stale, "
        f"{len(result.pending)} pending-outdated"
    )
    if result.open_conflicts:
        pairs = ", ".join(f"{low} ↔ {high}" for low, high in result.open_conflicts)
        out.line(f"conflicts: {len(result.open_conflicts)} open ({pairs})")
    else:
        out.line("conflicts: none open")
    if result.deprecated_templates:
        uses = ", ".join(
            f"{use.id} on {use.template} v{use.version}"
            for use in result.deprecated_templates
        )
        out.line(f"deprecated templates: {uses}")
    else:
        out.line("deprecated templates: none")
    if result.cr_counts:
        crs = ", ".join(
            f"{result.cr_counts[name]} {name}"
            for name in sorted(result.cr_counts)
            if result.cr_counts[name]
        )
        out.line(f"change requests (effective): {crs}")
    else:
        out.line("change requests: none")
    if result.cr_pending:
        out.line(f"  pending decisions: {', '.join(result.cr_pending)}")
    if result.cr_drift:
        out.line(f"  drift: {', '.join(result.cr_drift)}")
    if not result.hook_installed:
        hook = "not installed"
    elif result.hook_up_to_date:
        hook = "installed, up to date"
    else:
        hook = "installed, out of date"
    out.line(f"hook: {hook}")
    out.line(f"degraded mode: {'yes' if result.degraded else 'no'}")
    out.report(result.findings)
