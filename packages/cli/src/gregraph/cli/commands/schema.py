"""``gregraph schema`` (AGENT_READINESS §4.1, AGENT-021): the rulebook.

One call answers "what does this repository allow": config (id prefix,
baseline branch, versioning/graph/assets/CR policy), configured types, the
five kinds, the nine edge rules with their §6.1 guidance, the active
templates with their sections, and the CR lifecycle. ``--type`` narrows
``types``/``templates``; unknown names refuse ``E-TYPE-UNKNOWN`` (exit 4).
Thin: parse → :func:`gregraph.core.operations.describe_schema` → format.
"""

from __future__ import annotations

import argparse
import dataclasses

from gregraph.cli.main import App
from gregraph.core.operations import SchemaInfo, describe_schema


def _json_payload(info: SchemaInfo) -> dict[str, object]:
    """The §4.1 ``schema --json`` object."""
    return {
        "schema": info.schema_,
        "tool_version": info.tool_version,
        "id_prefix": info.id_prefix,
        "baseline_branch": info.baseline_branch,
        "versioning": info.versioning,
        "graph": info.graph,
        "assets": info.assets,
        "cr": info.cr,
        "types": {name: dataclasses.asdict(spec) for name, spec in info.types.items()},
        "kinds": list(info.kinds),
        "edge_rules": [dataclasses.asdict(rule) for rule in info.edge_rules],
        "templates": {
            name: {
                "latest_version": template.latest_version,
                "versions": list(template.versions),
                "deprecated": template.deprecated,
                "breaking": template.breaking,
                "description": template.description,
                "sections": [
                    section.model_dump(mode="json") for section in template.sections
                ],
            }
            for name, template in info.templates.items()
        },
        "cr_lifecycle": {
            "statuses": list(info.cr_lifecycle.statuses),
            "transitions": {
                status: list(targets)
                for status, targets in info.cr_lifecycle.transitions.items()
            },
            "scope_intents": list(info.cr_lifecycle.scope_intents),
        },
    }


def _print_config(app: App, info: SchemaInfo) -> None:
    out = app.out
    out.line(f"schema {info.schema_}  (tool {info.tool_version})")
    out.mapping_lines(
        {
            "id prefix": info.id_prefix,
            "baseline branch": info.baseline_branch,
        }
    )
    out.line()
    for title, section in (
        ("versioning", info.versioning),
        ("graph", info.graph),
        ("assets", info.assets),
        ("cr", info.cr),
    ):
        out.line(f"{title}:")
        for key in sorted(section):
            out.line(f"  {key}: {section[key]}")
        out.line()


def _print_types(app: App, info: SchemaInfo) -> None:
    out = app.out
    out.line("types:")
    out.table(
        ["TYPE", "KIND", "FOLDER", "TEMPLATE", "ID-PREFIX", "DESCRIPTION"],
        [
            [
                name,
                spec.kind,
                spec.folder,
                spec.template,
                spec.id_prefix,
                spec.description,
            ]
            for name, spec in sorted(info.types.items())
        ],
    )
    out.line(f"kinds: {', '.join(info.kinds)}")
    out.line()


def _print_edge_rules(app: App, info: SchemaInfo) -> None:
    out = app.out
    out.line("edge rules:")
    out.table(
        [
            "TYPE",
            "DIRECTION",
            "HIERARCHICAL",
            "ACYCLIC",
            "SOURCE KINDS",
            "TARGET KINDS",
            "SAME-KIND-ONLY",
            "EXCLUDES",
        ],
        [
            [
                rule.type,
                rule.direction,
                "yes" if rule.hierarchical else "no",
                "yes" if rule.acyclic else "no",
                ", ".join(rule.source_kinds),
                ", ".join(rule.target_kinds),
                "yes" if rule.same_kind_only else "no",
                ", ".join(
                    [
                        *rule.mutually_exclusive_with,
                        *(
                            f"{other} (opposite)"
                            for other in rule.mutually_exclusive_opposite
                        ),
                    ]
                ),
            ]
            for rule in info.edge_rules
        ],
    )
    for rule in info.edge_rules:
        if rule.description:
            out.line(f"  {rule.type}: {rule.description}")
    out.line()


def _print_templates(app: App, info: SchemaInfo) -> None:
    out = app.out
    out.line("templates:")
    for name, template in sorted(info.templates.items()):
        versions = ", ".join(f"v{version}" for version in template.versions)
        flags = "  [deprecated]" if template.deprecated else ""
        flags += "  [breaking]" if template.breaking else ""
        out.line(f"  {name} v{template.latest_version} ({versions}){flags}")
        if template.description:
            out.line(f"    {template.description}")
        for section in template.sections:
            required = "required" if section.required else "optional"
            placeholder = f" — {section.placeholder}" if section.placeholder else ""
            aliases = (
                f" (aliases: {', '.join(section.renamed_from)})"
                if section.renamed_from
                else ""
            )
            out.line(f"    ## {section.heading} ({required}){aliases}{placeholder}")
    out.line()


def _print_cr_lifecycle(app: App, info: SchemaInfo) -> None:
    out = app.out
    out.line("CR lifecycle:")
    out.line(f"  statuses: {', '.join(info.cr_lifecycle.statuses)}")
    out.line("  transitions:")
    for status in info.cr_lifecycle.statuses:
        targets = info.cr_lifecycle.transitions.get(status, ())
        out.line(f"    {status}: {', '.join(targets)}")
    out.line(f"  scope intents: {', '.join(info.cr_lifecycle.scope_intents)}")


def run(args: argparse.Namespace, app: App) -> int:
    workspace = app.open_workspace()
    info = describe_schema(workspace, type=getattr(args, "type", None))
    if app.out.json_mode:
        app.out.json(_json_payload(info))
        return 0
    _print_config(app, info)
    _print_types(app, info)
    _print_edge_rules(app, info)
    _print_templates(app, info)
    _print_cr_lifecycle(app, info)
    return 0
