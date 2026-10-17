"""``gregraph new`` (spec §13.2, AGENT_READINESS §2.4.1, §3.2): create a document.

Prompts for type (picker over types), title, and optional initial links when
interactive; every prompt has a flag equivalent (spec §13 general rules).
The template-guided authoring flags (``--section``/``--section-file``/
``--body``/``--body-file``/``--strict``, §3.4) are parsed *before* any prompt
so invalid flag combinations fail fast with exit 2. ``--json`` emits the rich
authoring payload (``md_path``, ``body``, ``sections``, ``sidecar``) an agent
needs for the file-first workflow. Thin: parse →
:func:`gregraph.core.operations.create_document` → format.
"""

from __future__ import annotations

import argparse
from typing import Any

from gregraph.cli.commands import parse_link_spec, type_pick_rows
from gregraph.cli.commands.sections import parse_content_args
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick, prompt_text
from gregraph.core.models import LinkType
from gregraph.core.operations import CreateResult, create_document, edit_document
from gregraph.core.validation import report_payload


def create_payload(result: CreateResult) -> dict[str, Any]:
    """The rich ``new``/``supersede`` authoring payload (§2.4.1).

    Shared with ``supersede`` (its ``new`` entry embeds the same shape).
    """
    sidecar = (
        result.sidecar_document.model_dump(mode="json", by_alias=True)
        if result.sidecar_document is not None
        else {}
    )
    return {
        "id": result.id,
        "uuid": str(result.uuid),
        "type": result.type,
        "kind": result.kind,
        "md_path": result.body.as_posix(),
        "json_path": result.sidecar.as_posix(),
        "template": {
            "name": result.template.name,
            "version": result.template.version,
        },
        "version": result.version,
        "body_hash": result.body_hash,
        "sections": [section.model_dump(mode="json") for section in result.sections],
        "body": result.body_text,
        "sidecar": sidecar,
        "links": [link.model_dump(mode="json") for link in result.links],
    }


def run(args: argparse.Namespace, app: App) -> int:
    content = parse_content_args(args, allow_body=True)
    strict = bool(getattr(args, "strict", False))
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

    try:
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
            sections=content.sections,
            body_text=content.body_text,
            strict=strict,
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    for finding in result.findings:
        app.out.finding(finding)
    for notice in result.notices:
        app.out.warn(notice)
    if app.out.json_mode:
        app.out.json(
            {
                **create_payload(result),
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
    app.out.line(f"created {result.id}  {result.body.as_posix()}")
    if args.edit:
        edit_document(workspace, result.id)
    return 0
