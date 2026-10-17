"""``gregraph baseline`` (spec §12.4, AGENT_READINESS §2.4.3): baseline tags.

A baseline is an annotated Git tag ``baseline/<name>`` whose message holds a
generated manifest (ID, version, body_hash, status per document). ``create``
refuses on uncommitted managed files, validation errors, an existing tag, or
without Git; ``list`` shows the tag names. Both subcommands support ``--json``.
Thin: parse → ``gregraph.core.operations.baseline_*`` → format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.main import App, UsageError
from gregraph.core.operations import (
    BaselineCreateResult,
    BaselineListResult,
    baseline_create,
    baseline_list,
)
from gregraph.core.validation import report_payload


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "baseline_cmd", None)
    if command == "create":
        created = baseline_create(workspace, args.name, message=args.message)
        notices = _clean_notices(app, created)
        if app.out.json_mode:
            app.out.json(_create_payload(created, notices))
            return 0
        for notice in created.notices:
            _notice(app, notice)
        head = created.head or "?"
        app.out.line(f"created {created.tag}  (HEAD {head})")
        if app.out.verbose:
            app.out.line(created.manifest.rstrip("\n"))
        return 0
    if command == "list":
        listing = baseline_list(workspace)
        notices = _clean_notices(app, listing)
        if app.out.json_mode:
            app.out.json(_list_payload(listing, notices))
            return 0
        for notice in listing.notices:
            _notice(app, notice)
        for tag in listing.tags:
            app.out.line(tag)
        return 0
    raise UsageError("baseline takes exactly one subcommand: create, list")


def _clean_notices(
    app: App, result: BaselineCreateResult | BaselineListResult
) -> list[str]:
    """Degraded notes + result notices, ``note: `` prefixes stripped (R3)."""
    stripped = [notice.removeprefix("note: ") for notice in result.notices]
    return [*app.recorded_notes, *stripped]


def _create_payload(result: BaselineCreateResult, notices: list[str]) -> dict[str, Any]:
    """The ``baseline create --json`` payload (§2.4.3)."""
    return {
        "name": result.name,
        "tag": result.tag,
        "manifest": result.manifest,
        "head": result.head,
        "findings": report_payload(result.findings),
        "notices": notices,
    }


def _list_payload(result: BaselineListResult, notices: list[str]) -> dict[str, Any]:
    """The ``baseline list --json`` payload (§2.4.3)."""
    return {
        "tags": list(result.tags),
        "findings": report_payload(result.findings),
        "notices": notices,
    }


def _notice(app: App, notice: str) -> None:
    if notice.startswith("note: "):
        app.out.note(notice.removeprefix("note: "))
    else:
        app.out.warn(notice)
