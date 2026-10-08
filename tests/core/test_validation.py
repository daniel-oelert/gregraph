"""Tests for ``gregraph.core.validation`` (spec §14, §4.3–4.4, §5.2–5.5).

Test-first (appendix C): at least one test per S10 code of the §14 catalogue,
plus tests for the severity aggregation helper (``--strict`` semantics), the
``validate --json`` emission shape, the code registry, and the cache refresh
helper backing ``E-TYPE-KIND-CHANGED`` / ``E-TEMPLATE-MUTATED``.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from gregraph.core.config import Config, write_config
from gregraph.core.git import GitAdapter
from gregraph.core.hashing import body_hash
from gregraph.core.ids import decode_body, derive_id, split_id
from gregraph.core.models import (
    Document,
    Finding,
    Identity,
    TemplateDescriptor,
    TemplateRef,
    TemplateSection,
)
from gregraph.core.storage import (
    CacheIndex,
    canonical_json_dumps,
    config_path,
    templates_dir,
    write_body,
    write_cache,
    write_sidecar,
)
from gregraph.core.templates import LoadedTemplate, load_template_dir, sections_hash
from gregraph.core.validation import (
    CODE_SEVERITIES,
    aggregate_severity,
    has_errors,
    refresh_cache,
    report_payload,
    validate_workspace,
)
from gregraph.core.workspace import Workspace

UTC = dt.UTC
CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=UTC)

DEFAULT_SECTIONS: tuple[tuple[str, bool, str], ...] = (
    ("Story", True, "As a role, I want capability, so that benefit."),
    ("Acceptance criteria", True, "Given … When … Then …"),
    ("Notes", False, ""),
)

DEFAULT_BODY = (
    "# Upload documents\n"
    "\n"
    "## Story\n"
    "\n"
    "As a user, I want uploads.\n"
    "\n"
    "## Acceptance criteria\n"
    "\n"
    "Given a file, when uploaded, then stored.\n"
    "\n"
    "## Notes\n"
    "\n"
    "Some notes.\n"
)

S10_CODES: dict[str, str] = {
    "E-SIDECAR-MISSING": "E",
    "E-BODY-MISSING": "E",
    "E-SIDECAR-INVALID": "E",
    "E-ID-FILENAME": "E",
    "E-ID-DERIVATION": "E",
    "E-ID-DUPLICATE": "E",
    "E-UUID-DUPLICATE": "E",
    "E-TYPE-UNKNOWN": "E",
    "E-TYPE-KIND-CHANGED": "E",
    "E-TITLE-MISSING": "E",
    "E-FRONTMATTER-FORBIDDEN": "E",
    "E-TEMPLATE-UNKNOWN": "E",
    "E-TEMPLATE-MUTATED": "E",
    "E-SECTION-REQUIRED-MISSING": "E",
    "E-SECTION-REQUIRED-EMPTY": "E",
    "W-SECTION-UNKNOWN": "W",
    "W-SECTION-ORDER": "W",
    "W-TEMPLATE-DEPRECATED": "W",
    "W-LINE-ENDINGS": "W",
    "W-SIDECAR-NONCANONICAL": "W",
    "W-NO-GIT-IDENTITY": "W",
    "W-PREFIX-MISMATCH": "W",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def uuid_from_body(body: str) -> UUID:
    """Deterministic UUID whose §4.1 ID body encodes ``body``'s value."""
    return UUID(int=decode_body(body) << 98)


def make_document(
    doc_id: str = "RE-AAAAAA",
    *,
    doc_type: str = "user-story",
    title: str = "Upload documents",
    template: tuple[str, int] = ("user-story", 1),
    uuid: UUID | None = None,
    links: Sequence[tuple[str, str]] = (),
) -> Document:
    if uuid is None:
        parts = split_id(doc_id)
        uuid = uuid_from_body(parts[1] if parts is not None else "AAAAAA")
    return Document(
        schema=1,
        uuid=uuid,
        id=doc_id,
        type=doc_type,
        title=title,
        created=CREATED,
        created_by=None,
        template=TemplateRef(name=template[0], version=template[1]),
        version=1,
        body_hash=body_hash(DEFAULT_BODY),
        assets=[],
        links=[
            {"type": link_type, "target": target, "target_version": 1}
            for link_type, target in links
        ],
        deprecated=None,
        tags=[],
        extra={},
    )


def write_doc(
    root: Path,
    document: Document,
    *,
    folder: str = "user-stories",
    stem: str | None = None,
    body: str | None = None,
    raw_body: bytes | None = None,
) -> None:
    directory = root / "documents" / folder
    directory.mkdir(parents=True, exist_ok=True)
    stem = stem or document.id
    if raw_body is not None:
        (directory / f"{stem}.md").write_bytes(raw_body)
    else:
        write_body(directory / f"{stem}.md", DEFAULT_BODY if body is None else body)
    write_sidecar(directory / f"{stem}.json", document)


def write_body_only(root: Path, body: str, stem: str = "RE-AAAAAA") -> Path:
    directory = root / "documents" / "user-stories"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.md"
    write_body(path, body)
    return path


def write_sidecar_only(root: Path, document: Document) -> Path:
    directory = root / "documents" / "user-stories"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document.id}.json"
    write_sidecar(path, document)
    return path


def write_template(
    root: Path,
    name: str = "user-story",
    version: int = 1,
    *,
    sections: Sequence[tuple[str, bool, str]] | None = None,
    deprecated: bool = False,
) -> None:
    directory = root / ".gregraph" / "templates" / name / f"v{version}"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = {
        "schema": 1,
        "name": name,
        "version": version,
        "description": f"{name} v{version}",
        "deprecated": deprecated,
        "breaking": False,
        "sections": [
            {
                "heading": heading,
                "required": required,
                "placeholder": placeholder,
                "renamed_from": [],
            }
            for heading, required, placeholder in (
                DEFAULT_SECTIONS if sections is None else sections
            )
        ],
    }
    (directory / "template.json").write_text(
        json.dumps(descriptor, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / "template.md").write_text("# {{ title }}\n", encoding="utf-8")


def setup_repo(root: Path) -> None:
    write_config(config_path(root), Config())
    write_template(root)


def findings_with(findings: list[Finding], code: str) -> list[Finding]:
    return [finding for finding in findings if finding.code == code]


def codes_of(findings: list[Finding]) -> set[str]:
    return {finding.code for finding in findings}


class _IdentitylessRepo(GitAdapter):
    """A repository without ``user.name``/``user.email`` configured."""

    def is_repo(self) -> bool:
        return True

    def identity(self) -> Identity | None:
        return None


class _IdentifiedRepo(GitAdapter):
    """A repository with a configured Git identity."""

    def is_repo(self) -> bool:
        return True

    def identity(self) -> Identity | None:
        return Identity(name="Test Author", email="test.author@example.org")


# --------------------------------------------------------------------------
# composed load findings (workspace.load_index)
# --------------------------------------------------------------------------


class TestComposedLoadFindings:
    def test_sidecar_missing(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_body_only(tmp_repo, DEFAULT_BODY)
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-SIDECAR-MISSING")
        assert item.severity == "E"
        assert item.subject == Path("documents/user-stories/RE-AAAAAA.md")

    def test_body_missing(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        sidecar = write_sidecar_only(tmp_repo, make_document())
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-BODY-MISSING")
        assert item.severity == "E"
        assert item.subject == sidecar.relative_to(tmp_repo)

    def test_sidecar_invalid(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_body_only(tmp_repo, DEFAULT_BODY)
        directory = tmp_repo / "documents" / "user-stories"
        (directory / "RE-AAAAAA.json").write_text("{not json", encoding="utf-8")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-SIDECAR-INVALID")
        assert item.severity == "E"

    def test_id_duplicate(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(), folder="user-stories")
        write_doc(tmp_repo, make_document(), folder="epics")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-ID-DUPLICATE")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert item.fix is not None
        assert "repair regenerate-id" in item.fix


# --------------------------------------------------------------------------
# identifiers (spec §4.3–4.4)
# --------------------------------------------------------------------------


class TestIdentifierChecks:
    def test_id_filename(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document("RE-AAAAAA"), stem="RE-BBBBBB")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-ID-FILENAME")
        assert item.severity == "E"
        assert item.subject == Path("documents/user-stories/RE-BBBBBB.json")
        assert "RE-AAAAAA" in item.message
        assert "RE-BBBBBB" in item.message

    def test_id_derivation(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document("RE-AAAAAA", uuid=uuid_from_body("BBBBBB")))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-ID-DERIVATION")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert derive_id(uuid_from_body("BBBBBB")) in item.message
        assert item.fix is not None
        assert "repair regenerate-id" in item.fix

    def test_uuid_duplicate(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        shared = uuid_from_body("AAAAAA")
        write_doc(tmp_repo, make_document("RE-AAAAAA", uuid=shared))
        write_doc(tmp_repo, make_document("RE-BBBBBB", uuid=shared))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-UUID-DUPLICATE")
        assert item.severity == "E"
        assert item.subject == "RE-BBBBBB"
        assert "RE-AAAAAA" in item.message

    def test_prefix_mismatch(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document("XX-AAAAAA"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-PREFIX-MISMATCH")
        assert item.severity == "W"
        assert item.subject == "XX-AAAAAA"
        # §4.3 is literal: the derivation invariant uses the *configured*
        # prefix, so a prefix mismatch also fails derivation (see the
        # SPEC-QUESTION in docs/backlog.md).
        [derivation] = findings_with(findings, "E-ID-DERIVATION")
        assert derivation.subject == "XX-AAAAAA"


# --------------------------------------------------------------------------
# types (spec §5.3, §16.5)
# --------------------------------------------------------------------------


class TestTypeChecks:
    def test_type_unknown(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(doc_type="nonexistent-type"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TYPE-UNKNOWN")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "nonexistent-type" in item.message

    def test_type_kind_changed(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_cache(
            tmp_repo,
            cache_model(types_seen={"user-story": "goal"}),
        )
        write_doc(tmp_repo, make_document(doc_type="user-story"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TYPE-KIND-CHANGED")
        assert item.severity == "E"
        assert item.subject == Path(".gregraph/config.toml")
        assert "user-story" in item.message
        assert "goal" in item.message

    def test_type_kind_change_without_documents_is_free(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_cache(
            tmp_repo,
            cache_model(types_seen={"user-story": "goal"}),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TYPE-KIND-CHANGED") == []


# --------------------------------------------------------------------------
# body conventions (spec §5.2)
# --------------------------------------------------------------------------


class TestBodyChecks:
    def test_title_missing(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(), body="## Story\n\nNo heading above.\n")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TITLE-MISSING")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert item.fix is not None
        assert item.fix.startswith("gregraph edit")

    def test_frontmatter_forbidden(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(),
            body="---\ntitle: Upload documents\n---\n\n# Upload documents\n",
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-FRONTMATTER-FORBIDDEN")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert item.fix is not None
        assert item.fix.startswith("gregraph edit")


# --------------------------------------------------------------------------
# templates (spec §5.5, §16.5)
# --------------------------------------------------------------------------


class TestTemplateChecks:
    def test_template_unknown_name(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(template=("missing-template", 1)))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TEMPLATE-UNKNOWN")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "missing-template" in item.message

    def test_template_unknown_version(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(template=("user-story", 9)))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TEMPLATE-UNKNOWN")
        assert item.severity == "E"
        assert "user-story" in item.message

    def test_template_mutated(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_cache(
            tmp_repo,
            cache_model(templates_seen={"user-story/v1": "sha256:" + "0" * 64}),
        )
        write_doc(tmp_repo, make_document())
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TEMPLATE-MUTATED")
        assert item.severity == "E"
        assert item.subject == Path(".gregraph/templates/user-story/v1/template.json")
        assert item.fix is not None
        assert "template bump" in item.fix

    def test_template_unchanged_is_fine(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        templates = load_template_dir(templates_dir(tmp_repo))
        digest = sections_hash(templates["user-story"][0].descriptor)
        write_cache(tmp_repo, cache_model(templates_seen={"user-story/v1": digest}))
        write_doc(tmp_repo, make_document())
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TEMPLATE-MUTATED") == []

    def test_template_deprecated(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_template(tmp_repo, deprecated=True)
        write_doc(tmp_repo, make_document())
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-TEMPLATE-DEPRECATED")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert item.fix is not None
        assert item.fix.startswith("gregraph migrate")


# --------------------------------------------------------------------------
# sections (spec §5.5)
# --------------------------------------------------------------------------


class TestSectionChecks:
    def test_section_required_missing(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(),
            body=(
                "# Upload documents\n\n"
                "## Acceptance criteria\n\nGiven a file, then stored.\n"
            ),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-SECTION-REQUIRED-MISSING")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "Story" in item.message

    def test_section_required_empty(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(),
            body=(
                "# Upload documents\n\n"
                "## Story\n\n"
                "## Acceptance criteria\n\nGiven a file, then stored.\n"
            ),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-SECTION-REQUIRED-EMPTY")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "Story" in item.message

    def test_section_required_placeholder_only(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(),
            body=(
                "# Upload documents\n\n"
                "## Story\n\n"
                "*As a role, I want capability, so that benefit.*\n\n"
                "## Acceptance criteria\n\nGiven a file, then stored.\n"
            ),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-SECTION-REQUIRED-EMPTY")
        assert "Story" in item.message

    def test_section_unknown(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(),
            body=(
                "# Upload documents\n\n"
                "## Story\n\nAs a user, I want uploads.\n\n"
                "## Acceptance criteria\n\nGiven a file, then stored.\n\n"
                "## Extra thinking\n\nOrganic extension.\n"
            ),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-SECTION-UNKNOWN")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert "Extra thinking" in item.message

    def test_section_order(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(),
            body=(
                "# Upload documents\n\n"
                "## Acceptance criteria\n\nGiven a file, then stored.\n\n"
                "## Story\n\nAs a user, I want uploads.\n"
            ),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-SECTION-ORDER")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"


# --------------------------------------------------------------------------
# serialisation hygiene (spec §5.2, §5.4)
# --------------------------------------------------------------------------


class TestSerialisationChecks:
    def test_line_endings(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        raw = DEFAULT_BODY.replace("\n", "\r\n").encode("utf-8")
        write_doc(tmp_repo, make_document(), raw_body=raw)
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-LINE-ENDINGS")
        assert item.severity == "W"
        assert item.subject == Path("documents/user-stories/RE-AAAAAA.md")
        assert item.fix is not None
        assert item.fix.startswith("gregraph sync")

    def test_sidecar_noncanonical(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        sidecar = tmp_repo / "documents" / "user-stories" / "RE-AAAAAA.json"
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        sidecar.write_text(
            json.dumps(data, indent=4) + "\n", encoding="utf-8", newline="\n"
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-SIDECAR-NONCANONICAL")
        assert item.severity == "W"
        assert item.subject == Path("documents/user-stories/RE-AAAAAA.json")
        assert item.fix is not None
        assert item.fix.startswith("gregraph sync")

    def test_canonical_sidecar_is_fine(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-SIDECAR-NONCANONICAL") == []
        sidecar = tmp_repo / "documents" / "user-stories" / "RE-AAAAAA.json"
        document = make_document()
        assert sidecar.read_bytes() == canonical_json_dumps(document).encode("utf-8")


# --------------------------------------------------------------------------
# git identity (spec §12.2)
# --------------------------------------------------------------------------


class TestGitIdentityCheck:
    def test_no_git_identity(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        workspace = Workspace.open(tmp_repo, git=_IdentitylessRepo(tmp_repo))
        findings = validate_workspace(workspace)
        [item] = findings_with(findings, "W-NO-GIT-IDENTITY")
        assert item.severity == "W"
        assert item.subject == Path(".gregraph/config.toml")

    def test_configured_identity_is_silent(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        workspace = Workspace.open(tmp_repo, git=_IdentifiedRepo(tmp_repo))
        findings = validate_workspace(workspace)
        assert findings_with(findings, "W-NO-GIT-IDENTITY") == []

    def test_degraded_mode_is_silent(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-NO-GIT-IDENTITY") == []


# --------------------------------------------------------------------------
# whole-report behaviour and helpers
# --------------------------------------------------------------------------


def cache_model(
    *,
    types_seen: dict[str, str] | None = None,
    templates_seen: dict[str, str] | None = None,
) -> CacheIndex:
    return CacheIndex(
        types_seen={} if types_seen is None else types_seen,
        templates_seen={} if templates_seen is None else templates_seen,
    )


class TestValidateWorkspace:
    def test_clean_repository_has_no_findings(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        # S11: an unlinked document is W-ORPHAN (spec §6.3), so a clean
        # repository links its documents.
        write_doc(tmp_repo, make_document(links=[("refines", "RE-BBBBBB")]))
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        assert validate_workspace(Workspace.open(tmp_repo)) == []

    def test_report_is_sorted_and_codes_registered(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(doc_type="nonexistent-type"))
        write_doc(tmp_repo, make_document("RE-BBBBBB"), body="No heading.\n")
        findings = validate_workspace(Workspace.open(tmp_repo))
        keys = [(f.code, str(f.subject), f.message) for f in findings]
        assert keys == sorted(keys)
        assert "E-TYPE-UNKNOWN" in codes_of(findings)
        assert "E-TITLE-MISSING" in codes_of(findings)

    def test_s10_codes_are_registered(self) -> None:
        for code, severity in S10_CODES.items():
            assert CODE_SEVERITIES.get(code) == severity


class TestSeverityAggregation:
    @staticmethod
    def _finding(code: str, severity: str) -> Finding:
        return Finding(code=code, severity=severity, subject="RE-AAAAAA", message="m")

    def test_empty_report(self) -> None:
        assert aggregate_severity([]) is None
        assert has_errors([]) is False

    def test_warnings_only(self) -> None:
        findings = [self._finding("W-A", "W")]
        assert aggregate_severity(findings) == "W"
        assert has_errors(findings) is False
        assert aggregate_severity(findings, strict=True) == "E"
        assert has_errors(findings, strict=True) is True

    def test_errors_dominate(self) -> None:
        findings = [self._finding("W-A", "W"), self._finding("E-A", "E")]
        assert aggregate_severity(findings) == "E"
        assert has_errors(findings) is True
        assert aggregate_severity(findings, strict=True) == "E"


class TestReportPayload:
    def test_json_emission_shape(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB")]),
            body=(
                "## Story\n\nAs a user, I want uploads.\n\n"
                "## Acceptance criteria\n\nGiven a file, then stored.\n"
            ),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB", doc_type="nope"))
        payload = report_payload(validate_workspace(Workspace.open(tmp_repo)))
        assert {item["code"] for item in payload} == {
            "E-TITLE-MISSING",
            "E-TYPE-UNKNOWN",
        }
        for item in payload:
            assert set(item) <= {"code", "severity", "id", "path", "message", "fix"}
            assert {"code", "severity", "message"} <= set(item)
            assert ("id" in item) != ("path" in item)
        by_code = {item["code"]: item for item in payload}
        assert by_code["E-TITLE-MISSING"]["id"] == "RE-AAAAAA"
        assert by_code["E-TITLE-MISSING"]["fix"].startswith("gregraph edit")
        assert "fix" not in by_code["E-TYPE-UNKNOWN"]


class TestRefreshCache:
    @staticmethod
    def _template(name: str, version: int) -> LoadedTemplate:
        descriptor = TemplateDescriptor(
            schema=1,
            name=name,
            version=version,
            description="d",
            deprecated=False,
            breaking=False,
            sections=[TemplateSection(heading="Story", required=True, placeholder="")],
        )
        return LoadedTemplate(descriptor=descriptor, body="# {{ title }}\n")

    def test_records_kinds_and_sections(self, tmp_repo: Path) -> None:
        template = self._template("user-story", 1)
        cache = refresh_cache(
            CacheIndex(),
            config=Config(),
            documents=[make_document()],
            templates={"user-story": [template]},
        )
        assert cache.types_seen["user-story"] == "requirement"
        assert cache.templates_seen == {
            "user-story/v1": sections_hash(template.descriptor)
        }

    def test_kind_disagreement_persists_while_documents_exist(
        self, tmp_repo: Path
    ) -> None:
        cache = refresh_cache(
            CacheIndex(types_seen={"user-story": "goal"}),
            config=Config(),
            documents=[make_document()],
            templates={},
        )
        assert cache.types_seen["user-story"] == "goal"
        cache = refresh_cache(
            CacheIndex(types_seen={"user-story": "goal"}),
            config=Config(),
            documents=[],
            templates={},
        )
        assert cache.types_seen["user-story"] == "requirement"

    def test_template_disagreement_persists_while_pinned(self, tmp_repo: Path) -> None:
        template = self._template("user-story", 1)
        old = "sha256:" + "0" * 64
        cache = refresh_cache(
            CacheIndex(templates_seen={"user-story/v1": old}),
            config=Config(),
            documents=[make_document()],
            templates={"user-story": [template]},
        )
        assert cache.templates_seen == {"user-story/v1": old}
        cache = refresh_cache(
            CacheIndex(templates_seen={"user-story/v1": old}),
            config=Config(),
            documents=[],
            templates={"user-story": [template]},
        )
        assert cache.templates_seen == {
            "user-story/v1": sections_hash(template.descriptor)
        }
