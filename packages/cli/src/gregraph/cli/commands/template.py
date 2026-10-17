"""``gregraph template`` (spec §13.17, §7.7, AGENT_READINESS §4.2): templates.

``list`` shows names, versions, flags and document counts; ``add`` copies a
built-in template in as ``v1`` (or the next version); ``bump`` copies the
latest version forward for editing (``--breaking`` marks the step); ``show``
prints a version's descriptor and skeleton. Every subcommand supports
``--json`` (AGENT-022). Thin: parse → ``gregraph.core.operations.template_*``
→ format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.main import App, UsageError
from gregraph.core.operations import (
    TemplateAddResult,
    TemplateBumpResult,
    TemplateInfo,
    TemplateListResult,
    TemplateShowResult,
    template_add,
    template_bump,
    template_list,
    template_show,
)
from gregraph.core.validation import report_payload


def _active(info: TemplateInfo) -> tuple[int, str]:
    """The active version: latest non-deprecated, else the last version.

    Mirrors ``describe_schema``'s active-version rule so ``template list
    --json`` and ``schema --json`` agree (AGENT_READINESS §4.1 note).
    """
    live = [version for version in info.versions if not version.deprecated]
    chosen = live[-1] if live else info.versions[-1]
    return chosen.version, chosen.description


def _list_payload(result: TemplateListResult) -> dict[str, Any]:
    """The §2.4.4 ``template list --json`` object."""
    templates: list[dict[str, Any]] = []
    for info in result.templates:
        latest_version, description = _active(info)
        templates.append(
            {
                "name": info.name,
                "description": description,
                "latest_version": latest_version,
                "versions": [
                    {
                        "version": version.version,
                        "deprecated": version.deprecated,
                        "breaking": version.breaking,
                        "documents": version.document_count,
                    }
                    for version in info.versions
                ],
            }
        )
    return {"templates": templates}


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "template_cmd", None)
    if command == "list":
        return _list(app, template_list(workspace))
    if command == "add":
        return _add(app, template_add(workspace, args.builtin))
    if command == "bump":
        return _bump(app, template_bump(workspace, args.name, breaking=args.breaking))
    if command == "show":
        _show(app, template_show(workspace, args.name, version=args.version))
        return 0
    raise UsageError("template takes exactly one subcommand: list, add, bump, show")


def _list(app: App, result: TemplateListResult) -> int:
    if app.out.json_mode:
        app.out.json(_list_payload(result))
        return 0
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


def _add(app: App, added: TemplateAddResult) -> int:
    for notice in added.notices:
        app.out.warn(notice)
    if app.out.json_mode:
        app.out.json(
            {
                "name": added.name,
                "version": added.version,
                "path": added.path.as_posix(),
                "findings": report_payload(added.findings),
                "notices": [*app.recorded_notes, *added.notices],
            }
        )
        return 0
    app.out.line(f"added {added.name} v{added.version}  {added.path.as_posix()}")
    return 0


def _bump(app: App, bumped: TemplateBumpResult) -> int:
    for notice in bumped.notices:
        app.out.warn(notice)
    if app.out.json_mode:
        app.out.json(
            {
                "name": bumped.name,
                "version": bumped.version,
                "path": bumped.path.as_posix(),
                "breaking": bumped.breaking,
                "findings": report_payload(bumped.findings),
                "notices": [*app.recorded_notes, *bumped.notices],
            }
        )
        return 0
    app.out.line(f"bumped {bumped.name} to v{bumped.version}  {bumped.path.as_posix()}")
    app.out.line("edit the new version's files; existing documents keep their pin")
    return 0


def _show(app: App, result: TemplateShowResult) -> None:
    out = app.out
    for notice in result.notices:
        out.warn(notice)
    if out.json_mode:
        descriptor = result.descriptor
        out.json(
            {
                "name": descriptor.name,
                "version": descriptor.version,
                "description": descriptor.description,
                "deprecated": descriptor.deprecated,
                "breaking": descriptor.breaking,
                "sections": [
                    section.model_dump(mode="json") for section in descriptor.sections
                ],
                "skeleton": result.skeleton,
                "path": result.path.as_posix(),
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return
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
