"""Tests for ``gregraph.core.models`` (spec §5.4, §5.5, §9.2, §10.2, §14, B.3).

Test-first for S1: appendix B.3 field sets and types, the ``schema`` alias,
the §5.4 mandatory-field set, JSON round-trips, sorted canonical lists, and
the §14 ``Finding`` report shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from gregraph.core.models import (
    AssetRef,
    ChangeRequest,
    Decision,
    Deprecation,
    Document,
    Finding,
    Identity,
    Link,
    ScopeEntry,
    TemplateDescriptor,
    TemplateRef,
    TemplateSection,
    Term,
)

DOCUMENT_MANDATORY = (
    "schema",
    "uuid",
    "id",
    "type",
    "title",
    "created",
    "template",
    "version",
    "body_hash",
    "assets",
    "links",
    "deprecated",
)
DOCUMENT_OPTIONAL = ("tags", "extra", "created_by", "origin_cr")
DOCUMENT_ALL = set(DOCUMENT_MANDATORY) | set(DOCUMENT_OPTIONAL)
CR_KEYS = (
    "schema",
    "uuid",
    "id",
    "title",
    "created",
    "created_by",
    "template",
    "version",
    "body_hash",
    "scope_hash",
    "scope",
    "introduces",
    "status",
    "decisions",
    "branch",
    "external_ref",
    "tags",
    "extra",
)


def _document_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "uuid": "6f3c2f1e-8b3e-4a4c-9a3d-2d0f5b7a9c11",
        "id": "RE-STORY-7F3K2Q",
        "type": "user-story",
        "title": "Upload documents to a knowledge base",
        "created": "2026-09-10T14:02:11Z",
        "created_by": {"name": "Jane Doe", "email": "jane@example.org"},
        "template": {"name": "user-story", "version": 2},
        "version": 3,
        "body_hash": "sha256:" + "9c1d" * 16,
        "assets": [{"path": "upload-flow.png", "hash": "sha256:" + "41ab" * 16}],
        "links": [
            {"type": "depends-on", "target": "RE-FEAT-9PZ0AH", "target_version": 1},
            {"type": "refines", "target": "RE-FEAT-2K7QMB", "target_version": 4},
        ],
        "deprecated": None,
        "tags": [],
        "extra": {},
        "origin_cr": None,
    }
    payload.update(overrides)
    return payload


def _cr_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "uuid": "0b9e7c1a-3d2f-4e8b-9a61-5c4d2e1f0a77",
        "id": "RE-CHG-3M9XA1",
        "title": "Raise knowledge-base upload limit to 200 MB",
        "created": "2026-09-10T09:00:00Z",
        "created_by": {"name": "Jane Doe", "email": "jane@example.org"},
        "template": {"name": "change-request", "version": 1},
        "version": 2,
        "body_hash": "sha256:" + "aa11" * 16,
        "scope_hash": "sha256:" + "bb22" * 16,
        "scope": [
            {"id": "RE-STORY-7F3K2Q", "intent": "modify", "base_version": 3},
            {"id": "RE-FEAT-9PZ0AH", "intent": "supersede", "base_version": 1},
        ],
        "introduces": ["RE-FEAT-Q4M2ZT"],
        "status": "accepted",
        "decisions": [
            {
                "status": "open",
                "at": "2026-09-10T09:00:00Z",
                "by": {"name": "Jane Doe", "email": "jane@example.org"},
                "at_version": 1,
            },
            {
                "status": "accepted",
                "at": "2026-09-12T15:30:00Z",
                "by": {"name": "Max Mustermann", "email": "max@example.org"},
                "at_version": 2,
            },
        ],
        "branch": None,
        "external_ref": None,
        "tags": [],
        "extra": {},
    }
    payload.update(overrides)
    return payload


def _term_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "term": "Knowledge base",
        "slug": "knowledge-base",
        "aliases": ["KB"],
        "created": "2026-09-10T14:02:11Z",
        "created_by": {"name": "Jane Doe", "email": "jane@example.org"},
        "template": {"name": "term", "version": 1},
        "version": 2,
        "body_hash": "sha256:" + "cc33" * 16,
        "deprecated": None,
    }
    payload.update(overrides)
    return payload


def _descriptor_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": 1,
        "name": "user-story",
        "version": 2,
        "description": "User story with Gherkin acceptance criteria",
        "deprecated": False,
        "breaking": False,
        "sections": [
            {
                "heading": "Story",
                "required": True,
                "placeholder": "As a <role>, I want <capability>, so that <benefit>.",
            },
            {
                "heading": "Acceptance criteria",
                "required": True,
                "placeholder": "Given … When … Then …",
            },
            {
                "heading": "Rationale",
                "required": False,
                "placeholder": "",
                "renamed_from": ["Motivation"],
            },
            {"heading": "Notes", "required": False, "placeholder": ""},
        ],
    }
    payload.update(overrides)
    return payload


def _assert_roundtrip(model: Any) -> Any:
    dumped = model.model_dump(mode="json", by_alias=True)
    restored = type(model).model_validate(dumped)
    assert restored == model
    from_text = type(model).model_validate_json(model.model_dump_json(by_alias=True))
    assert from_text == model
    return dumped


def test_identity_roundtrip() -> None:
    identity = Identity(name="Jane Doe", email="jane@example.org")
    dumped = _assert_roundtrip(identity)
    assert dumped == {"name": "Jane Doe", "email": "jane@example.org"}


def test_document_example_payload_parses() -> None:
    document = Document.model_validate(_document_payload())
    assert document.id == "RE-STORY-7F3K2Q"
    assert document.schema_ == 1
    assert document.created_by is not None
    assert document.created_by.name == "Jane Doe"
    assert document.template == TemplateRef(name="user-story", version=2)


def test_document_json_roundtrip() -> None:
    document = Document.model_validate(_document_payload())
    dumped = _assert_roundtrip(document)
    assert set(dumped) == DOCUMENT_ALL
    assert dumped["schema"] == 1


def test_document_dump_serialises_schema_alias() -> None:
    document = Document.model_validate(_document_payload())
    dumped = document.model_dump(mode="json", by_alias=True)
    assert "schema" in dumped
    assert "schema_" not in dumped


def test_document_accepts_python_field_names() -> None:
    payload = _document_payload()
    payload["schema_"] = payload.pop("schema")
    document = Document.model_validate(payload)
    assert document.schema_ == 1


@pytest.mark.parametrize("field", DOCUMENT_MANDATORY)
def test_document_mandatory_fields_enforced(field: str) -> None:
    payload = _document_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        Document.model_validate(payload)


@pytest.mark.parametrize("field", DOCUMENT_OPTIONAL)
def test_document_optional_fields_may_be_absent(field: str) -> None:
    payload = _document_payload()
    del payload[field]
    document = Document.model_validate(payload)
    dumped = document.model_dump(mode="json", by_alias=True)
    assert set(dumped) == DOCUMENT_ALL


def test_document_links_sorted_by_type_and_target() -> None:
    document = Document.model_validate(_document_payload())
    assert [(link.type, link.target) for link in document.links] == [
        ("depends-on", "RE-FEAT-9PZ0AH"),
        ("refines", "RE-FEAT-2K7QMB"),
    ]


def test_document_rejects_unknown_link_type() -> None:
    with pytest.raises(ValidationError):
        Document.model_validate(
            _document_payload(
                links=[
                    {"type": "blocks", "target": "RE-FEAT-2K7QMB", "target_version": 1}
                ]
            )
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": 0},
        {
            "links": [
                {"type": "refines", "target": "RE-FEAT-2K7QMB", "target_version": 0}
            ]
        },
        {"template": {"name": "user-story", "version": 0}},
    ],
)
def test_document_rejects_versions_below_one(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Document.model_validate(_document_payload(**overrides))


def test_document_rejects_non_string_extra_values() -> None:
    with pytest.raises(ValidationError):
        Document.model_validate(_document_payload(extra={"priority": 1}))  # type: ignore[dict-item]


def test_link_roundtrip() -> None:
    link = Link(type="refines", target="RE-FEAT-2K7QMB", target_version=4)
    assert _assert_roundtrip(link) == {
        "type": "refines",
        "target": "RE-FEAT-2K7QMB",
        "target_version": 4,
    }


def test_asset_ref_roundtrip() -> None:
    asset = AssetRef(path="upload-flow.png", hash="sha256:" + "41ab" * 16)
    assert _assert_roundtrip(asset)["path"] == "upload-flow.png"


def test_deprecation_roundtrip() -> None:
    deprecation = Deprecation(
        at=datetime(2026, 9, 10, 14, 2, 11, tzinfo=UTC),
        by=None,
        reason="superseded by RE-FEAT-2K7QMB",
    )
    dumped = _assert_roundtrip(deprecation)
    assert dumped["at"] == "2026-09-10T14:02:11Z"
    assert dumped["by"] is None


def test_decision_roundtrip() -> None:
    decision = Decision(
        status="accepted",
        at=datetime(2026, 9, 12, 15, 30, 0, tzinfo=UTC),
        by=Identity(name="Max Mustermann", email="max@example.org"),
        at_version=2,
    )
    assert _assert_roundtrip(decision)["status"] == "accepted"


def test_decision_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        Decision(
            status="done",  # type: ignore[arg-type]
            at=datetime(2026, 9, 12, 15, 30, 0, tzinfo=UTC),
            by=None,
            at_version=2,
        )


def test_scope_entry_roundtrip() -> None:
    entry = ScopeEntry(id="RE-STORY-7F3K2Q", intent="modify", base_version=3)
    assert _assert_roundtrip(entry) == {
        "id": "RE-STORY-7F3K2Q",
        "intent": "modify",
        "base_version": 3,
    }


def test_scope_entry_rejects_unknown_intent() -> None:
    with pytest.raises(ValidationError):
        ScopeEntry(id="RE-STORY-7F3K2Q", intent="rewrite", base_version=3)  # type: ignore[arg-type]


def test_scope_entry_rejects_zero_base_version() -> None:
    with pytest.raises(ValidationError):
        ScopeEntry(id="RE-STORY-7F3K2Q", intent="modify", base_version=0)


def test_template_ref_roundtrip() -> None:
    ref = TemplateRef(name="term", version=1)
    assert _assert_roundtrip(ref) == {"name": "term", "version": 1}


def test_template_ref_rejects_zero_version() -> None:
    with pytest.raises(ValidationError):
        TemplateRef(name="term", version=0)


def test_template_descriptor_roundtrip() -> None:
    descriptor = TemplateDescriptor.model_validate(_descriptor_payload())
    dumped = _assert_roundtrip(descriptor)
    assert dumped["name"] == "user-story"
    assert [section["heading"] for section in dumped["sections"]] == [
        "Story",
        "Acceptance criteria",
        "Rationale",
        "Notes",
    ]
    assert dumped["sections"][2]["renamed_from"] == ["Motivation"]


def test_template_descriptor_renamed_from_defaults_empty() -> None:
    descriptor = TemplateDescriptor.model_validate(_descriptor_payload())
    assert descriptor.sections[0] == TemplateSection(
        heading="Story",
        required=True,
        placeholder="As a <role>, I want <capability>, so that <benefit>.",
    )
    assert descriptor.sections[3].renamed_from == []


def test_term_roundtrip() -> None:
    term = Term.model_validate(_term_payload())
    dumped = _assert_roundtrip(term)
    assert dumped["slug"] == "knowledge-base"
    assert dumped["aliases"] == ["KB"]


def test_term_requires_template_per_b3() -> None:
    payload = _term_payload()
    del payload["template"]
    with pytest.raises(ValidationError):
        Term.model_validate(payload)


def test_cr_example_payload_parses() -> None:
    cr = ChangeRequest.model_validate(_cr_payload())
    assert cr.id == "RE-CHG-3M9XA1"
    assert cr.status == "accepted"
    assert cr.decisions[-1].at_version == 2


def test_cr_json_roundtrip() -> None:
    cr = ChangeRequest.model_validate(_cr_payload())
    dumped = _assert_roundtrip(cr)
    assert set(dumped) == set(CR_KEYS)
    assert dumped["schema"] == 1


@pytest.mark.parametrize("field", CR_KEYS)
def test_cr_all_fields_mandatory(field: str) -> None:
    payload = _cr_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        ChangeRequest.model_validate(payload)


def test_cr_scope_sorted_by_id_and_introduces_sorted() -> None:
    cr = ChangeRequest.model_validate(
        _cr_payload(
            scope=[
                {"id": "RE-FEAT-9PZ0AH", "intent": "modify", "base_version": 1},
                {"id": "RE-STORY-7F3K2Q", "intent": "supersede", "base_version": 3},
            ],
            introduces=["RE-FEAT-ZZZZZ1", "RE-FEAT-AAAAA1"],
        )
    )
    assert [entry.id for entry in cr.scope] == ["RE-FEAT-9PZ0AH", "RE-STORY-7F3K2Q"]
    assert cr.introduces == ["RE-FEAT-AAAAA1", "RE-FEAT-ZZZZZ1"]


def test_cr_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ChangeRequest.model_validate(_cr_payload(status="done"))


def test_finding_report_shape_id_subject() -> None:
    finding = Finding(
        code="E-CYCLE",
        severity="E",
        subject="RE-STORY-7F3K2Q",
        message="cycle via refines",
        fix="gregraph unlink RE-STORY-7F3K2Q RE-FEAT-2K7QMB",
    )
    assert finding.model_dump(mode="json") == {
        "code": "E-CYCLE",
        "severity": "E",
        "id": "RE-STORY-7F3K2Q",
        "message": "cycle via refines",
        "fix": "gregraph unlink RE-STORY-7F3K2Q RE-FEAT-2K7QMB",
    }


def test_finding_report_shape_path_subject_omits_fix() -> None:
    finding = Finding(
        code="E-SIDECAR-MISSING",
        severity="E",
        subject=Path("documents/RE-STORY-7F3K2Q.md"),
        message="missing sidecar",
    )
    assert finding.model_dump(mode="json") == {
        "code": "E-SIDECAR-MISSING",
        "severity": "E",
        "path": "documents/RE-STORY-7F3K2Q.md",
        "message": "missing sidecar",
    }


def test_finding_roundtrip_id_subject() -> None:
    finding = Finding(
        code="W-ORPHAN",
        severity="W",
        subject="RE-STORY-7F3K2Q",
        message="no edges",
        fix=None,
    )
    assert _assert_roundtrip(finding) == finding.model_dump(mode="json")


def test_finding_roundtrip_path_subject() -> None:
    finding = Finding(
        code="W-ASSET-ORPHAN",
        severity="W",
        subject=Path("assets/RE-STORY-7F3K2Q/orphan.png"),
        message="unreferenced asset",
    )
    restored = Finding.model_validate(finding.model_dump(mode="json"))
    assert restored == finding
    assert restored.subject == Path("assets/RE-STORY-7F3K2Q/orphan.png")


def test_finding_from_report_shape() -> None:
    by_id = Finding.model_validate(
        {"code": "W-ORPHAN", "severity": "W", "id": "RE-2", "message": "x"}
    )
    assert by_id.subject == "RE-2"
    by_path = Finding.model_validate(
        {"code": "W-ORPHAN", "severity": "W", "path": "docs/a.md", "message": "x"}
    )
    assert by_path.subject == Path("docs/a.md")


def test_finding_rejects_both_id_and_path() -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(
            {
                "code": "E-CYCLE",
                "severity": "E",
                "id": "RE-2",
                "path": "docs/a.md",
                "message": "x",
            }
        )


def test_finding_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        Finding(code="E-CYCLE", severity="error", subject="RE-2", message="x")  # type: ignore[arg-type]


def test_finding_without_details_omits_details_key() -> None:
    finding = Finding(code="E-CYCLE", severity="E", subject="RE-2", message="cycle")
    assert "details" not in finding.model_dump(mode="json")


def test_finding_details_serialised_when_present() -> None:
    finding = Finding(
        code="E-CYCLE",
        severity="E",
        subject="RE-A",
        message="adding RE-B refines RE-A creates a cycle",
        details={"cycle": ["RE-A", "RE-B"]},
    )
    assert finding.model_dump(mode="json") == {
        "code": "E-CYCLE",
        "severity": "E",
        "id": "RE-A",
        "message": "adding RE-B refines RE-A creates a cycle",
        "details": {"cycle": ["RE-A", "RE-B"]},
    }


def test_finding_details_roundtrips() -> None:
    finding = Finding(
        code="E-CYCLE",
        severity="E",
        subject="RE-A",
        message="cycle",
        details={"cycle": ["RE-A", "RE-B"]},
    )
    dumped = _assert_roundtrip(finding)
    assert dumped["details"] == {"cycle": ["RE-A", "RE-B"]}
    assert Finding.model_validate(dumped) == finding


def test_finding_details_preserved_from_report_shape() -> None:
    restored = Finding.model_validate(
        {
            "code": "E-CYCLE",
            "severity": "E",
            "id": "RE-A",
            "message": "cycle",
            "details": {"cycle": ["RE-A", "RE-B"]},
        }
    )
    assert restored.subject == "RE-A"
    assert restored.details == {"cycle": ["RE-A", "RE-B"]}
    assert restored.model_dump(mode="json") == {
        "code": "E-CYCLE",
        "severity": "E",
        "id": "RE-A",
        "message": "cycle",
        "details": {"cycle": ["RE-A", "RE-B"]},
    }
