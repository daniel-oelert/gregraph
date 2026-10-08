"""Tests for the template engine: loading, resolution, rendering, migration.

Spec §5.5 (template format, versioning, deprecation) and §7.7 (migration
planning). The planner is pure — writing migrated files is S15's job.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gregraph.core.models import TemplateDescriptor
from gregraph.core.templates import (
    MigrationPlan,
    check_deprecated,
    load_template_dir,
    plan_migration,
    render_template,
    resolve_template,
    sections_hash,
)

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _write_template(
    root: Path,
    name: str,
    version: int,
    *,
    body: str | None = None,
    deprecated: bool = False,
    breaking: bool = False,
    sections: list[tuple[str, bool, str]] | None = None,
    renamed: dict[str, list[str]] | None = None,
) -> Path:
    """Create ``<root>/<name>/v<version>/{template.md,template.json}``."""
    directory = root / name / f"v{version}"
    directory.mkdir(parents=True, exist_ok=True)
    if sections is None:
        sections = [("Summary", True, "Write a summary.")]
    renamed = renamed or {}
    desc = TemplateDescriptor.model_validate(
        {
            "schema": 1,
            "name": name,
            "version": version,
            "description": f"{name} v{version}",
            "deprecated": deprecated,
            "breaking": breaking,
            "sections": [
                {
                    "heading": heading,
                    "required": required,
                    "placeholder": placeholder,
                    "renamed_from": renamed.get(heading, []),
                }
                for heading, required, placeholder in sections
            ],
        }
    )
    (directory / "template.json").write_text(
        json.dumps(desc.model_dump(by_alias=True), indent=2) + "\n", encoding="utf-8"
    )
    if body is None:
        lines = ["# {{ title }}", ""]
        for heading, _required, placeholder in sections:
            lines.append(f"## {heading}")
            lines.append(f"*{placeholder}*")
            lines.append("")
        body = "\n".join(lines)
    (directory / "template.md").write_text(body, encoding="utf-8")
    return directory


def _sections(*entries: tuple[str, bool, str]) -> list[tuple[str, bool, str]]:
    return list(entries)


# --------------------------------------------------------------------------
# loading / contiguity / resolution
# --------------------------------------------------------------------------


def test_load_single_version(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    loaded = load_template_dir(tmp_path)
    assert set(loaded) == {"goal"}
    assert len(loaded["goal"]) == 1
    assert loaded["goal"][0].descriptor.version == 1
    assert loaded["goal"][0].descriptor.name == "goal"
    assert "# {{ title }}" in loaded["goal"][0].body


def test_load_multiple_versions_sorted(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    _write_template(tmp_path, "goal", 2)
    _write_template(tmp_path, "goal", 3)
    loaded = load_template_dir(tmp_path)
    assert [t.descriptor.version for t in loaded["goal"]] == [1, 2, 3]


def test_contiguity_gap_rejected(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    _write_template(tmp_path, "goal", 3)
    with pytest.raises(ValueError, match="contiguous|gap"):
        load_template_dir(tmp_path)


def test_contiguity_must_start_at_v1(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 2)
    with pytest.raises(ValueError, match="contiguous|v1"):
        load_template_dir(tmp_path)


def test_resolve_latest_non_deprecated(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    _write_template(tmp_path, "goal", 2)
    _write_template(tmp_path, "goal", 3, deprecated=True)
    loaded = load_template_dir(tmp_path)
    resolved = resolve_template(loaded["goal"])
    assert resolved.descriptor.version == 2


def test_resolve_all_deprecated_raises(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1, deprecated=True)
    loaded = load_template_dir(tmp_path)
    with pytest.raises(ValueError, match="deprecated"):
        resolve_template(loaded["goal"])


def test_resolve_explicit_version(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    _write_template(tmp_path, "goal", 2)
    loaded = load_template_dir(tmp_path)
    resolved = resolve_template(loaded["goal"], version=1)
    assert resolved.descriptor.version == 1


def test_resolve_missing_version_raises(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    loaded = load_template_dir(tmp_path)
    with pytest.raises(ValueError, match="version"):
        resolve_template(loaded["goal"], version=5)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def test_render_replaces_title(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    loaded = load_template_dir(tmp_path)
    out = render_template(
        loaded["goal"][0],
        title="My Goal",
        id="RE-000001",
        type="goal",
        kind="goal",
        created="2026-01-01T00:00:00Z",
        author="alice",
    )
    assert out.startswith("# My Goal")


def test_render_requires_all_variables(tmp_path: Path) -> None:
    _write_template(
        tmp_path,
        "goal",
        1,
        body="# {{ title }} for {{ id }}\n\n## Summary\n*ph*\n",
    )
    loaded = load_template_dir(tmp_path)
    with pytest.raises(Exception, match="id"):  # noqa: B017
        render_template(loaded["goal"][0], title="X")


# --------------------------------------------------------------------------
# deprecation rule
# --------------------------------------------------------------------------


def test_deprecated_without_consent_is_refused(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1, deprecated=True)
    loaded = load_template_dir(tmp_path)["goal"][0]
    finding = check_deprecated(loaded, version_pinned=True, allow_deprecated=False)
    assert finding is not None
    assert finding.code == "W-TEMPLATE-DEPRECATED"
    assert finding.severity == "E"


def test_deprecated_with_consent_allowed(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1, deprecated=True)
    loaded = load_template_dir(tmp_path)["goal"][0]
    assert check_deprecated(loaded, version_pinned=True, allow_deprecated=True) is None


def test_non_deprecated_needs_no_consent(tmp_path: Path) -> None:
    _write_template(tmp_path, "goal", 1)
    loaded = load_template_dir(tmp_path)["goal"][0]
    result = check_deprecated(loaded, version_pinned=False, allow_deprecated=False)
    assert result is None


def test_deprecated_resolved_without_pin_refused(tmp_path: Path) -> None:
    """``new`` without --template-version must not silently pick deprecated."""
    _write_template(tmp_path, "goal", 1, deprecated=True)
    loaded = load_template_dir(tmp_path)["goal"][0]
    finding = check_deprecated(loaded, version_pinned=False, allow_deprecated=False)
    assert finding is not None
    assert finding.severity == "E"


# --------------------------------------------------------------------------
# sections hash
# --------------------------------------------------------------------------


def test_sections_hash_stable_and_order_sensitive() -> None:
    a = TemplateDescriptor.model_validate(
        {
            "schema": 1,
            "name": "t",
            "version": 1,
            "description": "d",
            "deprecated": False,
            "breaking": False,
            "sections": [
                {"heading": "A", "required": True, "placeholder": ""},
                {"heading": "B", "required": False, "placeholder": ""},
            ],
        }
    )
    b = TemplateDescriptor.model_validate(
        {
            "schema": 1,
            "name": "t",
            "version": 1,
            "description": "d",
            "deprecated": False,
            "breaking": False,
            "sections": [
                {"heading": "B", "required": False, "placeholder": ""},
                {"heading": "A", "required": True, "placeholder": ""},
            ],
        }
    )
    assert sections_hash(a) == sections_hash(a)
    assert sections_hash(a) != sections_hash(b)


# --------------------------------------------------------------------------
# migration planner — additive (in-place)
# --------------------------------------------------------------------------


def _body(*sections: tuple[str, str]) -> str:
    lines = ["# Title", ""]
    for heading, content in sections:
        lines.append(f"## {heading}")
        if content:
            lines.append(content)
        lines.append("")
    return "\n".join(lines)


def test_additive_in_place_plan(tmp_path: Path) -> None:
    _write_template(tmp_path, "t", 1, sections=_sections(("Alpha", True, "A ph")))
    _write_template(
        tmp_path,
        "t",
        2,
        breaking=False,
        sections=_sections(("Alpha", True, "A ph"), ("Beta", True, "B ph")),
    )
    loaded = load_template_dir(tmp_path)["t"]
    current, target = loaded[0], loaded[1]
    body = _body(("Alpha", "real alpha"))
    plan = plan_migration(current=current, target=target, body=body, chain=[target])

    assert plan.kind == "in-place"
    assert "## Beta" in plan.new_body
    assert "*B ph*" in plan.new_body
    assert "real alpha" in plan.new_body
    assert "## Alpha" in plan.new_body
    # Beta is inserted after Alpha (template position).
    assert plan.new_body.index("## Alpha") < plan.new_body.index("## Beta")
    assert plan.inserted == ["Beta"]


def test_additive_leaves_unknown_sections_in_place(tmp_path: Path) -> None:
    _write_template(tmp_path, "t", 1, sections=_sections(("Alpha", True, "A ph")))
    _write_template(
        tmp_path,
        "t",
        2,
        sections=_sections(("Alpha", True, "A ph"), ("Beta", True, "B ph")),
    )
    loaded = load_template_dir(tmp_path)["t"]
    body = _body(("Alpha", "real alpha"), ("Extra", "user extra"))
    plan = plan_migration(
        current=loaded[0], target=loaded[1], body=body, chain=[loaded[1]]
    )

    assert plan.kind == "in-place"
    assert "## Extra" in plan.new_body
    assert "user extra" in plan.new_body
    assert plan.unknown == ["Extra"]
    assert any(f.code == "W-SECTION-UNKNOWN" for f in plan.findings)


# --------------------------------------------------------------------------
# migration planner — renamed (in-place with renamed_from)
# --------------------------------------------------------------------------


def test_renamed_in_place_plan(tmp_path: Path) -> None:
    _write_template(tmp_path, "t", 1, sections=_sections(("Old name", True, "ph")))
    _write_template(
        tmp_path,
        "t",
        2,
        sections=_sections(("New name", True, "ph")),
        renamed={"New name": ["Old name"]},
    )
    loaded = load_template_dir(tmp_path)["t"]
    body = _body(("Old name", "kept content"))
    plan = plan_migration(
        current=loaded[0], target=loaded[1], body=body, chain=[loaded[1]]
    )

    assert plan.kind == "in-place"
    assert "## New name" in plan.new_body
    assert "## Old name" not in plan.new_body
    assert "kept content" in plan.new_body
    assert plan.renamed == [("Old name", "New name")]


# --------------------------------------------------------------------------
# migration planner — breaking (superseding)
# --------------------------------------------------------------------------


def test_breaking_superseding_plan(tmp_path: Path) -> None:
    _write_template(tmp_path, "t", 1, sections=_sections(("Alpha", True, "A ph")))
    _write_template(
        tmp_path,
        "t",
        2,
        breaking=True,
        sections=_sections(("Gamma", True, "G ph")),
    )
    loaded = load_template_dir(tmp_path)["t"]
    body = _body(("Alpha", "real alpha"), ("Extra", "user extra"))
    plan = plan_migration(
        current=loaded[0], target=loaded[1], body=body, chain=[loaded[1]]
    )

    assert plan.kind == "superseding"
    assert "## Gamma" in plan.new_body
    assert "*G ph*" in plan.new_body
    # Unmatched content is preserved under the migration bucket.
    assert "## Unmapped content (migration)" in plan.new_body
    assert "real alpha" in plan.new_body
    assert "user extra" in plan.new_body
    assert plan.unmapped == ["Alpha", "Extra"]
    assert plan.manual_attention, "superseding plan must list manual attention items"


def test_breaking_in_chain_forces_superseding(tmp_path: Path) -> None:
    """A breaking step anywhere in the chain blocks in-place migration."""
    _write_template(tmp_path, "t", 1, sections=_sections(("A", True, "a")))
    _write_template(
        tmp_path, "t", 2, breaking=True, sections=_sections(("B", True, "b"))
    )
    _write_template(tmp_path, "t", 3, sections=_sections(("C", True, "c")))
    loaded = load_template_dir(tmp_path)["t"]
    body = _body(("A", "content"))
    plan = plan_migration(
        current=loaded[0], target=loaded[2], body=body, chain=loaded[1:]
    )
    assert plan.kind == "superseding"


def test_supersede_flag_forces_superseding(tmp_path: Path) -> None:
    _write_template(tmp_path, "t", 1, sections=_sections(("A", True, "a")))
    _write_template(tmp_path, "t", 2, sections=_sections(("B", True, "b")))
    loaded = load_template_dir(tmp_path)["t"]
    plan = plan_migration(
        current=loaded[0],
        target=loaded[1],
        body=_body(("A", "content")),
        chain=[loaded[1]],
        supersede=True,
    )
    assert plan.kind == "superseding"


# --------------------------------------------------------------------------
# planner purity
# --------------------------------------------------------------------------


def test_planner_does_not_write_files(tmp_path: Path) -> None:
    _write_template(tmp_path, "t", 1, sections=_sections(("A", True, "a")))
    secs = _sections(("A", True, "a"), ("B", True, "b"))
    _write_template(tmp_path, "t", 2, sections=secs)
    loaded = load_template_dir(tmp_path)["t"]
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    plan_migration(
        current=loaded[0],
        target=loaded[1],
        body=_body(("A", "content")),
        chain=[loaded[1]],
    )
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
    assert isinstance(
        plan := plan_migration(
            current=loaded[0],
            target=loaded[1],
            body=_body(("A", "x")),
            chain=[loaded[1]],
        ),
        MigrationPlan,
    )
    assert isinstance(plan.new_body, str)
