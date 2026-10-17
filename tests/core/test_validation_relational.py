"""Tests for the S11 relational, asset and misc validation codes (spec §14).

One test per code of the S11 deliverable: the composed graph codes
(``E-LINK-TARGET-MISSING``, ``E-EDGE-RULE``, ``E-EDGE-EXCLUSIVE``,
``E-CYCLE`` — composed from ``Graph.validation_findings()``; the cycle
report must include the path), the link-type and link-freshness codes
(§7.4), ``W-ORPHAN`` (§6.3), the mention codes (§5.2, CR IDs exempt from
``W-MENTION-UNLINKED``), the asset codes (§5.7), ``W-CONFLICT-OPEN``
(§11.1) and ``E-TARGET-SUPERSEDED``/``E-TARGET-DEPRECATED`` (§7.6/§8, as
found in files edited outside the tool).  Behaviour tests cover the
exemptions the spec text implies (supersession chains, symmetric history
edges, self-mentions).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import pytest

from gregraph.core.config import AssetsSection, Config, write_config
from gregraph.core.git import GitAdapter
from gregraph.core.hashing import body_hash
from gregraph.core.ids import decode_body, split_id
from gregraph.core.models import (
    ChangeRequest,
    Deprecation,
    Document,
    Finding,
    Link,
    LinkType,
    TemplateRef,
)
from gregraph.core.storage import config_path, write_body, write_sidecar
from gregraph.core.validation import CODE_SEVERITIES, validate_workspace
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

S11_CODES: dict[str, str] = {
    "E-LINK-TARGET-MISSING": "E",
    "E-LINK-TYPE-UNKNOWN": "E",
    "E-EDGE-RULE": "E",
    "E-EDGE-EXCLUSIVE": "E",
    "E-CYCLE": "E",
    "E-LINK-VERSION-AHEAD": "E",
    "W-LINK-OUTDATED": "W",
    "W-LINK-STALE": "W",
    "W-LINK-PENDING": "W",
    "W-ORPHAN": "W",
    "W-MENTION-UNLINKED": "W",
    "E-MENTION-UNKNOWN": "E",
    "E-ASSET-MISSING": "E",
    "E-ASSET-FOREIGN": "E",
    "W-ASSET-ORPHAN": "W",
    "W-ASSET-LARGE": "W",
    "E-ASSET-OWNERLESS": "E",
    "W-CONFLICT-OPEN": "W",
    "E-TARGET-SUPERSEDED": "E",
    "E-TARGET-DEPRECATED": "E",
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
    version: int = 1,
    body: str = DEFAULT_BODY,
    links: Sequence[tuple[LinkType, str, int]] = (),
    deprecated: bool = False,
) -> Document:
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
        template=TemplateRef(name="user-story", version=1),
        version=version,
        body_hash=body_hash(body),
        assets=[],
        links=[
            Link(type=link_type, target=target, target_version=target_version)
            for link_type, target, target_version in links
        ],
        deprecated=(
            Deprecation(at=CREATED, by=None, reason="obsolete") if deprecated else None
        ),
        tags=[],
        extra={},
    )


def write_doc(
    root: Path,
    document: Document,
    *,
    folder: str = "user-stories",
    body: str | None = None,
) -> None:
    directory = root / "documents" / folder
    directory.mkdir(parents=True, exist_ok=True)
    write_body(directory / f"{document.id}.md", DEFAULT_BODY if body is None else body)
    write_sidecar(directory / f"{document.id}.json", document)


def make_change(cr_id: str = "RE-DDDDDD") -> ChangeRequest:
    parts = split_id(cr_id)
    return ChangeRequest(
        schema=1,
        uuid=uuid_from_body(parts[1] if parts is not None else "DDDDDD"),
        id=cr_id,
        title="Change something",
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="change-request", version=1),
        version=1,
        body_hash=body_hash("# Change something\n"),
        scope_hash="sha256:" + "0" * 64,
        scope=[],
        introduces=[],
        status="open",
        decisions=[],
        branch=None,
        external_ref=None,
        tags=[],
        extra={},
    )


def write_change(root: Path, change: ChangeRequest) -> None:
    directory = root / "changes"
    directory.mkdir(parents=True, exist_ok=True)
    write_body(directory / f"{change.id}.md", "# Change something\n")
    write_sidecar(directory / f"{change.id}.json", change)


def write_template(root: Path, name: str = "user-story", version: int = 1) -> None:
    directory = root / ".gregraph" / "templates" / name / f"v{version}"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = {
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
                "renamed_from": [],
            }
            for heading, required, placeholder in DEFAULT_SECTIONS
        ],
    }
    (directory / "template.json").write_text(
        json.dumps(descriptor, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / "template.md").write_text("# {{ title }}\n", encoding="utf-8")


def setup_repo(root: Path, *, config: Config | None = None) -> None:
    write_config(config_path(root), Config() if config is None else config)
    write_template(root)


def findings_with(findings: list[Finding], code: str) -> list[Finding]:
    return [finding for finding in findings if finding.code == code]


def codes_of(findings: list[Finding]) -> set[str]:
    return {finding.code for finding in findings}


def _commit_all(root: Path) -> None:
    """Commit the current tree (test scaffolding may shell out to git; §12.1)."""
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test Author",
            "-c",
            "user.email=test.author@example.org",
            "commit",
            "-m",
            "seed",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


# --------------------------------------------------------------------------
# composed graph findings (spec §6)
# --------------------------------------------------------------------------


class TestComposedGraphFindings:
    def test_link_target_missing(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 1)]),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-LINK-TARGET-MISSING")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "RE-BBBBBB" in item.message

    def test_edge_rule(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(
                doc_type="design",
                links=[("refines", "RE-BBBBBB", 1)],
            ),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-EDGE-RULE")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "refines" in item.message

    def test_edge_exclusive(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(
                links=[
                    ("refines", "RE-BBBBBB", 1),
                    ("derives-from", "RE-BBBBBB", 1),
                ]
            ),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-EDGE-EXCLUSIVE")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"

    def test_cycle_report_includes_path(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("depends-on", "RE-BBBBBB", 1)]),
        )
        write_doc(
            tmp_repo,
            make_document("RE-BBBBBB", links=[("depends-on", "RE-AAAAAA", 1)]),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-CYCLE")
        assert item.severity == "E"
        assert "RE-AAAAAA" in item.message
        assert "RE-BBBBBB" in item.message
        assert "→" in item.message


# --------------------------------------------------------------------------
# edge types (spec §6.1)
# --------------------------------------------------------------------------


class TestLinkTypeChecks:
    def test_link_type_unknown(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        sidecar = tmp_repo / "documents" / "user-stories" / "RE-AAAAAA.json"
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        data["links"] = [{"type": "refine", "target": "RE-BBBBBB", "target_version": 1}]
        sidecar.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-LINK-TYPE-UNKNOWN")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "refine" in item.message
        # the sidecar also fails schema (Link.type is typed) — both fire
        assert findings_with(findings, "E-SIDECAR-INVALID") != []


# --------------------------------------------------------------------------
# link freshness (spec §7.4)
# --------------------------------------------------------------------------


class TestLinkFreshness:
    def test_link_version_ahead(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 3)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-LINK-VERSION-AHEAD")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert item.fix == "gregraph repair versions"
        assert findings_with(findings, "W-LINK-OUTDATED") == []

    def test_link_outdated(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB", version=2))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-LINK-OUTDATED")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert "RE-BBBBBB" in item.message

    def test_link_stale_deprecated_target(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB", deprecated=True))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-LINK-STALE")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert "RE-BBBBBB" in item.message
        # symmetric edges are not "directed edges" (§7.6/§8) — no rule error
        assert findings_with(findings, "E-TARGET-DEPRECATED") == []

    def test_link_stale_superseded_target(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        write_doc(
            tmp_repo,
            make_document("RE-CCCCCC", links=[("supersedes", "RE-BBBBBB", 1)]),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-LINK-STALE")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert "RE-BBBBBB" in item.message

    def test_link_pending(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        if (tmp_repo / ".git").exists():
            # Grace (§3.3) applies only before the first commit: commit the
            # target once so its later edit is a normal unbumped modification.
            _commit_all(tmp_repo)
        modified = "# Upload documents\n\nEdited but not yet bumped.\n"
        write_body(tmp_repo / "documents" / "user-stories" / "RE-BBBBBB.md", modified)
        workspace = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
        findings = validate_workspace(workspace)
        pending = findings_with(findings, "W-LINK-PENDING")
        if (tmp_repo / ".git").exists():
            [item] = pending
            assert item.severity == "W"
            assert item.subject == "RE-AAAAAA"
            assert "RE-BBBBBB" in item.message
        else:
            # §7.4: pending-outdated is a Git-mode state only
            assert pending == []

    def test_link_to_uncommitted_v1_target_is_fresh(self, tmp_repo: Path) -> None:
        """§3.3 rule 4 / AGENT-012: a draft v1 target stays fresh at tv 1."""
        if not (tmp_repo / ".git").exists():
            pytest.skip("the initial-grace state is a Git-mode state (§3.3)")
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        modified = "# Upload documents\n\nEdited but not yet bumped.\n"
        write_body(tmp_repo / "documents" / "user-stories" / "RE-BBBBBB.md", modified)
        workspace = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
        findings = validate_workspace(workspace)
        assert findings_with(findings, "W-LINK-PENDING") == []
        assert findings_with(findings, "E-LINK-VERSION-AHEAD") == []

    def test_link_pending_at_effective_version(self, tmp_repo: Path) -> None:
        """§5.4/D-AGENT-7/AGENT-026: tv == effective on an unbumped target warns."""
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 2)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        if (tmp_repo / ".git").exists():
            # commit once: the target leaves the grace state (§3.3 rule 5)
            _commit_all(tmp_repo)
        modified = "# Upload documents\n\nEdited but not yet bumped.\n"
        write_body(tmp_repo / "documents" / "user-stories" / "RE-BBBBBB.md", modified)
        workspace = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
        findings = validate_workspace(workspace)
        # tv == effective (not merely <= version) is not the ahead error
        assert findings_with(findings, "E-LINK-VERSION-AHEAD") == []
        [item] = findings_with(findings, "W-LINK-PENDING")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert item.fix == "gregraph sync --bump"
        assert "pending version" in item.message

    def test_link_version_ahead_of_effective(self, tmp_repo: Path) -> None:
        """§5.4/D-AGENT-7: tv beyond the effective version is the ahead error."""
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 3)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        if (tmp_repo / ".git").exists():
            _commit_all(tmp_repo)
        modified = "# Upload documents\n\nEdited but not yet bumped.\n"
        write_body(tmp_repo / "documents" / "user-stories" / "RE-BBBBBB.md", modified)
        workspace = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
        findings = validate_workspace(workspace)
        [item] = findings_with(findings, "E-LINK-VERSION-AHEAD")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert item.fix == "gregraph repair versions"
        assert findings_with(findings, "W-LINK-PENDING") == []

    def test_link_version_ahead_unmodified_target(self, tmp_repo: Path) -> None:
        """§5.4: tv = version + 1 on an unmodified target is still ahead."""
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("relates-to", "RE-BBBBBB", 2)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        workspace = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
        findings = validate_workspace(workspace)
        [item] = findings_with(findings, "E-LINK-VERSION-AHEAD")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert item.fix == "gregraph repair versions"
        assert findings_with(findings, "W-LINK-PENDING") == []

    def test_supersedes_chain_is_not_stale(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        write_doc(
            tmp_repo,
            make_document("RE-BBBBBB", links=[("supersedes", "RE-AAAAAA", 1)]),
        )
        write_doc(
            tmp_repo,
            make_document("RE-CCCCCC", links=[("supersedes", "RE-BBBBBB", 1)]),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-LINK-STALE") == []
        assert findings_with(findings, "E-TARGET-SUPERSEDED") == []
        assert findings_with(findings, "E-TARGET-DEPRECATED") == []


# --------------------------------------------------------------------------
# target state (spec §7.6, §8)
# --------------------------------------------------------------------------


class TestTargetStateChecks:
    def test_target_superseded(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        write_doc(
            tmp_repo,
            make_document("RE-BBBBBB", links=[("refines", "RE-AAAAAA", 1)]),
        )
        write_doc(
            tmp_repo,
            make_document("RE-CCCCCC", links=[("supersedes", "RE-AAAAAA", 1)]),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TARGET-SUPERSEDED")
        assert item.severity == "E"
        assert item.subject == "RE-BBBBBB"
        assert "RE-AAAAAA" in item.message
        # the same edge is also stale on the §7.4 freshness axis
        assert findings_with(findings, "W-LINK-STALE") != []

    def test_target_deprecated(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(deprecated=True))
        write_doc(
            tmp_repo,
            make_document("RE-BBBBBB", links=[("refines", "RE-AAAAAA", 1)]),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TARGET-DEPRECATED")
        assert item.severity == "E"
        assert item.subject == "RE-BBBBBB"
        assert "RE-AAAAAA" in item.message

    def test_symmetric_history_edge_is_not_an_error(self, tmp_repo: Path) -> None:
        # §11.2: the conflicts-with edge remains on dead documents as history
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("conflicts-with", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB", deprecated=True))
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TARGET-DEPRECATED") == []
        assert findings_with(findings, "E-TARGET-SUPERSEDED") == []

    def test_supersedes_may_target_superseded(self, tmp_repo: Path) -> None:
        # fork: one target superseded by two documents (§7.6)
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        write_doc(
            tmp_repo,
            make_document("RE-BBBBBB", links=[("supersedes", "RE-AAAAAA", 1)]),
        )
        write_doc(
            tmp_repo,
            make_document("RE-CCCCCC", links=[("supersedes", "RE-AAAAAA", 1)]),
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TARGET-SUPERSEDED") == []


# --------------------------------------------------------------------------
# orphans (spec §6.3)
# --------------------------------------------------------------------------


class TestOrphanChecks:
    def test_orphan(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-ORPHAN")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"

    def test_deprecated_orphan_is_silent(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document(deprecated=True))
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-ORPHAN") == []


# --------------------------------------------------------------------------
# mentions (spec §5.2)
# --------------------------------------------------------------------------


class TestMentionChecks:
    def test_mention_unlinked(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        body = "# Upload documents\n\nSee [[RE-BBBBBB]] for the parent story.\n"
        write_doc(tmp_repo, make_document(body=body), body=body)
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-MENTION-UNLINKED")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert "RE-BBBBBB" in item.message

    def test_mention_with_edge_is_silent(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        body = "# Upload documents\n\nSee [[RE-BBBBBB]] for the parent story.\n"
        write_doc(
            tmp_repo,
            make_document(body=body, links=[("relates-to", "RE-BBBBBB", 1)]),
            body=body,
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-MENTION-UNLINKED") == []

    def test_mention_unknown(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        body = "# Upload documents\n\nSee [[RE-ZZZZZZ]] for the parent story.\n"
        write_doc(tmp_repo, make_document(body=body), body=body)
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-MENTION-UNKNOWN")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "RE-ZZZZZZ" in item.message

    def test_cr_ids_are_exempt(self, tmp_repo: Path) -> None:
        # §5.2: document bodies may mention CR IDs freely
        setup_repo(tmp_repo)
        body = "# Upload documents\n\nSee [[RE-DDDDDD]] for the change request.\n"
        write_doc(tmp_repo, make_document(body=body), body=body)
        write_change(tmp_repo, make_change("RE-DDDDDD"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-MENTION-UNLINKED") == []
        assert findings_with(findings, "E-MENTION-UNKNOWN") == []

    def test_bare_id_and_hyphenated_words_produce_no_mention_findings(
        self, tmp_repo: Path
    ) -> None:
        """AGENT-402/D-AGENT-6: bare IDs and hyphenated prose are not mentions."""
        setup_repo(tmp_repo)
        body = (
            "# Upload documents\n"
            "\n"
            "The multi-target and baseline-branch designs see RE-BBBBBB.\n"
        )
        write_doc(tmp_repo, make_document(body=body), body=body)
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-MENTION-UNLINKED") == []
        assert findings_with(findings, "E-MENTION-UNKNOWN") == []
        # The explicit wikilink form still is a mention.
        explicit = "# Upload documents\n\nSee [[RE-BBBBBB]] for details.\n"
        write_doc(tmp_repo, make_document(body=explicit), body=explicit)
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-MENTION-UNLINKED")
        assert item.subject == "RE-AAAAAA"


# --------------------------------------------------------------------------
# assets (spec §5.7)
# --------------------------------------------------------------------------


class TestAssetChecks:
    def test_asset_missing(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        body = "# Upload documents\n\n![shot](../../assets/RE-AAAAAA/missing.png)\n"
        write_doc(tmp_repo, make_document(body=body), body=body)
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-ASSET-MISSING")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "missing.png" in item.message

    def test_asset_foreign(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        body = "# Upload documents\n\n![shot](../../assets/RE-BBBBBB/file.png)\n"
        write_doc(tmp_repo, make_document(body=body), body=body)
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        folder = tmp_repo / "assets" / "RE-BBBBBB"
        folder.mkdir(parents=True)
        (folder / "file.png").write_bytes(b"png")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-ASSET-FOREIGN")
        assert item.severity == "E"
        assert item.subject == "RE-AAAAAA"
        assert "RE-BBBBBB" in item.message

    def test_asset_orphan(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        folder = tmp_repo / "assets" / "RE-AAAAAA"
        folder.mkdir(parents=True)
        (folder / "extra.png").write_bytes(b"png")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-ASSET-ORPHAN")
        assert item.severity == "W"
        assert item.subject == Path("assets/RE-AAAAAA/extra.png")

    def test_asset_large(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo, config=Config(assets=AssetsSection(max_size_kb=1)))
        write_doc(tmp_repo, make_document())
        folder = tmp_repo / "assets" / "RE-AAAAAA"
        folder.mkdir(parents=True)
        (folder / "big.bin").write_bytes(b"x" * 2048)
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-ASSET-LARGE")
        assert item.severity == "W"
        assert item.subject == Path("assets/RE-AAAAAA/big.bin")

    def test_asset_ownerless(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(tmp_repo, make_document())
        folder = tmp_repo / "assets" / "GHOST"
        folder.mkdir(parents=True)
        (folder / "orphan.png").write_bytes(b"png")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-ASSET-OWNERLESS")
        assert item.severity == "E"
        assert item.subject == Path("assets/GHOST")


# --------------------------------------------------------------------------
# open conflicts (spec §11.1)
# --------------------------------------------------------------------------


class TestOpenConflicts:
    def test_conflict_open(self, tmp_repo: Path) -> None:
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("conflicts-with", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB"))
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "W-CONFLICT-OPEN")
        assert item.severity == "W"
        assert item.subject == "RE-AAAAAA"
        assert "RE-BBBBBB" in item.message

    def test_conflict_with_dead_endpoint_is_closed(self, tmp_repo: Path) -> None:
        # §11.1: both endpoints must be live for the conflict to be open
        setup_repo(tmp_repo)
        write_doc(
            tmp_repo,
            make_document(links=[("conflicts-with", "RE-BBBBBB", 1)]),
        )
        write_doc(tmp_repo, make_document("RE-BBBBBB", deprecated=True))
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "W-CONFLICT-OPEN") == []


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


class TestRegistry:
    def test_s11_codes_are_registered(self) -> None:
        for code, severity in S11_CODES.items():
            assert CODE_SEVERITIES.get(code) == severity
