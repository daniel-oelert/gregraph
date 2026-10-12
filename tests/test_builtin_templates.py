"""Golden tests for the 14 shipped built-in templates (S4 data, appendix B.2).

Every template must load through ``TemplateDescriptor``, render with dummy
variables, and expose exactly the section headings/required flags of
appendix B.2. The engine lives in ``gregraph.core.templates`` (S5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from gregraph.core.models import TemplateDescriptor
from gregraph.core.storage import canonical_json_bytes

BUILTIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "core"
    / "src"
    / "gregraph"
    / "builtin_templates"
)

# Appendix B.2: "Sections (required in bold)".
EXPECTED_SECTIONS: dict[str, list[tuple[str, bool]]] = {
    "assumption": [
        ("Assumption", True),
        ("Impact if false", True),
        ("Validation plan", False),
        ("Notes", False),
    ],
    "change-request": [
        ("Motivation", True),
        ("Proposed change", True),
        ("Impact", True),
        ("Resolution", False),
        ("Notes", False),
    ],
    "constraint": [
        ("Constraint", True),
        ("Source", True),
        ("Rationale", False),
        ("Notes", False),
    ],
    "context": [
        ("Context", True),
        ("Rationale", True),
        ("Assumptions", False),
        ("Out of scope", False),
    ],
    "decision": [
        ("Context", True),
        ("Decision", True),
        ("Consequences", True),
        ("Alternatives considered", False),
    ],
    "design": [
        ("Description", True),
        ("Decision drivers", True),
        ("Alternatives considered", False),
        ("Consequences", False),
        ("Notes", False),
    ],
    "epic": [
        ("Hypothesis", True),
        ("Rationale", True),
        ("Scope", False),
        ("Notes", False),
    ],
    "feature": [
        ("Description", True),
        ("Benefit", True),
        ("Scope", False),
        ("Notes", False),
    ],
    "goal": [
        ("Goal", True),
        ("Rationale", True),
        ("Success indicators", False),
        ("Notes", False),
    ],
    "requirement-ears": [
        ("Statement", True),
        ("Rationale", True),
        ("Fit criterion", False),
        ("Notes", False),
    ],
    "stakeholder": [
        ("Role", True),
        ("Interests", True),
        ("Contact", False),
        ("Notes", False),
    ],
    "term": [("Definition", True), ("Notes", False)],
    "test-case": [
        ("Objective", True),
        ("Preconditions", True),
        ("Steps", True),
        ("Expected result", True),
        ("Notes", False),
    ],
    "user-story": [
        ("Story", True),
        ("Acceptance criteria", True),
        ("Rationale", False),
        ("Notes", False),
    ],
}

DUMMY_VARS: dict[str, object] = {
    "title": "Dummy title",
    "id": "RE-000000",
    "type": "user-story",
    "kind": "requirement",
    "created": "2026-01-01T00:00:00Z",
    "author": "dummy",
    "sections": [],
}


def _names() -> list[str]:
    return sorted(p.name for p in BUILTIN_ROOT.iterdir() if p.is_dir())


def _descriptor(name: str) -> TemplateDescriptor:
    path = BUILTIN_ROOT / name / "v1" / "template.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return TemplateDescriptor.model_validate(data)


def _render(name: str) -> str:
    text = (BUILTIN_ROOT / name / "v1" / "template.md").read_text(encoding="utf-8")
    env = SandboxedEnvironment(undefined=StrictUndefined, keep_trailing_newline=True)
    return env.from_string(text).render(**DUMMY_VARS)


def test_fourteen_templates_shipped() -> None:
    assert _names() == sorted(EXPECTED_SECTIONS)


@pytest.mark.parametrize("name", sorted(EXPECTED_SECTIONS))
def test_descriptor_fields(name: str) -> None:
    desc = _descriptor(name)
    assert desc.schema_ == 1
    assert desc.name == name
    assert desc.version == 1
    assert desc.deprecated is False
    assert desc.breaking is False
    assert desc.description


@pytest.mark.parametrize("name", sorted(EXPECTED_SECTIONS))
def test_section_table_matches_appendix_b2(name: str) -> None:
    desc = _descriptor(name)
    assert [(s.heading, s.required) for s in desc.sections] == EXPECTED_SECTIONS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_SECTIONS))
def test_render_starts_with_h1(name: str) -> None:
    assert _render(name).splitlines()[0] == f"# {DUMMY_VARS['title']}"


@pytest.mark.parametrize("name", sorted(EXPECTED_SECTIONS))
def test_render_headings_match_descriptor(name: str) -> None:
    desc = _descriptor(name)
    lines = _render(name).splitlines()
    headings = [ln[3:].strip() for ln in lines if ln.startswith("## ")]
    assert headings == [s.heading for s in desc.sections]


@pytest.mark.parametrize("name", sorted(EXPECTED_SECTIONS))
def test_placeholders_are_italic_next_line(name: str) -> None:
    desc = _descriptor(name)
    lines = _render(name).splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        section = next(s for s in desc.sections if s.heading == line[3:].strip())
        if section.placeholder:
            assert lines[index + 1] == f"*{section.placeholder}*"


@pytest.mark.parametrize("name", sorted(EXPECTED_SECTIONS))
def test_only_h1_uses_variables(name: str) -> None:
    text = (BUILTIN_ROOT / name / "v1" / "template.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            assert "{{ title }}" in line
        else:
            assert "{{" not in line and "{%" not in line


def test_template_json_is_canonical() -> None:
    for name in _names():
        desc = _descriptor(name)
        raw = (BUILTIN_ROOT / name / "v1" / "template.json").read_bytes()
        assert raw == canonical_json_bytes(desc), name
