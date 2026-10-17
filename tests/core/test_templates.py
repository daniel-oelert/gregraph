"""Tests for the template engine: loading, resolution, rendering, migration.

Spec §5.5 (template format, versioning, deprecation) and §7.7 (migration
planning). The planner is pure — writing migrated files is S15's job.

Also covers the AGENT_READINESS §3.4 authoring helpers (template-guided
section assembly, required-section checks, whole-body preparation —
AGENT-015..019) and the ``storage.read_text_file`` helper used by
``--section-file``/``--body-file``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gregraph.core.models import OperationRefused, TemplateDescriptor
from gregraph.core.storage import read_text_file
from gregraph.core.templates import (
    MigrationPlan,
    assemble_sections,
    check_deprecated,
    check_required_sections,
    is_section_unfilled,
    load_template_dir,
    match_template_section,
    plan_migration,
    prepare_whole_body,
    render_template,
    resolve_section_inputs,
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


# --------------------------------------------------------------------------
# agent authoring: template-guided sections (§3.4, AGENT-015..019)
# --------------------------------------------------------------------------

_STORY_PH = "As a <role>, I want <capability>, so that <benefit>."
_STORY_SECTIONS: list[tuple[str, bool, str]] = [
    ("Story", True, _STORY_PH),
    ("Acceptance criteria", True, "Given … When … Then …"),
    ("Rationale", False, ""),
    ("Notes", False, "Optional notes."),
]
_STORY_RENAMED: dict[str, list[str]] = {"Rationale": ["Motivation"]}


def _descriptor(
    sections: list[tuple[str, bool, str]] | None = None,
    renamed: dict[str, list[str]] | None = None,
    *,
    name: str = "user-story",
    version: int = 1,
) -> TemplateDescriptor:
    """Build a descriptor in memory (no template files on disk)."""
    if sections is None:
        sections = _STORY_SECTIONS
    renamed = renamed or {}
    return TemplateDescriptor.model_validate(
        {
            "schema": 1,
            "name": name,
            "version": version,
            "description": f"{name} v{version}",
            "deprecated": False,
            "breaking": False,
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


# -- storage.read_text_file (CLI file payloads; §3.5) -----------------------


def test_read_text_file_decodes_utf8_and_normalises_crlf(tmp_path: Path) -> None:
    path = tmp_path / "payload.md"
    path.write_bytes("café\r\nau\r\nlait\nfin".encode())
    assert read_text_file(path) == "café\nau\nlait\nfin"


def test_read_text_file_normalises_lone_cr(tmp_path: Path) -> None:
    path = tmp_path / "payload.md"
    path.write_bytes(b"one\rtwo\rthree")
    assert read_text_file(path) == "one\ntwo\nthree"


def test_read_text_file_keeps_plain_lf(tmp_path: Path) -> None:
    path = tmp_path / "payload.md"
    path.write_text("already\nnormal\n", encoding="utf-8")
    assert read_text_file(path) == "already\nnormal\n"


# -- section unfilled rule (§5.5 emptiness, AGENT-018) ----------------------


def test_is_section_unfilled_matches_unfilled_spellings() -> None:
    for content in (
        "",
        "   \n\t ",
        "<!-- todo -->",
        _STORY_PH,
        f"*{_STORY_PH}*",
        f"**{_STORY_PH}**",
    ):
        assert is_section_unfilled(content, _STORY_PH), content
    assert not is_section_unfilled("Real content.", _STORY_PH)


def test_is_section_unfilled_without_placeholder() -> None:
    assert is_section_unfilled("", "")
    assert is_section_unfilled("<!-- only a comment -->", "")
    # emphasis text is real content when the section has no placeholder
    assert not is_section_unfilled("*emphasis*", "")


# -- heading matching (§3.4 rule 2, AGENT-017) ------------------------------


def test_match_template_section_exact_and_trimmed() -> None:
    descriptor = _descriptor()
    assert match_template_section(descriptor, "Story").heading == "Story"
    assert match_template_section(descriptor, "  Story  ").heading == "Story"


def test_match_template_section_renamed_from_alias() -> None:
    descriptor = _descriptor(_STORY_SECTIONS, _STORY_RENAMED)
    assert match_template_section(descriptor, "Motivation").heading == "Rationale"


def test_match_template_section_heading_wins_over_alias() -> None:
    descriptor = _descriptor(
        [("Alpha", True, "a"), ("Beta", False, "b")], {"Beta": ["Alpha"]}
    )
    assert match_template_section(descriptor, "Alpha").heading == "Alpha"


def test_match_template_section_is_case_sensitive() -> None:
    with pytest.raises(OperationRefused) as refused:
        match_template_section(_descriptor(), "story")
    assert refused.value.finding.code == "E-SECTION-UNKNOWN"


def test_match_template_section_unknown_is_self_describing() -> None:
    descriptor = _descriptor(_STORY_SECTIONS, _STORY_RENAMED)
    with pytest.raises(OperationRefused) as refused:
        match_template_section(descriptor, "Acceptance Criteria")
    finding = refused.value.finding
    assert finding.code == "E-SECTION-UNKNOWN"
    assert finding.severity == "E"
    assert finding.subject == "user-story/v1"
    assert finding.message == (
        "section 'Acceptance Criteria' is not a section of template "
        "'user-story' v1 (exact, case-sensitive; see details.template_sections)"
    )
    assert finding.details is not None
    assert finding.details["given_heading"] == "Acceptance Criteria"
    assert finding.details["template"] == {"name": "user-story", "version": 1}
    assert finding.details["template_sections"] == [
        sec.model_dump(mode="json") for sec in descriptor.sections
    ]


# -- input resolution (§3.4 rule 1) ------------------------------------------


def test_resolve_section_inputs_canonical_and_alias() -> None:
    resolved = resolve_section_inputs(
        _descriptor(_STORY_SECTIONS, _STORY_RENAMED),
        [("  Story  ", "story text"), ("Motivation", "why")],
    )
    assert resolved == {"Story": "story text", "Rationale": "why"}


def test_resolve_section_inputs_normalises_content() -> None:
    resolved = resolve_section_inputs(_descriptor(), [("Story", "a\r\nb\rc")])
    assert resolved == {"Story": "a\nb\nc"}


def test_resolve_section_inputs_rejects_duplicate_heading() -> None:
    with pytest.raises(ValueError, match="duplicate section heading 'Story'"):
        resolve_section_inputs(_descriptor(), [("Story", "one"), ("Story", "two")])


def test_resolve_section_inputs_rejects_alias_duplicate() -> None:
    with pytest.raises(ValueError, match="duplicate section heading 'Rationale'"):
        resolve_section_inputs(
            _descriptor(_STORY_SECTIONS, _STORY_RENAMED),
            [("Rationale", "one"), ("Motivation", "two")],
        )


def test_resolve_section_inputs_empty() -> None:
    assert resolve_section_inputs(_descriptor(), []) == {}


# -- assembly (§3.4 rule 3, AGENT-015/016) -----------------------------------


def test_assemble_sections_canonical_order_and_placeholders() -> None:
    body = assemble_sections(
        _descriptor(),
        title="My Story",
        content={"Notes": "kept note", "Story": "the story"},
    )
    assert body == (
        "# My Story\n"
        "\n"
        "## Story\n"
        "\n"
        "the story\n"
        "\n"
        "## Acceptance criteria\n"
        "\n"
        "*Given … When … Then …*\n"
        "\n"
        "## Rationale\n"
        "\n"
        "## Notes\n"
        "\n"
        "kept note\n"
    )


def test_assemble_sections_empty_provided_content_is_bare_heading() -> None:
    body = assemble_sections(
        _descriptor(), title="T", content={"Story": "", "Notes": "\n\n"}
    )
    assert "## Story\n\n## Acceptance criteria" in body
    assert body.endswith("## Notes\n")


def test_assemble_sections_edit_preserves_unmentioned_verbatim() -> None:
    base = (
        "# Old\n"
        "\n"
        "## Story\n"
        "\n"
        "old story\n"
        "\n"
        "## Notes\n"
        "\n"
        "kept  notes\n"
        "\n"
        "## Extra\n"
        "\n"
        "user extra\n"
    )
    body = assemble_sections(
        _descriptor([("Story", True, _STORY_PH), ("Notes", False, "Optional notes.")]),
        title="New",
        content={"Story": "new story"},
        base_body=base,
        preserve_existing=True,
    )
    assert body == (
        "# New\n"
        "\n"
        "## Story\n"
        "\n"
        "new story\n"
        "\n"
        "## Notes\n"
        "\n"
        "kept  notes\n"
        "\n"
        "## Extra\n"
        "\n"
        "user extra\n"
    )


def test_assemble_sections_edit_round_trips_byte_identical() -> None:
    base = "# Old\n\n## Notes\n\nkept notes\n"
    body = assemble_sections(
        _descriptor([("Notes", False, "Optional notes.")]),
        title="Old",
        content={},
        base_body=base,
        preserve_existing=True,
    )
    assert body == base


def test_assemble_sections_edit_is_idempotent() -> None:
    base = "# Old\n\n## Story\n\nold story\n\n## Notes\n\nkept  notes\n"
    once = assemble_sections(
        _descriptor(),
        title="Old",
        content={"Story": "new story"},
        base_body=base,
        preserve_existing=True,
    )
    twice = assemble_sections(
        _descriptor(),
        title="Old",
        content={"Story": "new story"},
        base_body=once,
        preserve_existing=True,
    )
    assert twice == once


def test_assemble_sections_edit_keeps_extra_sections_at_end() -> None:
    base = (
        "# Old\n"
        "\n"
        "## Story\n"
        "\n"
        "s\n"
        "\n"
        "## Zed\n"
        "\n"
        "zed content\n"
        "\n"
        "## Yankee\n"
        "\n"
        "yankee content\n"
    )
    body = assemble_sections(
        _descriptor([("Story", True, "ph")]),
        title="Old",
        content={},
        base_body=base,
        preserve_existing=True,
    )
    assert "zed content" in body
    assert "yankee content" in body
    assert body.index("## Story") < body.index("## Zed") < body.index("## Yankee")
    assert body.endswith("## Yankee\n\nyankee content\n")


def test_assemble_sections_edit_preserves_preamble() -> None:
    base = "# Old\n\nIntro prose.\n\n## Notes\n\nkept\n"
    body = assemble_sections(
        _descriptor([("Notes", False, "")]),
        title="New",
        content={},
        base_body=base,
        preserve_existing=True,
    )
    assert body == "# New\n\nIntro prose.\n\n## Notes\n\nkept\n"


def test_assemble_sections_creation_drops_preamble() -> None:
    base = "# Old\n\nIntro prose.\n\n## Notes\n\nkept\n"
    body = assemble_sections(
        _descriptor([("Notes", False, "")]),
        title="New",
        content={},
        base_body=base,
    )
    assert body == "# New\n\n## Notes\n\nkept\n"


def test_assemble_sections_resolves_renamed_sections() -> None:
    base = "# Old\n\n## Motivation\n\nbecause\n"
    descriptor = _descriptor(_STORY_SECTIONS, _STORY_RENAMED)
    edited = assemble_sections(
        descriptor, title="Old", content={}, base_body=base, preserve_existing=True
    )
    assert "## Rationale\n\nbecause" in edited
    assert "## Motivation" not in edited
    created = assemble_sections(descriptor, title="Old", content={}, base_body=base)
    assert "## Rationale\n\nbecause" in created
    assert "## Motivation" not in created
    assert "*Optional notes.*" in created


# -- required-section check (§3.4 rules 5–6, AGENT-018) ----------------------


def test_check_required_sections_passes_when_filled() -> None:
    body = (
        "# T\n\n## Story\n\nreal story\n\n## Acceptance criteria\n\nGiven When Then\n"
    )
    check_required_sections(_descriptor(), body)


def test_check_required_sections_accepts_renamed_alias_body() -> None:
    descriptor = _descriptor(
        [("Context", True, "ctx ph"), ("Notes", False, "")],
        {"Context": ["Background"]},
    )
    check_required_sections(descriptor, "# T\n\n## Background\n\nfilled\n")


def test_check_required_sections_refuses_missing() -> None:
    descriptor = _descriptor()
    with pytest.raises(OperationRefused) as refused:
        check_required_sections(descriptor, "# T\n")
    finding = refused.value.finding
    assert finding.code == "E-SECTION-REQUIRED-EMPTY"
    assert finding.severity == "E"
    assert finding.subject == "user-story/v1"
    assert finding.message == (
        "required section(s) 'Story', 'Acceptance criteria' of template "
        "'user-story' v1 are missing or empty"
    )
    assert finding.details is not None
    assert finding.details["missing_required"] == ["Story", "Acceptance criteria"]
    assert finding.details["template"] == {"name": "user-story", "version": 1}
    assert finding.details["template_sections"] == [
        sec.model_dump(mode="json") for sec in descriptor.sections
    ]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   \n\t ",
        "<!-- todo only -->",
        _STORY_PH,
        f"*{_STORY_PH}*",
        f"**{_STORY_PH}**",
    ],
)
def test_check_required_sections_refuses_unfilled_story(content: str) -> None:
    body = f"# T\n\n## Story\n\n{content}\n"
    with pytest.raises(OperationRefused) as refused:
        check_required_sections(
            _descriptor([("Story", True, _STORY_PH), ("Notes", False, "")]), body
        )
    finding = refused.value.finding
    assert finding.code == "E-SECTION-REQUIRED-EMPTY"
    assert finding.details is not None
    assert finding.details["missing_required"] == ["Story"]


def test_check_required_sections_require_provided() -> None:
    descriptor = _descriptor([("Story", True, "ph"), ("Notes", False, "")])
    body = "# T\n\n## Story\n\nreal story\n"
    check_required_sections(
        descriptor, body, provided_headings={"Story"}, require_provided=True
    )
    with pytest.raises(OperationRefused) as refused:
        check_required_sections(
            descriptor, body, provided_headings={"Notes"}, require_provided=True
        )
    finding = refused.value.finding
    assert finding.code == "E-SECTION-REQUIRED-EMPTY"
    assert finding.details is not None
    assert finding.details["missing_required"] == ["Story"]


def test_check_required_sections_provided_entry_still_checked() -> None:
    descriptor = _descriptor([("Story", True, "ph")])
    with pytest.raises(OperationRefused) as refused:
        check_required_sections(
            descriptor,
            "# T\n\n## Story\n\n",
            provided_headings={"Story"},
            require_provided=True,
        )
    assert refused.value.finding.details is not None
    assert refused.value.finding.details["missing_required"] == ["Story"]


def test_check_required_sections_subject_override() -> None:
    with pytest.raises(OperationRefused) as refused:
        check_required_sections(
            _descriptor([("Story", True, "ph")]),
            "# T\n",
            subject="USR-000001",
        )
    assert refused.value.finding.subject == "USR-000001"


def test_check_required_sections_ignores_optional_sections() -> None:
    check_required_sections(_descriptor([("Notes", False, "ph")]), "# T\n\n## Notes\n")


# -- whole-body input (§3.4 rule 4, AGENT-019) -------------------------------


def test_prepare_whole_body_replaces_differing_h1_with_notice() -> None:
    body, notices = prepare_whole_body(
        "# Old Title\n\ncontent line\n", title="New Title"
    )
    assert body == "# New Title\n\ncontent line\n"
    assert notices == ["replaced H1 'Old Title' with 'New Title'"]


def test_prepare_whole_body_keeps_matching_h1_without_notice() -> None:
    body, notices = prepare_whole_body("# Same\n\ncontent line\n", title="Same")
    assert body == "# Same\n\ncontent line\n"
    assert notices == []


def test_prepare_whole_body_prepends_missing_h1() -> None:
    body, notices = prepare_whole_body("content line\n", title="New")
    assert body == "# New\n\ncontent line\n"
    assert notices == []


def test_prepare_whole_body_normalises_line_endings_only() -> None:
    body, notices = prepare_whole_body("a\r\nb\rc\r\n", title="T")
    assert body == "# T\n\na\nb\nc\n"
    assert notices == []


def test_prepare_whole_body_empty_body() -> None:
    body, notices = prepare_whole_body("", title="T")
    assert body == "# T\n"
    assert notices == []


def test_prepare_whole_body_blank_lines_only_body() -> None:
    body, notices = prepare_whole_body("\n\n", title="T")
    assert body == "# T\n"
    assert notices == []


def test_prepare_whole_body_adds_trailing_newline() -> None:
    body, _notices = prepare_whole_body("text", title="T")
    assert body == "# T\n\ntext\n"


def test_prepare_whole_body_h1_variants() -> None:
    body, notices = prepare_whole_body("#\tTabbed\n", title="T")
    assert body == "# T\n"
    assert notices == ["replaced H1 'Tabbed' with 'T'"]
    body, notices = prepare_whole_body("#Old\n", title="T")
    assert body == "# T\n\n#Old\n"
    assert notices == []


def test_prepare_whole_body_replaces_h1_after_blank_lines() -> None:
    body, notices = prepare_whole_body("\n\n# Old\n\nx\n", title="New")
    assert body == "\n\n# New\n\nx\n"
    assert notices == ["replaced H1 'Old' with 'New'"]


def test_prepare_whole_body_does_not_treat_h2_as_title() -> None:
    body, notices = prepare_whole_body("## Sub\n\nx\n", title="T")
    assert body == "# T\n\n## Sub\n\nx\n"
    assert notices == []
