"""``gregraph set`` (spec §13.6, AGENT_READINESS §2.4.1): set tags or extra.

``tags=a,b`` replaces, ``tags+=x``/``tags-=x`` add/remove, ``extra.<name>=v``
sets and ``extra.<name>=`` removes. Everything else is refused with a pointer
to the right command (``title`` → edit the H1, ``type`` → supersede, …).
Prompts for the document and the assignments when interactive. ``--json``
emits ``{id, applied, findings, notices}`` with ``applied`` mapping each given
assignment's key to its value. Thin: parse →
:func:`gregraph.core.operations.set_fields` → format.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from gregraph.cli.commands import document_pick_rows
from gregraph.cli.main import App, UsageError
from gregraph.cli.prompts import pick, prompt_text
from gregraph.core.operations import set_fields
from gregraph.core.validation import report_payload


def applied_assignments(assignments: Sequence[str]) -> dict[str, str]:
    """``{key: value}`` of the given ``key=value`` assignments (§2.4.1).

    The key is everything before the first ``=`` (``tags``, ``tags+``,
    ``tags-``, ``extra.<name>``); assignments without ``=`` cannot happen —
    core refuses them (``E-SET-VALUE``).
    """
    applied: dict[str, str] = {}
    for text in assignments:
        key, separator, value = text.partition("=")
        if separator:
            applied[key] = value
    return applied


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

    assignments = list(args.assignments)
    if not assignments:
        if not app.interactive:
            raise UsageError("missing assignment (pass key=value or drop --no-input)")
        while True:
            text = prompt_text(
                "assignment (key=value, empty to finish)", stdout=app.out.stdout
            )
            if text is None or text == "":
                break
            assignments.append(text)
    if not assignments:
        raise UsageError("nothing to set")

    result = set_fields(workspace, doc_id=doc_id, assignments=assignments)
    for notice in result.notices:
        app.out.warn(notice)
    if app.out.json_mode:
        app.out.json(
            {
                "id": result.id,
                "applied": applied_assignments(assignments),
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
    if result.changed:
        app.out.line(f"updated {result.id}")
    else:
        app.out.line(f"{result.id}: no change")
    app.out.line(f"  tags: {', '.join(result.tags) if result.tags else '(none)'}")
    if result.extra:
        for name, value in sorted(result.extra.items()):
            app.out.line(f"  extra.{name}: {value}")
    return 0
