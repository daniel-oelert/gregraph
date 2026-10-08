"""Tests for ``gregraph.core.workspace`` (spec §3, §1.5, §16.1–16.2, §16.5).

Test-first (appendix C): root discovery (nearest ancestor with
``.gregraph/config.toml``), lazy full-index loading of all sidecars, load
findings (``E-SIDECAR-MISSING``, ``E-BODY-MISSING``, ``E-SIDECAR-INVALID``,
``E-ID-DUPLICATE``), lazy cache, and ``reload``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from gregraph.core.config import Config, write_config
from gregraph.core.hashing import body_hash
from gregraph.core.models import (
    ChangeRequest,
    Document,
    TemplateRef,
    Term,
)
from gregraph.core.storage import (
    CACHE_RELPATH,
    change_paths,
    config_path,
    document_paths,
    term_paths,
    write_body,
    write_sidecar,
)
from gregraph.core.workspace import (
    Index,
    Loaded,
    Workspace,
    find_root,
    load_index,
)

UTC = dt.UTC
CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=UTC)


def make_document(
    doc_id: str,
    doc_type: str = "user-story",
    title: str = "Sample",
    links: list[tuple[str, str]] | None = None,
) -> Document:
    return Document(
        schema=1,
        uuid=uuid5(NAMESPACE_URL, f"gregraph:test:{doc_id}"),
        id=doc_id,
        type=doc_type,
        title=title,
        created=CREATED,
        created_by=None,
        template=TemplateRef(name=doc_type, version=1),
        version=1,
        body_hash=body_hash(f"# {title}\n"),
        assets=[],
        links=[
            {"type": link_type, "target": target, "target_version": 1}
            for link_type, target in (links or [])
        ],
        deprecated=None,
        tags=[],
        extra={},
    )


def make_change(cr_id: str) -> ChangeRequest:
    return ChangeRequest(
        schema=1,
        uuid=uuid5(NAMESPACE_URL, f"gregraph:test:{cr_id}"),
        id=cr_id,
        title="Change something",
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="change-request", version=1),
        version=1,
        body_hash=body_hash("# Change something\n"),
        scope_hash="sha256:00",
        scope=[],
        introduces=[],
        status="open",
        decisions=[],
        branch=None,
        external_ref=None,
        tags=[],
        extra={},
    )


def make_term(slug: str) -> Term:
    return Term(
        schema=1,
        term=slug.replace("-", " ").title(),
        slug=slug,
        aliases=[],
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="term", version=1),
        version=1,
        body_hash=body_hash(f"# {slug}\n"),
        deprecated=None,
    )


def write_document(root: Path, folder: str, document: Document) -> Path:
    body_rel, sidecar_rel = document_paths(Path(), folder, document.id)
    write_body(root / body_rel, f"# {document.title}\n")
    write_sidecar(root / sidecar_rel, document)
    return sidecar_rel


class TestFindRoot:
    def test_returns_none_without_marker(self, tmp_path: Path) -> None:
        (tmp_path / "a" / "b").mkdir(parents=True)
        assert find_root(tmp_path / "a" / "b") is None

    def test_finds_marker_in_start_directory(self, tmp_repo: Path) -> None:
        assert find_root(tmp_repo) == tmp_repo

    def test_finds_marker_in_ancestor(self, tmp_repo: Path) -> None:
        nested = tmp_repo / "documents" / "user-story"
        nested.mkdir(parents=True, exist_ok=True)
        assert find_root(nested) == tmp_repo

    def test_nearest_marker_wins(self, tmp_repo: Path) -> None:
        nested_root = tmp_repo / "documents"
        write_config(config_path(nested_root), Config())
        deep = nested_root / "user-story"
        deep.mkdir(parents=True, exist_ok=True)
        assert find_root(deep) == nested_root

    def test_ignores_directory_named_like_config(self, tmp_path: Path) -> None:
        marker = tmp_path / ".gregraph" / "config.toml"
        marker.parent.mkdir()
        marker.mkdir()
        assert find_root(tmp_path) is None


class TestWorkspaceOpen:
    def test_raises_without_root(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            Workspace.open(tmp_path)

    def test_reads_config_defaults(self, tmp_repo: Path) -> None:
        workspace = Workspace.open(tmp_repo)
        assert workspace.root == tmp_repo
        assert workspace.config.ids.prefix == "RE"
        assert "user-story" in workspace.config.types

    def test_reads_written_config(self, tmp_repo: Path) -> None:
        config = Config()
        config.ids.prefix = "XX"
        write_config(config_path(tmp_repo), config)
        workspace = Workspace.open(tmp_repo)
        assert workspace.config.ids.prefix == "XX"

    def test_defaults_to_null_git_adapter(self, tmp_repo: Path) -> None:
        from gregraph.core.git import NullGitAdapter

        workspace = Workspace.open(tmp_repo)
        assert isinstance(workspace.git, NullGitAdapter)


class TestLoadIndex:
    def test_empty_repo(self, tmp_repo: Path) -> None:
        index = load_index(tmp_repo)
        assert index.documents == {}
        assert index.changes == {}
        assert index.terms == {}
        assert index.findings == ()

    def test_loads_documents_changes_terms(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "user-story", make_document("RE-AAAAAA"))
        body, sidecar = change_paths(Path(), "RE-BBBBBB")
        write_body(tmp_repo / body, "# Change something\n")
        write_sidecar(tmp_repo / sidecar, make_change("RE-BBBBBB"))
        body, sidecar = term_paths(Path(), "knowledge-base")
        write_body(tmp_repo / body, "# Knowledge Base\n")
        write_sidecar(tmp_repo / sidecar, make_term("knowledge-base"))

        index = load_index(tmp_repo)
        assert set(index.documents) == {"RE-AAAAAA"}
        assert set(index.changes) == {"RE-BBBBBB"}
        assert set(index.terms) == {"knowledge-base"}
        assert index.findings == ()

    def test_loads_documents_from_nested_folders(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "feature", make_document("RE-AAAAAA"))
        write_document(tmp_repo, "epic", make_document("RE-BBBBBB"))
        index = load_index(tmp_repo)
        assert set(index.documents) == {"RE-AAAAAA", "RE-BBBBBB"}

    def test_paths_are_repo_relative(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "user-story", make_document("RE-AAAAAA"))
        index = load_index(tmp_repo)
        loaded = index.documents["RE-AAAAAA"]
        assert isinstance(loaded, Loaded)
        assert not loaded.body.is_absolute()
        assert not loaded.sidecar.is_absolute()
        assert loaded.body == Path("documents/user-story/RE-AAAAAA.md")
        assert loaded.sidecar == Path("documents/user-story/RE-AAAAAA.json")

    def test_missing_sidecar_finding(self, tmp_repo: Path) -> None:
        body, _ = document_paths(Path(), "user-story", "RE-AAAAAA")
        write_body(tmp_repo / body, "# Orphan body\n")
        index = load_index(tmp_repo)
        assert index.documents == {}
        [finding] = index.findings
        assert finding.code == "E-SIDECAR-MISSING"
        assert finding.severity == "E"
        assert finding.subject == body

    def test_missing_body_finding_but_document_loaded(self, tmp_repo: Path) -> None:
        document = make_document("RE-AAAAAA")
        _, sidecar = document_paths(Path(), "user-story", "RE-AAAAAA")
        write_sidecar(tmp_repo / sidecar, document)
        index = load_index(tmp_repo)
        assert set(index.documents) == {"RE-AAAAAA"}
        [finding] = index.findings
        assert finding.code == "E-BODY-MISSING"
        assert finding.subject == sidecar

    def test_invalid_sidecar_finding(self, tmp_repo: Path) -> None:
        _, sidecar = document_paths(Path(), "user-story", "RE-AAAAAA")
        write_body(tmp_repo / sidecar.with_suffix(".md"), "# Broken\n")
        write_sidecar(tmp_repo / sidecar, {"schema": 1})
        index = load_index(tmp_repo)
        assert index.documents == {}
        [finding] = index.findings
        assert finding.code == "E-SIDECAR-INVALID"
        assert finding.subject == sidecar

    def test_unparsable_json_finding(self, tmp_repo: Path) -> None:
        _, sidecar = document_paths(Path(), "user-story", "RE-AAAAAA")
        write_body(tmp_repo / sidecar.with_suffix(".md"), "# Broken\n")
        full_sidecar = tmp_repo / sidecar
        full_sidecar.parent.mkdir(parents=True, exist_ok=True)
        full_sidecar.write_text("{not json", encoding="utf-8")
        index = load_index(tmp_repo)
        [finding] = index.findings
        assert finding.code == "E-SIDECAR-INVALID"

    def test_duplicate_id_keeps_first(self, tmp_repo: Path) -> None:
        first = make_document("RE-AAAAAA", title="First")
        second = make_document("RE-AAAAAA", title="Second")
        write_document(tmp_repo, "epic", first)
        write_document(tmp_repo, "feature", second)
        index = load_index(tmp_repo)
        assert set(index.documents) == {"RE-AAAAAA"}
        assert index.documents["RE-AAAAAA"].model.title == "First"
        [finding] = index.findings
        assert finding.code == "E-ID-DUPLICATE"
        assert finding.subject == "RE-AAAAAA"

    def test_duplicate_id_across_documents_and_changes(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "user-story", make_document("RE-AAAAAA"))
        body, sidecar = change_paths(Path(), "RE-AAAAAA")
        write_body(tmp_repo / body, "# Change\n")
        write_sidecar(tmp_repo / sidecar, make_change("RE-AAAAAA"))
        index = load_index(tmp_repo)
        assert set(index.documents) == {"RE-AAAAAA"}
        assert index.changes == {}
        [finding] = index.findings
        assert finding.code == "E-ID-DUPLICATE"
        assert finding.subject == "RE-AAAAAA"

    def test_documents_keep_links(self, tmp_repo: Path) -> None:
        document = make_document(
            "RE-AAAAAA", links=[("refines", "RE-BBBBBB"), ("depends-on", "RE-CCCCCC")]
        )
        write_document(tmp_repo, "user-story", document)
        index = load_index(tmp_repo)
        loaded = index.documents["RE-AAAAAA"]
        assert [link.target for link in loaded.model.links] == [
            "RE-CCCCCC",
            "RE-BBBBBB",
        ]


class TestWorkspaceIndex:
    def test_index_is_lazy_and_cached(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "user-story", make_document("RE-AAAAAA"))
        workspace = Workspace.open(tmp_repo)
        first = workspace.index
        assert set(first.documents) == {"RE-AAAAAA"}
        _, sidecar = document_paths(Path(), "user-story", "RE-BBBBBB")
        write_document(tmp_repo, "user-story", make_document("RE-BBBBBB"))
        assert workspace.index is first
        assert set(workspace.index.documents) == {"RE-AAAAAA"}

    def test_reload_picks_up_changes(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "user-story", make_document("RE-AAAAAA"))
        workspace = Workspace.open(tmp_repo)
        assert set(workspace.index.documents) == {"RE-AAAAAA"}
        write_document(tmp_repo, "user-story", make_document("RE-BBBBBB"))
        workspace.reload()
        assert set(workspace.index.documents) == {"RE-AAAAAA", "RE-BBBBBB"}

    def test_cache_is_lazy(self, tmp_repo: Path) -> None:
        workspace = Workspace.open(tmp_repo)
        cache = workspace.cache
        assert cache.files == {}
        assert cache.tool_version
        assert (tmp_repo / CACHE_RELPATH).exists() is False

    def test_graph_is_lazy_and_cached(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "user-story", make_document("RE-AAAAAA"))
        workspace = Workspace.open(tmp_repo)
        first = workspace.graph
        assert set(first.nodes) == {"RE-AAAAAA"}
        assert workspace.graph is first

    def test_index_exposes_typed_entries(self, tmp_repo: Path) -> None:
        write_document(tmp_repo, "user-story", make_document("RE-AAAAAA"))
        index = load_index(tmp_repo)
        assert isinstance(index, Index)
        loaded = index.documents["RE-AAAAAA"]
        assert isinstance(loaded, Loaded)
        assert isinstance(loaded.model, Document)
