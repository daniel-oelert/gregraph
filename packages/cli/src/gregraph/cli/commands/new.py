"""``gregraph new`` (spec §13.2): create a document.

Prompts for type (picker over types), title, and optional initial links when
interactive; every prompt has a flag equivalent (spec §13 general rules).
Thin: parse → :func:`gregraph.core.operations.create_document` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.commands import parse_link_spec, type_pick_rows
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick, prompt_text
from gregraph.core.models import LinkType
from gregraph.core.operations import create_document, edit_document


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()

    type_name = args.type
    if type_name is None:
        if not app.interactive:
            raise UsageError(
                "missing document type (pass TYPE or drop --no-input to be prompted)"
            )
        picked = pick(
            "pick a document type",
            type_pick_rows(workspace.config),
            stdout=app.out.stdout,
        )
        if picked is None:
            raise UsageError("cancelled: no document type selected")
        type_name = picked.key

    title = args.title
    if title is None:
        if not app.interactive:
            raise UsageError("missing title (pass --title or drop --no-input)")
        title = prompt_text("title", required=True, stdout=app.out.stdout)
        if title is None:
            raise UsageError("cancelled: no title given")

    links: list[tuple[LinkType, str]] = [parse_link_spec(item) for item in args.link]
    if app.interactive and not args.link:
        while True:
            text = prompt_text(
                "link (TYPE:TARGET, empty to finish)", stdout=app.out.stdout
            )
            if text is None or text == "":
                break
            try:
                links.append(parse_link_spec(text))
            except ValueError as exc:
                app.out.error(str(exc))

    result = create_document(
        workspace,
        type=type_name,
        title=title,
        template=args.template,
        template_version=args.template_version,
        allow_deprecated=args.allow_deprecated,
        tags=args.tag,
        links=links,
        cr=args.cr,
    )
    for finding in result.findings:
        app.out.finding(finding)
    for notice in result.notices:
        app.out.warn(notice)
    app.out.line(f"created {result.id}  {result.body.as_posix()}")
    if args.edit:
        edit_document(workspace, result.id)
    return 0
