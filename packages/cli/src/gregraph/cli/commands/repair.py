"""``gregraph repair`` (spec §13.19, §7.2, §12.6, §4.4): repair damaged data.

``versions`` recomputes conflicted sidecars (conflict markers: ``version =
max(versions seen) + 1``, hashes and clamped/de-duplicated links);
``regenerate-id PATH`` fixes an ``E-ID-DUPLICATE`` with a fresh UUID/ID;
``cache`` deletes and rebuilds the index cache. Invoked without a subcommand,
the §12.6 merge-conflict guidance is printed (spec §13.19). Thin: parse →
``gregraph.core.operations.repair_*`` → format.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gregraph.cli.main import App, UsageError
from gregraph.core.operations import (
    RepairIdResult,
    RepairVersionsResult,
    repair_cache,
    repair_regenerate_id,
    repair_versions,
)
from gregraph.core.versioning import repair_guidance


def run(args: argparse.Namespace, app: App) -> int:
    command = getattr(args, "repair_cmd", None)
    if command is None:
        app.out.line("usage: gregraph repair {versions,regenerate-id,cache} ...")
        app.out.line()
        for line in repair_guidance():
            app.out.line(line)
        raise UsageError(
            "repair takes exactly one subcommand: versions, regenerate-id, cache"
        )
    workspace = app.open_workspace()
    if command == "versions":
        _print_versions(app, repair_versions(workspace))
        return 0
    if command == "regenerate-id":
        _print_id(app, repair_regenerate_id(workspace, Path(args.path)))
        return 0
    cache = repair_cache(workspace)
    app.out.line(
        f"cache rebuilt: {cache.file_count} file(s), "
        f"{cache.types_seen} type(s), {cache.templates_seen} template(s)"
    )
    return 0


def _print_versions(app: App, result: RepairVersionsResult) -> None:
    out = app.out
    for item in result.repaired:
        seen = ", ".join(str(version) for version in item.versions_seen)
        out.line(
            f"repaired {item.path.as_posix()}  version {item.version} (seen {seen})"
        )
        if item.clamped_links:
            out.line(f"  clamped {item.clamped_links} link(s)")
        if item.deduplicated_links:
            out.line(f"  de-duplicated {item.deduplicated_links} link(s)")
        for change in item.changes:
            out.line(f"  {change}")
    for notice in result.notices:
        out.warn(notice)


def _print_id(app: App, result: RepairIdResult) -> None:
    out = app.out
    out.line(f"{result.old_id} -> {result.new_id}  {result.body.as_posix()}")
    for link in result.rewritten:
        out.line(
            f"  rewrote {link.source} {link.type} -> "
            f"{link.old_target} to {link.new_target}"
        )
    for entry in result.manual:
        out.line(f"  manual: {entry}")
    for notice in result.notices:
        out.warn(notice)
