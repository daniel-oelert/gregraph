"""Pydantic models: Document, Link, ChangeRequest, ScopeEntry, Decision, Term.

Also TemplateDescriptor, Identity, Finding (spec §16.1; fields per §5.4, §5.5,
§9.2, §10.2, appendix B.3; Finding shape per §14). Paths are repository-relative
``pathlib.Path`` (spec §16.2). ``OperationRefused(finding)`` (spec §16.2) lives
here next to ``Finding`` (docs/decisions.md ``D-OPREFUSED-HOME``).

``Document`` enforces the §5.4 minimal mandatory set (``tags``, ``extra``,
``created_by``, ``origin_cr`` default to empty/null but are always serialised).
``ChangeRequest`` requires every field of §9.2. ``Term`` follows appendix B.3.
Lists that canonical JSON sorts (§5.4: ``links`` by ``(type, target)``; §9.2:
``scope`` by ``id``, ``introduces``) are kept sorted by the models themselves.
``Finding.model_dump`` emits the §14 report shape (``id``/``path`` key chosen by
subject type; ``fix`` and ``details`` omitted when absent). Pure data only —
no I/O, no printing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

LinkType = Literal[
    "refines",
    "derives-from",
    "depends-on",
    "satisfies",
    "verifies",
    "constrains",
    "supersedes",
    "conflicts-with",
    "relates-to",
]
CrStatus = Literal["open", "accepted", "rejected", "implemented"]
ScopeIntent = Literal["modify", "supersede", "deprecate"]
Severity = Literal["E", "W"]


class Identity(BaseModel):
    """Git author identity, name/email (spec §12.2, appendix B.3)."""

    name: str
    email: str


class Link(BaseModel):
    """Outbound graph edge stored on the source node (spec §6.1, appendix B.3)."""

    type: LinkType
    target: str
    target_version: int = Field(ge=1)


class AssetRef(BaseModel):
    """Referenced asset file, path relative to ``assets/<ID>/`` (spec §5.7, B.3)."""

    path: str
    hash: str


class Deprecation(BaseModel):
    """Deprecation marker on a document or term (spec §5.4, appendix B.3)."""

    at: datetime
    by: Identity | None
    reason: str


class Decision(BaseModel):
    """Appended CR status transition record (spec §9.3, appendix B.3)."""

    status: CrStatus
    at: datetime
    by: Identity | None
    at_version: int = Field(ge=1)


class ScopeEntry(BaseModel):
    """CR scope entry: change to one existing document (spec §9.4, B.3)."""

    id: str
    intent: ScopeIntent
    base_version: int = Field(ge=1)


class TemplateRef(BaseModel):
    """Pinned template name and version (spec §5.5, appendix B.3)."""

    name: str
    version: int = Field(ge=1)


class TemplateSection(BaseModel):
    """One template section descriptor (spec §5.5)."""

    heading: str
    required: bool
    placeholder: str
    renamed_from: list[str] = Field(default_factory=list)


class TemplateDescriptor(BaseModel):
    """``template.json`` sidecar of a template version (spec §5.5)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: int = Field(alias="schema")
    name: str
    version: int = Field(ge=1)
    description: str
    deprecated: bool
    breaking: bool
    sections: list[TemplateSection]


class Document(BaseModel):
    """Document sidecar schema (spec §5.4, appendix B.3)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: int = Field(alias="schema")
    uuid: UUID
    id: str
    type: str
    title: str
    created: datetime
    created_by: Identity | None = None
    template: TemplateRef
    version: int = Field(ge=1)
    body_hash: str
    assets: list[AssetRef]
    links: list[Link]
    deprecated: Deprecation | None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)
    origin_cr: str | None = None

    @model_validator(mode="after")
    def _sort_links(self) -> Self:
        self.links = sorted(self.links, key=lambda link: (link.type, link.target))
        return self


class Term(BaseModel):
    """Glossary term sidecar schema (spec §10.2, appendix B.3)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: int = Field(alias="schema")
    term: str
    slug: str
    aliases: list[str]
    created: datetime
    created_by: Identity | None
    template: TemplateRef
    version: int = Field(ge=1)
    body_hash: str
    deprecated: Deprecation | None


class ChangeRequest(BaseModel):
    """Change-request sidecar schema (spec §9.2, appendix B.3)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: int = Field(alias="schema")
    uuid: UUID
    id: str
    title: str
    created: datetime
    created_by: Identity | None
    template: TemplateRef
    version: int = Field(ge=1)
    body_hash: str
    scope_hash: str
    scope: list[ScopeEntry]
    introduces: list[str]
    status: CrStatus
    decisions: list[Decision]
    branch: str | None
    external_ref: str | None
    tags: list[str]
    extra: dict[str, str]

    @model_validator(mode="after")
    def _sort_content(self) -> Self:
        self.scope = sorted(self.scope, key=lambda entry: entry.id)
        self.introduces = sorted(self.introduces)
        return self


class Finding(BaseModel):
    """Validation finding; serialises to the §14 ``validate --json`` shape.

    ``subject`` is a document/CR ID (``str``) or a repository-relative path
    (``pathlib.Path``); the JSON key is ``id`` or ``path`` accordingly,
    ``fix`` is omitted when there is no suggested command, and ``details``
    (optional machine-readable context, AGENT_READINESS §2.2) is omitted
    when absent.
    """

    code: str
    severity: Severity
    subject: str | Path
    message: str
    fix: str | None = None
    details: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_report_shape(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        mapping = dict(data)
        if "subject" in mapping:
            return mapping
        has_id = "id" in mapping
        has_path = "path" in mapping
        if has_id and has_path:
            raise ValueError("finding subject takes exactly one of 'id' or 'path'")
        if has_id:
            mapping["subject"] = mapping.pop("id")
        elif has_path:
            mapping["subject"] = Path(str(mapping.pop("path")))
        return mapping

    @model_serializer(mode="plain")
    def _to_report_shape(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
        }
        if isinstance(self.subject, Path):
            item["path"] = str(self.subject)
        else:
            item["id"] = self.subject
        item["message"] = self.message
        if self.fix is not None:
            item["fix"] = self.fix
        if self.details is not None:
            item["details"] = self.details
        return item


class OperationRefused(Exception):
    """Raised when an operation refuses to proceed (spec §16.2).

    Carries the refusal :class:`Finding` (e.g. ``E-CYCLE``, ``E-TARGET-SUPERSEDED``)
    that the CLI maps to exit code 4 and prints. Exceptions are reserved for
    refusals and internal errors — everything else is a ``Finding`` in a result
    (spec §16.2). Home: next to ``Finding``, docs/decisions.md ``D-OPREFUSED-HOME``.
    """

    def __init__(self, finding: Finding) -> None:
        self.finding = finding
        super().__init__(f"{finding.code}: {finding.message}")
