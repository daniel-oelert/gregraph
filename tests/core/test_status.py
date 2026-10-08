"""Tests for ``gregraph.core.status`` (spec §8, §11.1, §16.1).

Test-first (appendix C): status precedence (``deprecated`` > ``superseded`` >
``draft`` > ``active``), ``draft``/``active`` with real Git fixtures, ``unknown``
in degraded mode and when the baseline branch is missing locally (with a
warning), WIP aggregation (drafts, unbumped modifications, uncommitted files
under the managed directories) and the open-conflict count of §11.1.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from gregraph.core.config import Config, GitSection, write_config
from gregraph.core.git import GitAdapter
from gregraph.core.hashing import body_hash
from gregraph.core.models import Deprecation, Document, Link, TemplateRef, Term
from gregraph.core.status import (
    ItemStatus,
    WipState,
    compute_status,
    derive_status,
    open_conflicts,
)
from gregraph.core.storage import (
    CONFIG_RELPATH,
    config_path,
    document_paths,
    term_paths,
    write_body,
    write_sidecar,
)
from gregraph.core.workspace import Workspace

CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=dt.UTC)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, "LC_ALL": "C"},
        capture_output=True,
        check=True,
        text=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _write_layout(root: Path, config: Config | None = None) -> None:
    write_config(config_path(root), config if config is not None else Config())
    for name in ("documents", "changes", "glossary", "assets"):
        (root / name).mkdir()
    (root / ".gitignore").write_text(".gregraph/cache/\n", encoding="utf-8")


def _init_repo(root: Path, branch: str = "main") -> Path:
    _git(root, "init", "-b", branch)
    _git(root, "config", "user.name", "Test Author")
    _git(root, "config", "user.email", "test.author@example.org")
    _write_layout(root)
    _commit_all(root, "init")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Git repository on ``main`` with the spec §3 layout and one init commit."""
    return _init_repo(tmp_path, "main")


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    """gregraph layout without any Git repository (degraded mode)."""
    _write_layout(tmp_path)
    return tmp_path


def _workspace(root: Path) -> Workspace:
    return Workspace.open(root, git=GitAdapter(root))


def _body(title: str) -> str:
    return f"# {title}\n"


def _document(
    doc_id: str,
    *,
    title: str = "Sample",
    deprecated: bool = False,
    links: tuple[tuple[str, str], ...] = (),
) -> Document:
    return Document(
        schema=1,
        uuid=uuid5(NAMESPACE_URL, f"gregraph:test:{doc_id}"),
        id=doc_id,
        type="user-story",
        title=title,
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="user-story", version=1),
        version=1,
        body_hash=body_hash(_body(title)),
        assets=[],
        links=[
            Link(type=link_type, target=target, target_version=1)
            for link_type, target in links
        ],
        deprecated=(
            Deprecation(at=CREATED, by=None, reason="obsolete") if deprecated else None
        ),
        tags=[],
        extra={},
    )


def _term(slug: str, *, deprecated: bool = False) -> Term:
    name = slug.replace("-", " ").title()
    return Term(
        schema=1,
        term=name,
        slug=slug,
        aliases=[],
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="term", version=1),
        version=1,
        body_hash=body_hash(_body(name)),
        deprecated=(
            Deprecation(at=CREATED, by=None, reason="obsolete") if deprecated else None
        ),
    )


def _write_document(root: Path, document: Document) -> None:
    body_rel, sidecar_rel = document_paths(Path(), "user-story", document.id)
    write_body(root / body_rel, _body(document.title))
    write_sidecar(root / sidecar_rel, document)


def _write_term(root: Path, term: Term) -> None:
    body_rel, sidecar_rel = term_paths(Path(), term.slug)
    write_body(root / body_rel, _body(term.term))
    write_sidecar(root / sidecar_rel, term)


def _rewrite_body(root: Path, doc_id: str, text: str) -> None:
    body_rel, _ = document_paths(Path(), "user-story", doc_id)
    write_body(root / body_rel, text)


class TestDeriveStatus:
    def test_active(self) -> None:
        assert (
            derive_status(deprecated=False, superseded=False, draft=False) == "active"
        )

    def test_draft(self) -> None:
        assert derive_status(deprecated=False, superseded=False, draft=True) == "draft"

    def test_unknown_when_draft_unknown(self) -> None:
        assert (
            derive_status(deprecated=False, superseded=False, draft=None) == "unknown"
        )

    def test_superseded_beats_draft(self) -> None:
        assert (
            derive_status(deprecated=False, superseded=True, draft=True) == "superseded"
        )

    def test_superseded_beats_active(self) -> None:
        assert (
            derive_status(deprecated=False, superseded=True, draft=False)
            == "superseded"
        )

    def test_superseded_beats_unknown(self) -> None:
        assert (
            derive_status(deprecated=False, superseded=True, draft=None) == "superseded"
        )

    def test_deprecated_beats_draft(self) -> None:
        assert (
            derive_status(deprecated=True, superseded=False, draft=True) == "deprecated"
        )

    def test_deprecated_beats_superseded(self) -> None:
        assert (
            derive_status(deprecated=True, superseded=True, draft=False) == "deprecated"
        )

    def test_deprecated_beats_active(self) -> None:
        assert (
            derive_status(deprecated=True, superseded=False, draft=False)
            == "deprecated"
        )

    def test_deprecated_beats_unknown(self) -> None:
        assert (
            derive_status(deprecated=True, superseded=False, draft=None) == "deprecated"
        )

    def test_full_precedence_chain(self) -> None:
        assert (
            derive_status(deprecated=True, superseded=True, draft=True) == "deprecated"
        )
        assert (
            derive_status(deprecated=False, superseded=True, draft=True) == "superseded"
        )
        assert derive_status(deprecated=False, superseded=False, draft=True) == "draft"
        assert (
            derive_status(deprecated=False, superseded=False, draft=False) == "active"
        )


class TestDocumentStatus:
    def test_active_when_tracked_and_identical_to_baseline(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc")
        report = compute_status(_workspace(repo))
        item = report.documents["RE-AAAAAA"]
        assert item.status == "active"
        assert item.draft is False

    def test_draft_when_untracked(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        report = compute_status(_workspace(repo))
        item = report.documents["RE-AAAAAA"]
        assert item.status == "draft"
        assert item.draft is True

    def test_draft_when_body_modified(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc")
        _rewrite_body(repo, "RE-AAAAAA", "# Sample\n\nEdited.\n")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "draft"

    def test_draft_when_sidecar_modified(self, repo: Path) -> None:
        document = _document("RE-AAAAAA")
        _write_document(repo, document)
        _commit_all(repo, "add doc")
        changed = document.model_copy(update={"tags": ["edited"]})
        _write_document(repo, changed)
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "draft"

    def test_draft_when_committed_on_feature_branch(self, repo: Path) -> None:
        _git(repo, "checkout", "-b", "feature")
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc on feature")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "draft"

    def test_active_after_merge_into_baseline(self, repo: Path) -> None:
        _git(repo, "checkout", "-b", "feature")
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc on feature")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "feature")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "active"

    def test_superseded_when_successor_exists(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _write_document(
            repo, _document("RE-BBBBBB", links=(("supersedes", "RE-AAAAAA"),))
        )
        _commit_all(repo, "add docs")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "superseded"
        assert report.documents["RE-AAAAAA"].superseded is True
        assert report.documents["RE-BBBBBB"].status == "active"

    def test_superseded_beats_draft(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _write_document(
            repo, _document("RE-BBBBBB", links=(("supersedes", "RE-AAAAAA"),))
        )
        _commit_all(repo, "add docs")
        _rewrite_body(repo, "RE-AAAAAA", "# Sample\n\nEdited.\n")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "superseded"

    def test_deprecated_beats_draft(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA", deprecated=True))
        _rewrite_body(repo, "RE-AAAAAA", "# Sample\n\nEdited.\n")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "deprecated"

    def test_deprecated_beats_superseded(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA", deprecated=True))
        _write_document(
            repo, _document("RE-BBBBBB", links=(("supersedes", "RE-AAAAAA"),))
        )
        _commit_all(repo, "add docs")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "deprecated"

    def test_deprecated_beats_superseded_and_draft(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA", deprecated=True))
        _write_document(
            repo, _document("RE-BBBBBB", links=(("supersedes", "RE-AAAAAA"),))
        )
        _commit_all(repo, "add docs")
        _rewrite_body(repo, "RE-AAAAAA", "# Sample\n\nEdited.\n")
        report = compute_status(_workspace(repo))
        assert report.documents["RE-AAAAAA"].status == "deprecated"

    def test_healthy_repository_has_no_findings(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc")
        report = compute_status(_workspace(repo))
        assert report.findings == ()


class TestTermStatus:
    def test_active_when_tracked_and_identical_to_baseline(self, repo: Path) -> None:
        _write_term(repo, _term("knowledge-base"))
        _commit_all(repo, "add term")
        report = compute_status(_workspace(repo))
        assert report.terms["knowledge-base"].status == "active"

    def test_draft_when_untracked(self, repo: Path) -> None:
        _write_term(repo, _term("knowledge-base"))
        report = compute_status(_workspace(repo))
        assert report.terms["knowledge-base"].status == "draft"

    def test_deprecated_beats_draft(self, repo: Path) -> None:
        _write_term(repo, _term("knowledge-base", deprecated=True))
        body_rel, _ = term_paths(Path(), "knowledge-base")
        write_body(repo / body_rel, "# Knowledge Base\n\nEdited.\n")
        report = compute_status(_workspace(repo))
        assert report.terms["knowledge-base"].status == "deprecated"


class TestDegradedMode:
    def test_unknown_without_git_repository(self, plain: Path) -> None:
        _write_document(plain, _document("RE-AAAAAA"))
        report = compute_status(_workspace(plain))
        assert report.documents["RE-AAAAAA"].status == "unknown"
        assert report.documents["RE-AAAAAA"].draft is None

    def test_unknown_with_null_adapter(self, plain: Path) -> None:
        _write_document(plain, _document("RE-AAAAAA"))
        report = compute_status(Workspace.open(plain))
        assert report.documents["RE-AAAAAA"].status == "unknown"

    def test_unknown_for_terms(self, plain: Path) -> None:
        _write_term(plain, _term("knowledge-base"))
        report = compute_status(_workspace(plain))
        assert report.terms["knowledge-base"].status == "unknown"

    def test_stored_flags_still_resolve(self, plain: Path) -> None:
        _write_document(plain, _document("RE-AAAAAA", deprecated=True))
        _write_document(plain, _document("RE-BBBBBB"))
        _write_document(
            plain, _document("RE-CCCCCC", links=(("supersedes", "RE-BBBBBB"),))
        )
        report = compute_status(_workspace(plain))
        assert report.documents["RE-AAAAAA"].status == "deprecated"
        assert report.documents["RE-BBBBBB"].status == "superseded"
        assert report.documents["RE-CCCCCC"].status == "unknown"

    def test_no_findings(self, plain: Path) -> None:
        _write_document(plain, _document("RE-AAAAAA"))
        report = compute_status(_workspace(plain))
        assert report.findings == ()


class TestMissingBaseline:
    @pytest.fixture
    def trunk_repo(self, tmp_path: Path) -> Path:
        """Repository with commits on ``trunk`` only; default baseline missing."""
        return _init_repo(tmp_path, "trunk")

    def test_unknown_with_warning(self, trunk_repo: Path) -> None:
        _write_document(trunk_repo, _document("RE-AAAAAA"))
        _commit_all(trunk_repo, "add doc")
        report = compute_status(_workspace(trunk_repo))
        assert report.documents["RE-AAAAAA"].status == "unknown"
        assert report.documents["RE-AAAAAA"].draft is None
        [finding] = report.findings
        assert finding.code == "W-BASELINE-MISSING"
        assert finding.severity == "W"
        assert finding.subject == CONFIG_RELPATH

    def test_unknown_for_terms(self, trunk_repo: Path) -> None:
        _write_term(trunk_repo, _term("knowledge-base"))
        _commit_all(trunk_repo, "add term")
        report = compute_status(_workspace(trunk_repo))
        assert report.terms["knowledge-base"].status == "unknown"
        assert len(report.findings) == 1

    def test_deprecated_still_resolves(self, trunk_repo: Path) -> None:
        _write_document(trunk_repo, _document("RE-AAAAAA", deprecated=True))
        _commit_all(trunk_repo, "add doc")
        report = compute_status(_workspace(trunk_repo))
        assert report.documents["RE-AAAAAA"].status == "deprecated"

    def test_baseline_branch_comes_from_config(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-b", "trunk")
        _git(tmp_path, "config", "user.name", "Test Author")
        _git(tmp_path, "config", "user.email", "test.author@example.org")
        _write_layout(tmp_path, Config(git=GitSection(baseline_branch="trunk")))
        _commit_all(tmp_path, "init")
        _write_document(tmp_path, _document("RE-AAAAAA"))
        _commit_all(tmp_path, "add doc")
        report = compute_status(_workspace(tmp_path))
        assert report.documents["RE-AAAAAA"].status == "active"
        assert report.findings == ()


class TestWip:
    def test_clean_repository_is_not_wip(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc")
        wip = compute_status(_workspace(repo)).wip
        assert wip.is_wip is False
        assert wip.draft_count == 0
        assert wip.modified_count == 0
        assert wip.uncommitted == ()

    def test_untracked_document_is_draft(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        wip = compute_status(_workspace(repo)).wip
        assert wip.is_wip is True
        assert wip.draft_count == 1
        assert [item.key for item in wip.drafts] == ["RE-AAAAAA"]

    def test_edited_body_is_unbumped_modification(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc")
        _rewrite_body(repo, "RE-AAAAAA", "# Sample\n\nEdited.\n")
        wip = compute_status(_workspace(repo)).wip
        assert wip.modified_count == 1
        assert [item.key for item in wip.modified] == ["RE-AAAAAA"]
        assert wip.is_wip is True

    def test_sidecar_only_edit_is_not_unbumped(self, repo: Path) -> None:
        document = _document("RE-AAAAAA")
        _write_document(repo, document)
        _commit_all(repo, "add doc")
        _write_document(repo, document.model_copy(update={"tags": ["edited"]}))
        wip = compute_status(_workspace(repo)).wip
        assert wip.modified_count == 0
        assert wip.draft_count == 1

    def test_committed_draft_counts_without_uncommitted(self, repo: Path) -> None:
        _git(repo, "checkout", "-b", "feature")
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc on feature")
        wip = compute_status(_workspace(repo)).wip
        assert wip.is_wip is True
        assert wip.draft_count == 1
        assert wip.modified_count == 0
        assert wip.uncommitted == ()

    def test_uncommitted_stray_file_under_managed_dir(self, repo: Path) -> None:
        (repo / "assets" / "orphan.bin").write_bytes(b"\x00\x01")
        wip = compute_status(_workspace(repo)).wip
        assert wip.is_wip is True
        assert wip.uncommitted == (Path("assets/orphan.bin"),)
        assert wip.draft_count == 0
        assert wip.modified_count == 0

    def test_untracked_file_outside_managed_dirs_ignored(self, repo: Path) -> None:
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        wip = compute_status(_workspace(repo)).wip
        assert wip.is_wip is False

    def test_staged_file_is_still_uncommitted(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        body_rel, sidecar_rel = document_paths(Path(), "user-story", "RE-AAAAAA")
        _git(repo, "add", body_rel.as_posix(), sidecar_rel.as_posix())
        wip = compute_status(_workspace(repo)).wip
        assert wip.is_wip is True
        assert wip.uncommitted != ()

    def test_counts_feed_the_status_header(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _write_document(repo, _document("RE-BBBBBB"))
        _write_document(repo, _document("RE-CCCCCC"))
        _commit_all(repo, "add docs")
        _rewrite_body(repo, "RE-CCCCCC", "# Sample\n\nEdited.\n")
        _git(repo, "checkout", "-b", "feature")
        _write_document(repo, _document("RE-DDDDDD"))
        _commit_all(repo, "add draft on feature")
        wip = compute_status(_workspace(repo)).wip
        assert wip.is_wip is True
        assert wip.draft_count == 2
        assert wip.modified_count == 1
        assert {item.key for item in wip.drafts} == {"RE-CCCCCC", "RE-DDDDDD"}
        assert [item.key for item in wip.modified] == ["RE-CCCCCC"]

    def test_term_modifications_count(self, plain: Path) -> None:
        _write_term(plain, _term("knowledge-base"))
        body_rel, _ = term_paths(Path(), "knowledge-base")
        write_body(plain / body_rel, "# Knowledge Base\n\nEdited.\n")
        wip = compute_status(_workspace(plain)).wip
        assert wip.modified_count == 1
        assert wip.is_wip is True

    def test_degraded_mode_sees_unbumped_modifications(self, plain: Path) -> None:
        _write_document(plain, _document("RE-AAAAAA"))
        _rewrite_body(plain, "RE-AAAAAA", "# Sample\n\nEdited.\n")
        wip = compute_status(_workspace(plain)).wip
        assert wip.modified_count == 1
        assert wip.draft_count == 0
        assert wip.uncommitted == ()

    def test_wip_state_defaults_are_empty(self) -> None:
        wip = WipState()
        assert wip.is_wip is False
        assert wip.draft_count == 0
        assert wip.modified_count == 0
        assert wip.uncommitted_count == 0


class TestOpenConflicts:
    def test_counts_live_pair(self, repo: Path) -> None:
        _write_document(
            repo, _document("RE-AAAAAA", links=(("conflicts-with", "RE-BBBBBB"),))
        )
        _write_document(repo, _document("RE-BBBBBB"))
        _commit_all(repo, "add docs")
        report = compute_status(_workspace(repo))
        assert report.open_conflicts == (("RE-AAAAAA", "RE-BBBBBB"),)
        assert report.open_conflict_count == 1

    def test_symmetric_recorded_both_ways_counted_once(self, repo: Path) -> None:
        _write_document(
            repo, _document("RE-AAAAAA", links=(("conflicts-with", "RE-BBBBBB"),))
        )
        _write_document(
            repo, _document("RE-BBBBBB", links=(("conflicts-with", "RE-AAAAAA"),))
        )
        _commit_all(repo, "add docs")
        report = compute_status(_workspace(repo))
        assert report.open_conflict_count == 1

    def test_deprecated_endpoint_closes_conflict(self, repo: Path) -> None:
        _write_document(
            repo, _document("RE-AAAAAA", links=(("conflicts-with", "RE-BBBBBB"),))
        )
        _write_document(repo, _document("RE-BBBBBB", deprecated=True))
        _commit_all(repo, "add docs")
        report = compute_status(_workspace(repo))
        assert report.open_conflict_count == 0

    def test_superseded_endpoint_closes_conflict(self, repo: Path) -> None:
        _write_document(
            repo, _document("RE-AAAAAA", links=(("conflicts-with", "RE-BBBBBB"),))
        )
        _write_document(repo, _document("RE-BBBBBB"))
        _write_document(
            repo, _document("RE-CCCCCC", links=(("supersedes", "RE-BBBBBB"),))
        )
        _commit_all(repo, "add docs")
        report = compute_status(_workspace(repo))
        assert report.open_conflict_count == 0

    def test_multiple_pairs(self, repo: Path) -> None:
        _write_document(
            repo,
            _document(
                "RE-AAAAAA",
                links=(
                    ("conflicts-with", "RE-BBBBBB"),
                    ("conflicts-with", "RE-CCCCCC"),
                ),
            ),
        )
        _write_document(repo, _document("RE-BBBBBB"))
        _write_document(repo, _document("RE-CCCCCC"))
        _commit_all(repo, "add docs")
        report = compute_status(_workspace(repo))
        assert report.open_conflicts == (
            ("RE-AAAAAA", "RE-BBBBBB"),
            ("RE-AAAAAA", "RE-CCCCCC"),
        )
        assert report.open_conflict_count == 2

    def test_dangling_target_not_counted(self, repo: Path) -> None:
        _write_document(
            repo, _document("RE-AAAAAA", links=(("conflicts-with", "RE-ZZZZZZ"),))
        )
        _commit_all(repo, "add doc")
        report = compute_status(_workspace(repo))
        assert report.open_conflict_count == 0

    def test_open_conflicts_helper_uses_the_graph(self, repo: Path) -> None:
        _write_document(
            repo, _document("RE-AAAAAA", links=(("conflicts-with", "RE-BBBBBB"),))
        )
        _write_document(repo, _document("RE-BBBBBB"))
        _commit_all(repo, "add docs")
        workspace = _workspace(repo)
        assert open_conflicts(workspace.graph) == (("RE-AAAAAA", "RE-BBBBBB"),)


class TestStatusReport:
    def test_reports_documents_and_terms(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _write_term(repo, _term("knowledge-base"))
        _commit_all(repo, "add items")
        report = compute_status(_workspace(repo))
        assert set(report.documents) == {"RE-AAAAAA"}
        assert set(report.terms) == {"knowledge-base"}
        assert isinstance(report.documents["RE-AAAAAA"], ItemStatus)
        assert report.documents["RE-AAAAAA"].body == Path(
            "documents/user-story/RE-AAAAAA.md"
        )
        assert report.documents["RE-AAAAAA"].sidecar == Path(
            "documents/user-story/RE-AAAAAA.json"
        )
        assert report.documents["RE-AAAAAA"].deprecated is False
        assert report.documents["RE-AAAAAA"].superseded is False

    def test_report_is_plain_data(self, repo: Path) -> None:
        _write_document(repo, _document("RE-AAAAAA"))
        _commit_all(repo, "add doc")
        report = compute_status(_workspace(repo))
        payload: dict[str, Any] = {
            "documents": {key: item.status for key, item in report.documents.items()},
            "wip": report.wip.is_wip,
            "conflicts": report.open_conflict_count,
        }
        assert payload == {
            "documents": {"RE-AAAAAA": "active"},
            "wip": False,
            "conflicts": 0,
        }
