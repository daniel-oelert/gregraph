"""``gregraph graph`` (spec §13.13, §15): export the Mermaid flowchart.

Default scope: all non-superseded, non-deprecated nodes; all directed edges
plus ``conflicts-with``. ``--root/--depth`` limit to the downstream subgraph,
``--types/--edges`` filter, ``--include-superseded`` widens the node scope,
``--direction`` picks ``TD``/``LR`` and ``-o FILE`` writes the fenced block to
a file instead of stdout (the one place the CLI touches the filesystem). Thin:
parse → :func:`gregraph.core.operations.export_graph` → format.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from gregraph.cli.main import App
from gregraph.core.operations import ExportGraphResult, export_graph
from gregraph.core.validation import report_payload


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    if args.depth is not None and args.depth < 0:
        raise ValueError("depth must be zero or positive")
    result = export_graph(
        workspace,
        roots=tuple(args.root),
        depth=args.depth,
        types=_split_csv(args.types),
        edges=_split_csv(args.edges),
        include_superseded=args.include_superseded,
        direction=args.direction,
    )
    if app.out.json_mode:
        app.out.json(_payload(result))
    else:
        app.out.report(result.findings)
        if args.output is not None:
            Path(args.output).write_text(result.diagram, encoding="utf-8")
            app.out.line(f"wrote {args.output}")
        else:
            print(result.diagram, end="", file=app.out.stdout)
    return 0


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _payload(result: ExportGraphResult) -> dict[str, Any]:
    return {
        "diagram": result.diagram,
        "findings": report_payload(result.findings),
    }
