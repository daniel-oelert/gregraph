"""``gregraph template`` (spec §13.17, §7.7): manage repository templates.

``list`` shows names, versions, flags and document counts; ``add`` copies a
built-in template in as ``v1`` (or the next version); ``bump`` copies the
latest version forward for editing (``--breaking`` marks the step); ``show``
prints a version's descriptor and skeleton. Thin: parse →
``gregraph.core.operations.template_*`` → format.
"""

from __future__ import annotations

import argparse

from gregraph.cli.main import App, UsageError
from gregraph.core.operations import (
    TemplateListResult,
    TemplateShowResult,
    template_add,
    template_bump,
    template_list,
    template_show,
)


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "template_cmd", None)
    if command == "list":
        return _list(app, template_list(workspace))
    if command == "add":
        added = template_add(workspace, args.builtin)
        for notice in added.notices:
            app.out.warn(notice)
        app.out.line(f"added {added.name} v{added.version}  {added.path.as_posix()}")
        return 0
    if command == "bump":
        bumped = template_bump(workspace, args.name, breaking=args.breaking)
        app.out.line(
            f"bumped {bumped.name} to v{bumped.version}  {bumped.path.as_posix()}"
        )
        app.out.line("edit the new version's files; existing documents keep their pin")
        return 0
    if command == "show":
        _show(app, template_show(workspace, args.name, version=args.version))
        return 0
    raise UsageError("template takes exactly one subcommand: list, add, bump, show")


def _list(app: App, result: TemplateListResult) -> int:
    rows: list[list[str]] = []
    for info in result.templates:
        for version in info.versions:
            rows.append(
                [
                    info.name,
                    f"v{version.version}",
                    "deprecated" if version.deprecated else "",
                    "breaking" if version.breaking else "",
                    str(version.document_count),
                    version.description,
                ]
            )
    app.out.table(
        ["TEMPLATE", "VERSION", "DEPRECATED", "BREAKING", "DOCS", "DESCRIPTION"],
        rows,
    )
    return 0


def _show(app: App, result: TemplateShowResult) -> None:
    out = app.out
    for notice in result.notices:
        out.warn(notice)
    descriptor = result.descriptor
    out.line(f"{result.name} v{descriptor.version}")
    out.mapping_lines(
        {
            "description": descriptor.description,
            "deprecated": "yes" if descriptor.deprecated else "no",
            "breaking": "yes" if descriptor.breaking else "no",
        }
    )
    out.line()
    out.line(result.skeleton.rstrip("\n"))
