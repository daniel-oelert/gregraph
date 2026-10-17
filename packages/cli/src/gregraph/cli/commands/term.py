"""``gregraph term`` (spec §13.20, §10, AGENT_READINESS §2.4.4): glossary terms.

Terms are first-class non-graph entities (§10.1) identified by slug.
``add`` creates ``glossary/<slug>.md`` + ``<slug>.json`` and takes the
template-guided ``--section*``/``--strict`` flags (§3.4; no whole-body
flags); ``usage`` lists documents mentioning the name or an alias
(informational, no edges); ``rename`` moves the files and lists mentions
without rewriting prose; ``deprecate`` sets the deprecation flag. Every
subcommand supports ``--json``. Thin: parse →
``gregraph.core.operations.term_*`` → format.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from gregraph.cli.commands.sections import parse_content_args
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import prompt_text
from gregraph.core.operations import (
    TermAddResult,
    TermInfo,
    TermListResult,
    TermRenameResult,
    TermUsageResult,
    term_add,
    term_deprecate,
    term_list,
    term_rename,
    term_show,
    term_usage,
)
from gregraph.core.validation import report_payload
from gregraph.core.workspace import Workspace


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    command = getattr(args, "term_cmd", None)
    if command == "add":
        return _add(args, app, workspace)
    if command == "list":
        return _list(app, term_list(workspace))
    if command == "show":
        return _show(app, term_show(workspace, args.slug))
    if command == "usage":
        return _usage(app, term_usage(workspace, args.slug))
    if command == "rename":
        return _rename(app, term_rename(workspace, args.slug, args.new_term))
    if command == "deprecate":
        return _deprecate(args, app, workspace)
    raise UsageError(
        "term takes exactly one subcommand: add, list, show, usage, rename, deprecate"
    )


def open_editor(app: App, root: Path, body: Path) -> None:
    """Open ``body`` in ``$VISUAL``/``$EDITOR`` (spec §13.23, §13.20 ``--edit``).

    A missing or failing editor is an environment error (CLI exit code 3),
    mirroring :func:`gregraph.core.operations.edit_document` for bodies that
    are not documents (CRs, terms).
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise OSError("no $VISUAL or $EDITOR configured; cannot edit")
    command = shlex.split(editor)
    if not command:
        raise OSError("$VISUAL/$EDITOR is empty; cannot edit")
    completed = subprocess.run([*command, str(root / body)], cwd=root, check=False)
    if completed.returncode != 0:
        raise OSError(f"editor {editor!r} exited with status {completed.returncode}")


def _add(args: argparse.Namespace, app: App, workspace: Workspace) -> int:
    content = parse_content_args(args, allow_body=False)
    strict = bool(getattr(args, "strict", False))
    name = args.term
    if not name:
        raise UsageError("missing term text")
    result = term_add(
        workspace,
        term=name,
        aliases=args.alias,
        sections=content.sections,
        strict=strict,
    )
    if app.out.json_mode:
        app.out.json(_add_payload(app, result))
        return 0
    _print_add(app, result)
    if args.edit:
        open_editor(app, workspace.root, result.body)
    return 0


def _add_payload(app: App, result: TermAddResult) -> dict[str, Any]:
    """The ``term add --json`` payload (§2.4.4): the rich ``new`` shape."""
    return {
        "term": result.term,
        "slug": result.slug,
        "aliases": list(result.aliases),
        "md_path": result.body.as_posix(),
        "json_path": result.sidecar.as_posix(),
        "sections": [section.model_dump(mode="json") for section in result.sections],
        "body": result.body_text,
        "body_hash": result.body_hash,
        "findings": report_payload(result.findings),
        "notices": [*app.recorded_notes, *result.notices],
    }


def _print_add(app: App, result: TermAddResult) -> None:
    for finding in result.findings:
        app.out.finding(finding)
    for notice in result.notices:
        app.out.warn(notice)
    app.out.line(f"added {result.slug}  {result.body.as_posix()}")


def _list(app: App, result: TermListResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "terms": [
                    {
                        "term": info.term,
                        "slug": info.slug,
                        "aliases": list(info.aliases),
                        "version": info.version,
                        "deprecated": (
                            info.deprecated.model_dump(mode="json")
                            if info.deprecated is not None
                            else None
                        ),
                    }
                    for info in result.terms
                ]
            }
        )
        return 0
    app.out.table(
        ["SLUG", "TERM", "ALIASES", "VERSION", "STATUS"],
        [
            [
                info.slug,
                info.term,
                ", ".join(info.aliases),
                str(info.version),
                str(info.status),
            ]
            for info in result.terms
        ],
    )
    return 0


def _show(app: App, info: TermInfo) -> int:
    if app.out.json_mode:
        app.out.json(_show_payload(info))
        return 0
    out = app.out
    out.line(f"{info.slug}  {info.term}")
    created = info.created.isoformat().replace("+00:00", "Z")
    created_by = ""
    if info.created_by is not None:
        created_by = f"  by  {info.created_by.name} <{info.created_by.email}>"
    deprecated = ""
    if info.deprecated is not None:
        deprecated = f"  deprecated {info.deprecated.at.isoformat()}"
        if info.deprecated.reason:
            deprecated += f"  ({info.deprecated.reason})"
    out.mapping_lines(
        {
            "status": str(info.status),
            "aliases": ", ".join(info.aliases),
            "version": str(info.version),
            "created": f"{created}{created_by}",
            "template": f"{info.template.name}/v{info.template.version}",
            "body_hash": info.body_hash,
        }
    )
    if deprecated:
        out.line(deprecated)
    return 0


def _show_payload(info: TermInfo) -> dict[str, Any]:
    """The ``term show --json`` payload (§2.4.4)."""
    return {
        "term": info.term,
        "slug": info.slug,
        "aliases": list(info.aliases),
        "created": info.created.isoformat().replace("+00:00", "Z"),
        "created_by": (
            info.created_by.model_dump(mode="json")
            if info.created_by is not None
            else None
        ),
        "version": info.version,
        "body_hash": info.body_hash,
        "deprecated": (
            info.deprecated.model_dump(mode="json")
            if info.deprecated is not None
            else None
        ),
        "template": info.template.model_dump(mode="json"),
        "status": info.status,
    }


def _usage(app: App, result: TermUsageResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "slug": result.slug,
                "term": result.term,
                "documents": [
                    {"id": mention.id, "mentions": list(mention.matched)}
                    for mention in result.mentions
                ],
            }
        )
        return 0
    out = app.out
    out.line(f"{result.slug} ({', '.join(result.names)})")
    if not result.mentions:
        out.line("  no mentions")
        return 0
    for mention in result.mentions:
        out.line(
            f"  {mention.id}  {mention.path.as_posix()}  matched: "
            f"{', '.join(mention.matched)}"
        )
    return 0


def _rename(app: App, result: TermRenameResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "old_slug": result.old_slug,
                "new_slug": result.slug,
                "term": result.term,
                "mentioning_documents": [mention.id for mention in result.mentions],
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
    out = app.out
    for notice in result.notices:
        out.warn(notice)
    if not result.changed:
        return 0
    out.line(f"renamed {result.old_slug} -> {result.slug}  {result.body.as_posix()}")
    if result.mentions:
        out.line("mentions of the old name (prose is yours to update):")
        for mention in result.mentions:
            out.line(
                f"  {mention.id}  {mention.path.as_posix()}  "
                f"matched: {', '.join(mention.matched)}"
            )
    return 0


def _deprecate(args: argparse.Namespace, app: App, workspace: Workspace) -> int:
    reason = args.reason
    if reason is None:
        if not app.interactive:
            raise UsageError("missing --reason (deprecation needs a reason)")
        reason = prompt_text("reason", required=True, stdout=app.out.stdout)
        if reason is None:
            raise UsageError("cancelled: no reason given")
    result = term_deprecate(workspace, args.slug, reason=reason)
    if app.out.json_mode:
        app.out.json(
            {
                "slug": result.slug,
                "deprecated": (
                    result.deprecated.model_dump(mode="json")
                    if result.deprecated is not None
                    else None
                ),
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
    for notice in result.notices:
        app.out.warn(notice)
    if result.changed:
        app.out.line(f"deprecated {result.slug}")
    return 0
