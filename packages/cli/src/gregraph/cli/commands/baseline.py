"""``gregraph baseline``: baseline tags.

A baseline is an annotated Git tag ``baseline/<name>`` whose message holds a
generated manifest (ID, version, body_hash, status per document). ``create``
refuses on uncommitted managed files, validation errors, an existing tag, or
without Git; ``list`` shows the tag names. Thin: parse →
``gregraph.core.operations.baseline_*`` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.main import App, UsageError
from gregraph.core.operations import baseline_create, baseline_list


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "baseline_cmd", None)
    if command == "create":
        created = baseline_create(workspace, args.name, message=args.message)
        for notice in created.notices:
            _notice(app, notice)
        head = created.head or "?"
        app.out.line(f"created {created.tag}  (HEAD {head})")
        if app.out.verbose:
            app.out.line(created.manifest.rstrip("\n"))
        return 0
    if command == "list":
        listing = baseline_list(workspace)
        for notice in listing.notices:
            _notice(app, notice)
        for tag in listing.tags:
            app.out.line(tag)
        return 0
    raise UsageError("baseline takes exactly one subcommand: create, list")


def _notice(app: App, notice: str) -> None:
    if notice.startswith("note: "):
        app.out.note(notice.removeprefix("note: "))
    else:
        app.out.warn(notice)
