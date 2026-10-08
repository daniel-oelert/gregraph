"""Storage tests: paths, canonical JSON, sidecars, bodies, cache (spec §3, §5.4, §16.5).

Test-first (appendix C): these drive ``gregraph/core/storage.py``.

Canonical JSON idempotence tests are mandatory (S3 handoff). Model↔file
round-trips use the real models from ``gregraph.core.models``.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gregraph.core.models import (
    AssetRef,
    ChangeRequest,
    Decision,
    Document,
    Identity,
    Link,
    ScopeEntry,
    TemplateRef,
    Term,
)
from gregraph.core.storage import (
    assets_dir,
    cache_entry_is_fresh,
    cache_path,
    canonical_json_bytes,
    canonical_json_dumps,
    change_paths,
    config_path,
    document_paths,
    find_change,
    find_document,
    find_term,
    iter_changes,
    iter_documents,
    iter_terms,
    load_cache,
    read_body,
    read_sidecar,
    stat_cache_entry,
    templates_dir,
    term_paths,
    write_body,
    write_cache,
    write_sidecar,
)

UTC = dt.UTC
CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=UTC)


def make_document(
    doc_id: str = "RE-7F3K2Q",
    links: list[Link] | None = None,
) -> Document:
    return Document(
        schema=1,
        uuid=uuid.UUID("6f3c2f1e-8b3e-4a4c-9a3d-2d0f5b7a9c11"),
        id=doc_id,
        type="user-story",
        title="Upload documents to a knowledge base",
        created=CREATED,
        created_by=Identity(name="Jane Doe", email="jane@example.org"),
        template=TemplateRef(name="user-story", version=2),
        version=3,
        body_hash="sha256:9c1d",
        assets=[AssetRef(path="upload-flow.png", hash="sha256:41ab")],
        links=links
        or [
            Link(type="depends-on", target="RE-9PZ0AH", target_version=1),
            Link(type="refines", target="RE-2K7QMB", target_version=4),
        ],
        deprecated=None,
        tags=["upload"],
        extra={"priority": "high"},
    )


def make_change_request() -> ChangeRequest:
    return ChangeRequest(
        schema=1,
        uuid=uuid.UUID("0b9e7c1a-3d2f-4e8b-9a61-5c4d2e1f0a77"),
        id="RE-3M9XA1",
        title="Raise knowledge-base upload limit to 200 MB",
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="change-request", version=1),
        version=2,
        body_hash="sha256:aa11",
        scope_hash="sha256:bb22",
        scope=[
            ScopeEntry(id="RE-9PZ0AH", intent="supersede", base_version=1),
            ScopeEntry(id="RE-7F3K2Q", intent="modify", base_version=3),
        ],
        introduces=["RE-Q4M2ZT", "RE-A1B2C3"],
        status="accepted",
        decisions=[
            Decision(
                status="open",
                at=CREATED,
                by=Identity(name="Jane Doe", email="jane@example.org"),
                at_version=1,
            ),
        ],
        branch=None,
        external_ref=None,
        tags=[],
        extra={},
    )


def make_term() -> Term:
    return Term(
        schema=1,
        term="Knowledge base",
        slug="knowledge-base",
        aliases=["KB"],
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="term", version=1),
        version=2,
        body_hash="sha256:cc33",
        deprecated=None,
    )


# ---------------------------------------------------------------------------
# Path rules (spec §3)
# ---------------------------------------------------------------------------


def test_config_path(tmp_repo: Path) -> None:
    assert config_path(tmp_repo) == tmp_repo / ".gregraph" / "config.toml"


def test_cache_path(tmp_repo: Path) -> None:
    assert cache_path(tmp_repo) == tmp_repo / ".gregraph" / "cache" / "index.json"


def test_templates_dir(tmp_repo: Path) -> None:
    assert templates_dir(tmp_repo) == tmp_repo / ".gregraph" / "templates"


def test_document_paths(tmp_repo: Path) -> None:
    body, sidecar = document_paths(tmp_repo, "user-stories", "RE-7F3K2Q")
    assert body == tmp_repo / "documents" / "user-stories" / "RE-7F3K2Q.md"
    assert sidecar == tmp_repo / "documents" / "user-stories" / "RE-7F3K2Q.json"
    assert assets_dir(tmp_repo, "RE-7F3K2Q") == tmp_repo / "assets" / "RE-7F3K2Q"


def test_change_paths(tmp_repo: Path) -> None:
    body, sidecar = change_paths(tmp_repo, "RE-3M9XA1")
    assert body == tmp_repo / "changes" / "RE-3M9XA1.md"
    assert sidecar == tmp_repo / "changes" / "RE-3M9XA1.json"


def test_term_paths(tmp_repo: Path) -> None:
    body, sidecar = term_paths(tmp_repo, "knowledge-base")
    assert body == tmp_repo / "glossary" / "knowledge-base.md"
    assert sidecar == tmp_repo / "glossary" / "knowledge-base.json"


def test_find_document_scans_all_folders(tmp_repo: Path) -> None:
    body, sidecar = document_paths(tmp_repo, "user-stories", "RE-7F3K2Q")
    body.parent.mkdir(parents=True)
    body.write_text("# Title\n", encoding="utf-8")
    sidecar.write_text("{}", encoding="utf-8")
    found = find_document(tmp_repo, "RE-7F3K2Q")
    assert found is not None
    assert found.stem == "RE-7F3K2Q"
    assert found.body == body
    assert found.sidecar == sidecar
    assert find_document(tmp_repo, "RE-NOPE") is None


def test_find_document_nested_folder(tmp_repo: Path) -> None:
    body, sidecar = document_paths(tmp_repo, "specs/deep", "RE-1")
    body.parent.mkdir(parents=True)
    body.write_text("# T\n", encoding="utf-8")
    sidecar.write_text("{}", encoding="utf-8")
    found = find_document(tmp_repo, "RE-1")
    assert found is not None
    assert found.body == body


def test_find_change_and_term(tmp_repo: Path) -> None:
    cr_body, cr_sidecar = change_paths(tmp_repo, "RE-3M9XA1")
    cr_body.write_text("# CR\n", encoding="utf-8")
    cr_sidecar.write_text("{}", encoding="utf-8")
    term_body, term_sidecar = term_paths(tmp_repo, "knowledge-base")
    term_body.write_text("# Knowledge base\n", encoding="utf-8")
    term_sidecar.write_text("{}", encoding="utf-8")
    found_cr = find_change(tmp_repo, "RE-3M9XA1")
    assert found_cr is not None
    assert (found_cr.body, found_cr.sidecar) == (cr_body, cr_sidecar)
    found_term = find_term(tmp_repo, "knowledge-base")
    assert found_term is not None
    assert (found_term.body, found_term.sidecar) == (term_body, term_sidecar)
    assert find_change(tmp_repo, "RE-NOPE") is None
    assert find_term(tmp_repo, "nope") is None


def test_iterators_list_every_stem(tmp_repo: Path) -> None:
    doc_body, _ = document_paths(tmp_repo, "features", "RE-A")
    doc_body.parent.mkdir(parents=True)
    doc_body.write_text("# A\n", encoding="utf-8")
    _, doc_sidecar = document_paths(tmp_repo, "goals", "RE-B")
    doc_sidecar.parent.mkdir(parents=True)
    doc_sidecar.write_text("{}", encoding="utf-8")
    cr_body, cr_sidecar = change_paths(tmp_repo, "RE-C")
    cr_body.write_text("# C\n", encoding="utf-8")
    cr_sidecar.write_text("{}", encoding="utf-8")
    term_body, term_sidecar = term_paths(tmp_repo, "kb")
    term_body.write_text("# kb\n", encoding="utf-8")
    term_sidecar.write_text("{}", encoding="utf-8")
    assert sorted(f.stem for f in iter_documents(tmp_repo)) == ["RE-A", "RE-B"]
    assert [f.stem for f in iter_changes(tmp_repo)] == ["RE-C"]
    assert [f.stem for f in iter_terms(tmp_repo)] == ["kb"]


# ---------------------------------------------------------------------------
# Canonical JSON (spec §5.4, global rules)
# ---------------------------------------------------------------------------


def test_canonical_json_format() -> None:
    text = canonical_json_dumps({"b": 1, "a": [1, 2], "ü": "nï"})
    assert text == '{\n  "a": [\n    1,\n    2\n  ],\n  "b": 1,\n  "ü": "nï"\n}\n'


def test_canonical_json_bytes_stability_key_order() -> None:
    one = {"a": 1, "b": {"x": 1, "y": 2}, "c": [3]}
    two = {"c": [3], "b": {"y": 2, "x": 1}, "a": 1}
    assert canonical_json_bytes(one) == canonical_json_bytes(two)


def test_canonical_json_idempotent_rewrite() -> None:
    original = {"title": "T", "links": [{"type": "refines", "target": "RE-B"}], "z": 1}
    once = canonical_json_bytes(original)
    twice = canonical_json_bytes(json.loads(once.decode("utf-8")))
    assert once == twice


def test_links_sorted_by_type_then_target() -> None:
    links = [
        {"type": "refines", "target": "RE-B", "target_version": 1},
        {"type": "depends-on", "target": "RE-C", "target_version": 1},
        {"type": "refines", "target": "RE-A", "target_version": 2},
    ]
    dumped = json.loads(canonical_json_dumps({"links": links}))
    assert [(link["type"], link["target"]) for link in dumped["links"]] == [
        ("depends-on", "RE-C"),
        ("refines", "RE-A"),
        ("refines", "RE-B"),
    ]


def test_scope_sorted_by_id_and_introduces_sorted() -> None:
    dumped = json.loads(
        canonical_json_dumps(
            {
                "scope": [
                    {"id": "RE-B", "intent": "modify", "base_version": 1},
                    {"id": "RE-A", "intent": "supersede", "base_version": 2},
                ],
                "introduces": ["RE-Z", "RE-A"],
            }
        )
    )
    assert [entry["id"] for entry in dumped["scope"]] == ["RE-A", "RE-B"]
    assert dumped["introduces"] == ["RE-A", "RE-Z"]


def test_canonical_json_leaves_unrelated_lists_alone() -> None:
    dumped = json.loads(
        canonical_json_dumps({"tags": ["b", "a"], "assets": [{"path": "z"}]})
    )
    assert dumped["tags"] == ["b", "a"]
    assert dumped["assets"] == [{"path": "z"}]


def test_canonical_json_unicode_not_escaped() -> None:
    assert "Ünïcode" in canonical_json_dumps({"t": "Ünïcode"})


def test_canonical_json_trailing_newline() -> None:
    assert canonical_json_dumps({}).endswith("\n")
    assert not canonical_json_dumps({}).endswith("\n\n")


_json_atoms = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.text(max_size=8)
)
_json_values = st.recursive(
    _json_atoms,
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=8,
)


@given(payload=st.dictionaries(st.text(max_size=8), _json_values, max_size=5))
def test_canonical_json_hypothesis_idempotent(payload: dict[str, Any]) -> None:
    once = canonical_json_dumps(payload)
    twice = canonical_json_dumps(json.loads(once))
    assert once == twice


@given(payload=st.dictionaries(st.text(max_size=8), _json_values, max_size=5))
def test_canonical_json_hypothesis_key_order_invariant(payload: dict[str, Any]) -> None:
    reversed_payload = dict(reversed(list(payload.items())))
    assert canonical_json_dumps(payload) == canonical_json_dumps(reversed_payload)


# ---------------------------------------------------------------------------
# Sidecar read/write (spec §5.4, §9.2, §10.2)
# ---------------------------------------------------------------------------


def test_document_round_trip(tmp_repo: Path) -> None:
    body, sidecar = document_paths(tmp_repo, "user-stories", "RE-7F3K2Q")
    document = make_document()
    write_sidecar(sidecar, document)
    assert read_sidecar(sidecar, Document) == document
    once = sidecar.read_bytes()
    write_sidecar(sidecar, read_sidecar(sidecar, Document))
    assert sidecar.read_bytes() == once


def test_document_canonicalises_links(tmp_repo: Path) -> None:
    _, sidecar = document_paths(tmp_repo, "features", "RE-L")
    sidecar.parent.mkdir(parents=True)
    document = make_document(
        links=[
            Link(type="refines", target="RE-B", target_version=1),
            Link(type="refines", target="RE-A", target_version=1),
        ]
    )
    write_sidecar(sidecar, document)
    loaded = read_sidecar(sidecar, Document)
    assert [(link.type, link.target) for link in loaded.links] == [
        ("refines", "RE-A"),
        ("refines", "RE-B"),
    ]
    assert sidecar.read_bytes() == canonical_json_bytes(loaded)


def test_change_request_round_trip(tmp_repo: Path) -> None:
    _, sidecar = change_paths(tmp_repo, "RE-3M9XA1")
    cr = make_change_request()
    write_sidecar(sidecar, cr)
    loaded = read_sidecar(sidecar, ChangeRequest)
    assert [entry.id for entry in loaded.scope] == ["RE-7F3K2Q", "RE-9PZ0AH"]
    assert loaded.introduces == ["RE-A1B2C3", "RE-Q4M2ZT"]
    once = sidecar.read_bytes()
    write_sidecar(sidecar, loaded)
    assert sidecar.read_bytes() == once


def test_term_round_trip(tmp_repo: Path) -> None:
    _, sidecar = term_paths(tmp_repo, "knowledge-base")
    term = make_term()
    write_sidecar(sidecar, term)
    assert read_sidecar(sidecar, Term) == term


def test_sidecar_file_bytes_are_canonical(tmp_repo: Path) -> None:
    _, sidecar = document_paths(tmp_repo, "features", "RE-7F3K2Q")
    sidecar.parent.mkdir(parents=True)
    document = make_document()
    write_sidecar(sidecar, document)
    dumped = json.loads(sidecar.read_bytes().decode("utf-8"))
    assert dumped["schema"] == 1
    assert list(dumped) == sorted(dumped)
    assert sidecar.read_bytes().endswith(b"\n")
    assert b"\r" not in sidecar.read_bytes()


# ---------------------------------------------------------------------------
# Bodies (spec §5.2)
# ---------------------------------------------------------------------------


def test_body_round_trip(tmp_repo: Path) -> None:
    body, _ = document_paths(tmp_repo, "features", "RE-7F3K2Q")
    body.parent.mkdir(parents=True)
    text = "# Title\n\nBody text.\n"
    write_body(body, text)
    assert read_body(body) == text


def test_write_body_forces_lf(tmp_repo: Path) -> None:
    body, _ = change_paths(tmp_repo, "RE-1")
    write_body(body, "# T\r\nline\r\n")
    assert body.read_bytes() == b"# T\nline\n"


def test_read_body_normalises_line_endings(tmp_repo: Path) -> None:
    body, _ = term_paths(tmp_repo, "kb")
    body.write_bytes(b"# T\r\na\rb\n")
    assert read_body(body) == "# T\na\nb\n"


def test_read_body_strips_bom(tmp_repo: Path) -> None:
    body, _ = term_paths(tmp_repo, "kb")
    body.write_bytes(b"\xef\xbb\xbf# T\n")
    assert read_body(body) == "# T\n"


def test_read_body_missing_raises(tmp_repo: Path) -> None:
    body, _ = document_paths(tmp_repo, "features", "RE-NOPE")
    with pytest.raises(FileNotFoundError):
        read_body(body)


# ---------------------------------------------------------------------------
# Cache (spec §16.5)
# ---------------------------------------------------------------------------


def test_cache_round_trip(tmp_repo: Path) -> None:
    body, _ = document_paths(tmp_repo, "features", "RE-1")
    body.parent.mkdir(parents=True)
    write_body(body, "# T\n")
    cache = load_cache(tmp_repo)
    cache.files["documents/features/RE-1.md"] = stat_cache_entry(body, "sha256:aa")
    cache.types_seen["feature"] = "requirement"
    cache.templates_seen["feature/v1"] = "sha256:sections"
    write_cache(tmp_repo, cache)
    loaded = load_cache(tmp_repo)
    assert loaded == cache
    assert loaded.schema_ == 1
    assert loaded.tool_version == "0.1.1"


def test_cache_absent_rebuilds_silently(tmp_repo: Path) -> None:
    cache = load_cache(tmp_repo)
    assert cache.files == {}
    assert cache.types_seen == {}
    assert cache.templates_seen == {}
    assert cache.schema_ == 1


def test_cache_rebuild_on_corrupted_file(tmp_repo: Path) -> None:
    path = cache_path(tmp_repo)
    path.parent.mkdir(parents=True)
    path.write_text("{ not json !!!", encoding="utf-8")
    cache = load_cache(tmp_repo)
    assert cache.files == {}
    assert cache.types_seen == {}
    assert cache.templates_seen == {}
    body, _ = change_paths(tmp_repo, "RE-1")
    write_body(body, "# T\n")
    cache.files["changes/RE-1.md"] = stat_cache_entry(body, "sha256:aa")
    write_cache(tmp_repo, cache)
    assert load_cache(tmp_repo).files["changes/RE-1.md"].body_hash == "sha256:aa"


def test_cache_rebuild_on_schema_corruption(tmp_repo: Path) -> None:
    path = cache_path(tmp_repo)
    path.parent.mkdir(parents=True)
    path.write_text('{"schema": 99, "files": "nope"}', encoding="utf-8")
    cache = load_cache(tmp_repo)
    assert cache.files == {}
    assert cache.schema_ == 1


def test_cache_entry_freshness(tmp_repo: Path) -> None:
    body, _ = term_paths(tmp_repo, "kb")
    write_body(body, "# T\n")
    entry = stat_cache_entry(body, "sha256:aa")
    assert entry.size > 0
    assert entry.mtime_ns > 0
    assert cache_entry_is_fresh(entry, body)
    write_body(body, "# T changed\n")
    assert not cache_entry_is_fresh(entry, body)


def test_cache_file_is_canonical_json(tmp_repo: Path) -> None:
    cache = load_cache(tmp_repo)
    write_cache(tmp_repo, cache)
    path = cache_path(tmp_repo)
    assert path.read_bytes() == canonical_json_bytes(cache)
    assert b'"schema"' in path.read_bytes()
