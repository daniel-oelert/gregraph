"""``gregraph repair`` (spec §13.19, §7.2, §12.6, §4.4): repair damaged data.

``versions`` recomputes conflicted sidecars (conflict markers: ``version =
max(versions seen) + 1``, hashes and clamped/de-duplicated links);
``regenerate-id PATH`` fixes an ``E-ID-DUPLICATE`` with a fresh UUID/ID;
``cache`` deletes and rebuilds the index cache; ``agents`` regenerates
``AGENTS.md`` and ``.agents/skills/gregraph/SKILL.md`` (AGENT_READINESS
§7.3, AGENT-033). Every subcommand supports ``--json`` (§2.4.3). Invoked
without a subcommand, the §12.6 merge-conflict guidance is printed (spec
§13.19). Thin: parse → ``gregraph.core.operations.repair_*`` → format.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gregraph.cli.main import App, UsageError
from gregraph.core.operations import (
    RepairAgentsResult,
    RepairCacheResult,
    RepairIdResult,
    RepairVersionsResult,
    repair_agents,
    repair_cache,
    repair_regenerate_id,
    repair_versions,
)
from gregraph.core.validation import report_payload
from gregraph.core.versioning import repair_guidance

_SUBCOMMANDS = ("versions", "regenerate-id", "cache", "agents")


def run(args: argparse.Namespace, app: App) -> int:
    command = getattr(args, "repair_cmd", None)
    if command is None:
        app.out.line(f"usage: gregraph repair {{{','.join(_SUBCOMMANDS)}}} ...")
        app.out.line()
        for line in repair_guidance():
            app.out.line(line)
        raise UsageError(
            f"repair takes exactly one subcommand: {', '.join(_SUBCOMMANDS)}"
        )
    workspace = app.open_workspace()
    if command == "versions":
        return _versions(app, repair_versions(workspace))
    if command == "regenerate-id":
        return _regenerate_id(app, repair_regenerate_id(workspace, Path(args.path)))
    if command == "agents":
        return _agents(app, repair_agents(workspace))
    return _cache(app, repair_cache(workspace))


def _versions(app: App, result: RepairVersionsResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "repaired": [
                    {
                        "path": item.path.as_posix(),
                        "version": item.version,
                        "versions_seen": list(item.versions_seen),
                        "clamped_links": item.clamped_links,
                        "deduplicated_links": item.deduplicated_links,
                        "changes": list(item.changes),
                    }
                    for item in result.repaired
                ],
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
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
    return 0


def _regenerate_id(app: App, result: RepairIdResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "old_id": result.old_id,
                "new_id": result.new_id,
                "uuid": str(result.uuid),
                "body": result.body.as_posix(),
                "sidecar": result.sidecar.as_posix(),
                "rewritten": [
                    {
                        "source": rewritten.source,
                        "type": rewritten.type,
                        "old_target": rewritten.old_target,
                        "new_target": rewritten.new_target,
                    }
                    for rewritten in result.rewritten
                ],
                "manual": list(result.manual),
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
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
    return 0


def _cache(app: App, result: RepairCacheResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "file_count": result.file_count,
                "types_seen": result.types_seen,
                "templates_seen": result.templates_seen,
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
    app.out.line(
        f"cache rebuilt: {result.file_count} file(s), "
        f"{result.types_seen} type(s), {result.templates_seen} template(s)"
    )
    return 0


def _agents(app: App, result: RepairAgentsResult) -> int:
    if app.out.json_mode:
        app.out.json(
            {
                "agents_files": [path.as_posix() for path in result.agents_files],
                "changed": [path.as_posix() for path in result.changed],
                "findings": report_payload(result.findings),
                "notices": [*app.recorded_notes, *result.notices],
            }
        )
        return 0
    out = app.out
    if result.changed:
        regenerated = ", ".join(path.as_posix() for path in result.changed)
        out.line(f"regenerated: {regenerated}")
    else:
        out.line("agents files up to date")
    for notice in result.notices:
        out.warn(notice)
    return 0
