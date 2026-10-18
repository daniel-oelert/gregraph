"""Tests for ``operations.update_body`` (spec §5.2, §5.6, §7.2–§7.3, §14).

Browser editing support: an optional UI replaces a document body through the
core API. The operation guards against lost updates with the body hash the
UI read (``E-BODY-STALE``), normalises line endings and whitespace, syncs the
sidecar title from the H1 exactly like report-mode sync, and never bumps
``version`` or touches ``body_hash``, ``assets`` or ``links`` (those belong to
the commit-time reconcile pass). Refusals raise ``OperationRefused``; missing
H1 and front matter are reported as findings (spec §14), not refused.
"""

from __future__ import annotations

import datetime as dt
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from pydantic import ValidationError

from gregraph.core.hashing import body_hash
from gregraph.core.models import (
    ChangeRequest,
    Document,
    Identity,
    OperationRefused,
    TemplateRef,
    Term,
)
from gregraph.core.operations import set_fields, update_body
from gregraph.core.storage import read_body, read_sidecar, write_body, write_sidecar
from gregraph.core.versioning import scope_hash
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import GitIdentity, SampleGraph

CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=dt.UTC)


def _snapshot(root: Path) -> dict[str, bytes]:
    """Bytes of every file under the repository except Git internals."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def _document_files(sample: SampleGraph, doc_id: str) -> tuple[Path, Path]:
    workspace = Workspace.open(sample.root)
    loaded = workspace.index.documents[doc_id]
    return sample.root / loaded.body, sample.root / loaded.sidecar


def _current_hash(sample: SampleGraph, doc_id: str) -> str:
    body, _ = _document_files(sample, doc_id)
    return body_hash(read_body(body))


def _add_change_request(root: Path, cr_id: str = "RE-CHG-ABCDEF") -> str:
    """Write an open change request under ``changes/`` (spec §9.2)."""
    cr = ChangeRequest(
        schema=1,
        uuid=UUID(int=99),
        id=cr_id,
        title="Change",
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="change-request", version=1),
        version=1,
        body_hash=body_hash("# Change\n"),
        scope_hash=scope_hash([]),
        scope=[],
        introduces=[],
        status="open",
        decisions=[],
        branch=None,
        external_ref=None,
        tags=[],
        extra={},
    )
    write_body(root / "changes" / f"{cr_id}.md", "# Change\n")
    write_sidecar(root / "changes" / f"{cr_id}.json", cr)
    return cr_id


def _add_term(root: Path, slug: str = "knowledge-base") -> str:
    """Write a glossary term under ``glossary/`` (spec §10.2)."""
    term = Term(
        schema=1,
        term="Knowledge base",
        slug=slug,
        aliases=[],
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="term", version=1),
        version=1,
        body_hash=body_hash("# Knowledge base\n"),
        deprecated=None,
    )
    write_body(root / "glossary" / f"{slug}.md", "# Knowledge base\n")
    write_sidecar(root / "glossary" / f"{slug}.json", term)
    return slug


# --------------------------------------------------------------------------
# happy path and lifecycle invariants
# --------------------------------------------------------------------------


def test_update_body_writes_body_and_syncs_title(sample_graph: SampleGraph) -> None:
    """The body is replaced, the H1 syncs to the sidecar, and lifecycle fields
    (version, body_hash, assets, links, identity) stay exactly as they were."""
    doc_id = sample_graph.ids["story"]
    body_path, sidecar_path = _document_files(sample_graph, doc_id)
    before = read_sidecar(sidecar_path, Document)
    text = "# Renamed story\n\n## Story\n\nNew prose.\n"

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text=text,
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert result.id == doc_id
    assert result.body == body_path.relative_to(sample_graph.root)
    assert result.body_hash == body_hash(text)
    assert result.title == "Renamed story"
    assert result.changed is True
    assert result.findings == ()
    assert body_path.read_bytes() == text.encode("utf-8")
    after = read_sidecar(sidecar_path, Document)
    assert after.title == "Renamed story"
    assert after.version == before.version
    assert after.body_hash == before.body_hash
    assert after.assets == before.assets
    assert after.links == before.links
    assert after.model_dump(exclude={"title"}) == before.model_dump(exclude={"title"})


def test_update_body_refuses_stale_base_hash_without_writing(
    sample_graph: SampleGraph,
) -> None:
    """A base hash that no longer matches the working-tree body is refused."""
    doc_id = sample_graph.ids["story"]
    body_path, sidecar_path = _document_files(sample_graph, doc_id)
    before_files = _snapshot(sample_graph.root)

    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text="# Overwrite attempt\n",
            base_hash="sha256:" + "0" * 64,
        )

    finding = raised.value.finding
    assert finding.code == "E-BODY-STALE"
    assert finding.severity == "E"
    assert finding.subject == doc_id
    assert _snapshot(sample_graph.root) == before_files
    assert body_path.is_file() and sidecar_path.is_file()


def test_update_body_normalises_crlf_before_hashing_and_writing(
    sample_graph: SampleGraph,
) -> None:
    """CRLF input is written as LF and hashed on the normalised text (§5.2, §7.3)."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    text = "# CRLF title\r\n\r\n## Story\r\n\r\nLine one.\r\n"

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text=text,
        base_hash=_current_hash(sample_graph, doc_id),
    )

    normalised = "# CRLF title\n\n## Story\n\nLine one.\n"
    assert b"\r" not in body_path.read_bytes()
    assert body_path.read_bytes() == normalised.encode("utf-8")
    assert result.body_hash == body_hash(normalised)
    assert result.title == "CRLF title"


def test_update_body_unchanged_text_is_idempotent(sample_graph: SampleGraph) -> None:
    """Re-saving the same content as LF or CRLF writes nothing."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    current = read_body(body_path)
    before_files = _snapshot(sample_graph.root)

    for variant in (current, current.replace("\n", "\r\n")):
        result = update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text=variant,
            base_hash=_current_hash(sample_graph, doc_id),
        )
        assert result.changed is False
        assert result.body_hash == body_hash(current)
        assert result.findings == ()
        assert _snapshot(sample_graph.root) == before_files


def test_update_body_whitespace_only_edit_is_written_verbatim(
    sample_graph: SampleGraph,
) -> None:
    """Trailing spaces are Markdown hard-break syntax: the edit is written as given
    even though the hash, which normalises whitespace (spec §7.3), is unchanged."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    current = read_body(body_path)
    base = _current_hash(sample_graph, doc_id)
    text = current.replace("\n", "   \n")

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text=text,
        base_hash=base,
    )

    assert result.changed is True
    assert result.body_hash == base
    assert body_path.read_bytes() == text.encode("utf-8")


def test_update_body_preserves_hard_break_and_blank_lines(
    sample_graph: SampleGraph,
) -> None:
    """Hard breaks, runs of blank lines and a missing final newline are kept exactly."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    text = "# Breaks\n\n\n\nLine one  \nLine two\n\n\n\nTrailing without newline"

    update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text=text,
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert body_path.read_bytes() == text.encode("utf-8")


def test_update_body_leaves_sidecar_alone_when_title_unchanged(
    sample_graph: SampleGraph,
) -> None:
    """Prose-only edits keep the sidecar bytes identical (nothing else is written)."""
    doc_id = sample_graph.ids["story"]
    _, sidecar_path = _document_files(sample_graph, doc_id)
    sidecar_before = sidecar_path.read_bytes()
    body_path, _ = _document_files(sample_graph, doc_id)
    title = read_body(body_path).splitlines()[0]

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text=f"{title}\n\nOnly prose changed.\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert result.changed is True
    assert sidecar_path.read_bytes() == sidecar_before


def test_update_body_writes_only_the_requested_body(sample_graph: SampleGraph) -> None:
    """Only the target body changes on disk when the title is unchanged."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    before = _snapshot(sample_graph.root)
    title = read_body(body_path).splitlines()[0]

    update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text=f"{title}\n\nChanged prose.\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    after = _snapshot(sample_graph.root)
    changed = {key for key in before if before[key] != after.get(key)}
    assert changed == {body_path.relative_to(sample_graph.root).as_posix()}
    assert set(after) == set(before)


def test_update_body_preserves_tags_and_extra(sample_graph: SampleGraph) -> None:
    """Other sidecar metadata set through ``set`` survives a title-changing save."""
    doc_id = sample_graph.ids["story"]
    set_fields(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        assignments=["tags=alpha,beta", "extra.owner=team-a"],
    )
    _, sidecar_path = _document_files(sample_graph, doc_id)
    before = read_sidecar(sidecar_path, Document)

    update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text="# Renamed with metadata\n\nBody.\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    after = read_sidecar(sidecar_path, Document)
    assert after.tags == before.tags == ["alpha", "beta"]
    assert after.extra == before.extra == {"owner": "team-a"}
    assert after.title == "Renamed with metadata"
    assert after.version == before.version


def test_update_body_accepts_lowercase_id(sample_graph: SampleGraph) -> None:
    """Input IDs are case-insensitive and normalised (spec §4.5)."""
    doc_id = sample_graph.ids["story"]

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id.lower(),
        text="# Lower-case ID\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert result.id == doc_id


# --------------------------------------------------------------------------
# findings: H1 and front matter (spec §5.2, §5.6, §14)
# --------------------------------------------------------------------------


def test_update_body_missing_h1_reports_and_keeps_title(
    sample_graph: SampleGraph,
) -> None:
    """Without an H1 the body is still saved, E-TITLE-MISSING is reported and the
    sidecar title keeps its previous value (the report-mode sync rule)."""
    doc_id = sample_graph.ids["story"]
    body_path, sidecar_path = _document_files(sample_graph, doc_id)
    previous_title = read_sidecar(sidecar_path, Document).title

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text="Prose without a heading.\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert body_path.read_text(encoding="utf-8") == "Prose without a heading.\n"
    assert result.title is None
    assert result.changed is True
    assert [f.code for f in result.findings] == ["E-TITLE-MISSING"]
    assert result.findings[0].severity == "E"
    assert result.findings[0].subject == doc_id
    assert read_sidecar(sidecar_path, Document).title == previous_title


def test_update_body_empty_input_writes_empty_file(
    sample_graph: SampleGraph,
) -> None:
    """Empty input normalises to a single newline and reports E-TITLE-MISSING."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text="",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert body_path.read_bytes() == b""
    assert result.body_hash == body_hash("")
    assert result.title is None
    assert [f.code for f in result.findings] == ["E-TITLE-MISSING"]


def test_update_body_front_matter_is_reported(sample_graph: SampleGraph) -> None:
    """A body starting with '---' reports E-FRONTMATTER-FORBIDDEN (spec §5.2)."""
    doc_id = sample_graph.ids["story"]

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text="---\ntitle: X\n---\n\n# Title\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    codes = {finding.code for finding in result.findings}
    assert "E-FRONTMATTER-FORBIDDEN" in codes
    assert all(finding.severity == "E" for finding in result.findings)
    assert all(finding.subject == doc_id for finding in result.findings)


def test_update_body_valid_text_has_no_findings(sample_graph: SampleGraph) -> None:
    """A conforming body produces no findings and a synced title."""
    doc_id = sample_graph.ids["story"]

    result = update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text="# Clean\n\nBody.\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert result.findings == ()
    assert result.title == "Clean"


# --------------------------------------------------------------------------
# identifier refusals (spec §4.5, §14: E-ID-UNKNOWN)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["RE-STORY-ZZZZZZ", "not-an-id", "", "  "])
def test_update_body_unknown_or_malformed_id_refused(
    sample_graph: SampleGraph, bad: str
) -> None:
    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=bad,
            text="# X\n",
            base_hash="sha256:" + "0" * 64,
        )
    assert raised.value.finding.code == "E-ID-UNKNOWN"
    assert raised.value.finding.severity == "E"


def test_update_body_change_request_id_refused(sample_graph: SampleGraph) -> None:
    """A change request is not a document; its body is not editable here."""
    cr_id = _add_change_request(sample_graph.root)
    before = _snapshot(sample_graph.root)

    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=cr_id,
            text="# Hijack\n",
            base_hash=body_hash("# Change\n"),
        )

    assert raised.value.finding.code == "E-ID-UNKNOWN"
    assert _snapshot(sample_graph.root) == before


def test_update_body_glossary_term_refused(sample_graph: SampleGraph) -> None:
    """A glossary slug is not a document ID (spec §10) and is refused."""
    slug = _add_term(sample_graph.root)
    before = _snapshot(sample_graph.root)

    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=slug,
            text="# Hijack\n",
            base_hash=body_hash("# Knowledge base\n"),
        )

    assert raised.value.finding.code == "E-ID-UNKNOWN"
    assert _snapshot(sample_graph.root) == before


def test_update_body_keeps_created_by(
    sample_graph: SampleGraph, identity: GitIdentity
) -> None:
    """``created_by`` (Git identity, §5.4) is never rewritten on body saves.

    Requires a Git repository (the ``identity`` fixture skips without one).
    """
    doc_id = sample_graph.ids["story"]
    _, sidecar_path = _document_files(sample_graph, doc_id)
    document = read_sidecar(sidecar_path, Document)
    document.created_by = Identity(name=identity.name, email=identity.email)
    write_sidecar(sidecar_path, document)

    update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text="# Identity kept\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert read_sidecar(sidecar_path, Document).created_by == document.created_by


# --------------------------------------------------------------------------
# unsafe paths: symlinks never redirect a write (spec §3, §14: E-PATH-UNSAFE)
# --------------------------------------------------------------------------


def _symlink(link: Path, target: Path, *, is_dir: bool = False) -> None:
    """Create a symbolic link or skip when the platform forbids it (no privilege)."""
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symbolic links unavailable on this platform: {exc}")


def _outside_copy(
    tmp_path_factory: pytest.TempPathFactory, name: str, content: bytes
) -> Path:
    path = tmp_path_factory.mktemp("outside") / name
    path.write_bytes(content)
    return path


def test_update_body_external_body_symlink_refused(
    sample_graph: SampleGraph, tmp_path_factory: pytest.TempPathFactory
) -> None:
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    original = body_path.read_bytes()
    outside = _outside_copy(tmp_path_factory, "body.md", original)
    body_path.unlink()
    _symlink(body_path, outside)
    before_repo = _snapshot(sample_graph.root)
    before_outside = [outside.read_bytes()]

    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text="# Redirected title\n\nWritten elsewhere.\n",
            base_hash=body_hash(original.decode("utf-8")),
        )

    assert raised.value.finding.code == "E-PATH-UNSAFE"
    assert raised.value.finding.severity == "E"
    assert _snapshot(sample_graph.root) == before_repo
    assert [outside.read_bytes()] == before_outside


def test_update_body_external_sidecar_symlink_blocks_body_write(
    sample_graph: SampleGraph, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """An unsafe sidecar blocks the body write too, so the pair cannot diverge."""
    doc_id = sample_graph.ids["story"]
    body_path, sidecar_path = _document_files(sample_graph, doc_id)
    original_sidecar = sidecar_path.read_bytes()
    outside = _outside_copy(tmp_path_factory, "sidecar.json", original_sidecar)
    sidecar_path.unlink()
    _symlink(sidecar_path, outside)
    body_before = body_path.read_bytes()
    before_repo = _snapshot(sample_graph.root)
    before_outside = outside.read_bytes()

    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text="# Title change that needs the sidecar\n\nBody.\n",
            base_hash=_current_hash(sample_graph, doc_id),
        )

    assert raised.value.finding.code == "E-PATH-UNSAFE"
    assert body_path.read_bytes() == body_before
    assert _snapshot(sample_graph.root) == before_repo
    assert outside.read_bytes() == before_outside


def test_update_body_symlinked_body_inside_repo_refused(
    sample_graph: SampleGraph,
) -> None:
    """A link pointing inside the repository is still refused (no alias writes)."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    target = body_path.with_name("alias-target.md")
    target.write_bytes(body_path.read_bytes())
    body_path.unlink()
    _symlink(body_path, target)
    before_repo = _snapshot(sample_graph.root)

    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text="# Alias\n",
            base_hash=body_hash(target.read_text(encoding="utf-8")),
        )

    assert raised.value.finding.code == "E-PATH-UNSAFE"
    assert _snapshot(sample_graph.root) == before_repo


def test_update_body_directory_symlink_after_index_refused(
    sample_graph: SampleGraph, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A workspace opened before its folder became a link is refused on save.

    Fresh indexes never reach documents through a linked folder (directory walks
    do not descend into links), so the race is: index loaded, then the folder is
    swapped for a link to a folder outside the repository.
    """
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    folder = body_path.parent
    workspace = Workspace.open(sample_graph.root)
    assert doc_id in workspace.index.documents  # force the lazy index load first
    base = _current_hash(sample_graph, doc_id)
    outside_dir = tmp_path_factory.mktemp("outside-folder")
    for entry in folder.iterdir():
        (outside_dir / entry.name).write_bytes(entry.read_bytes())
    for entry in list(folder.iterdir()):
        entry.unlink()
    folder.rmdir()
    _symlink(folder, outside_dir, is_dir=True)
    before_outside = {p.name: p.read_bytes() for p in outside_dir.iterdir()}

    with pytest.raises(OperationRefused) as raised:
        update_body(
            workspace, doc_id=doc_id, text="# Via folder link\n", base_hash=base
        )

    assert raised.value.finding.code == "E-PATH-UNSAFE"
    assert {p.name: p.read_bytes() for p in outside_dir.iterdir()} == before_outside


# --------------------------------------------------------------------------
# atomic body replacement, stale detection and missing bodies (design §21.5)
# --------------------------------------------------------------------------


def _folder_listing(folder: Path) -> list[str]:
    return sorted(entry.name for entry in folder.iterdir())


def test_update_body_failed_replace_leaves_original_and_no_leftovers(
    sample_graph: SampleGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the final rename fails, the old body survives untouched and no temporary
    file is left beside it (the temporary never has a managed suffix)."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    original = body_path.read_bytes()
    folder_before = _folder_listing(body_path.parent)
    snapshot_before = _snapshot(sample_graph.root)

    def failing_replace(source: object, target: object) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr("gregraph.core.storage.os.replace", failing_replace)
    with pytest.raises(OSError, match="simulated rename failure"):
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text="# Replaced\n\nNew prose.\n",
            base_hash=_current_hash(sample_graph, doc_id),
        )

    assert body_path.read_bytes() == original
    assert _folder_listing(body_path.parent) == folder_before
    assert not list(body_path.parent.glob("*.tmp"))
    assert _snapshot(sample_graph.root) == snapshot_before


def test_update_body_failed_write_cleans_temporary(
    sample_graph: SampleGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure while the temporary file is being flushed removes it; the body
    keeps its previous bytes."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    original = body_path.read_bytes()
    folder_before = _folder_listing(body_path.parent)

    def failing_fsync(fd: int) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("gregraph.core.storage.os.fsync", failing_fsync)
    with pytest.raises(OSError, match="simulated disk failure"):
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text="# Replaced\n\nNew prose.\n",
            base_hash=_current_hash(sample_graph, doc_id),
        )

    assert body_path.read_bytes() == original
    assert _folder_listing(body_path.parent) == folder_before


def test_update_body_same_length_external_change_with_restored_mtime_is_stale(
    sample_graph: SampleGraph,
) -> None:
    """An external edit of the same byte length whose mtime is put back is still
    detected: the comparison is by content hash, not by timestamps."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    editor_base = _current_hash(sample_graph, doc_id)
    stat = body_path.stat()
    raw = body_path.read_bytes()
    index = raw.index(b"a")
    external = raw[:index] + b"b" + raw[index + 1 :]
    assert len(external) == len(raw)
    body_path.write_bytes(external)
    os.utime(body_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert body_path.stat().st_mtime_ns == stat.st_mtime_ns

    with pytest.raises(OperationRefused) as raised:
        update_body(
            Workspace.open(sample_graph.root),
            doc_id=doc_id,
            text="# Stale save\n",
            base_hash=editor_base,
        )

    assert raised.value.finding.code == "E-BODY-STALE"
    assert body_path.read_bytes() == external


def test_update_body_missing_body_is_refused_and_not_recreated(
    sample_graph: SampleGraph,
) -> None:
    """A body removed after the index was loaded is refused and never recreated."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    workspace = Workspace.open(sample_graph.root)
    assert doc_id in workspace.index.documents
    base = _current_hash(sample_graph, doc_id)
    body_path.unlink()
    folder_before = _folder_listing(body_path.parent)

    with pytest.raises(OperationRefused) as raised:
        update_body(workspace, doc_id=doc_id, text="# Recreated?\n", base_hash=base)

    assert raised.value.finding.code == "E-BODY-MISSING"
    assert not body_path.exists()
    assert _folder_listing(body_path.parent) == folder_before


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX-only")
def test_update_body_preserves_file_mode(sample_graph: SampleGraph) -> None:
    """The atomic replacement keeps the body's permission bits."""
    doc_id = sample_graph.ids["story"]
    body_path, _ = _document_files(sample_graph, doc_id)
    body_path.chmod(0o640)

    update_body(
        Workspace.open(sample_graph.root),
        doc_id=doc_id,
        text="# Mode kept\n\nBody.\n",
        base_hash=_current_hash(sample_graph, doc_id),
    )

    assert stat.S_IMODE(body_path.stat().st_mode) == 0o640


# --------------------------------------------------------------------------
# sidecar validated before the body is written (design §21.5)
# --------------------------------------------------------------------------


def test_update_body_sidecar_deleted_after_index_load_writes_nothing(
    sample_graph: SampleGraph,
) -> None:
    """A sidecar removed after the index was loaded fails the save before the body is
    written, and the save is never reported as partially applied."""
    doc_id = sample_graph.ids["story"]
    body_path, sidecar_path = _document_files(sample_graph, doc_id)
    workspace = Workspace.open(sample_graph.root)
    assert doc_id in workspace.index.documents  # force the lazy index load first
    base = _current_hash(sample_graph, doc_id)
    body_before = body_path.read_bytes()
    sidecar_path.unlink()
    before_repo = _snapshot(sample_graph.root)

    with pytest.raises(FileNotFoundError):
        update_body(
            workspace,
            doc_id=doc_id,
            text="# Title that needs the sidecar\n\nNew prose.\n",
            base_hash=base,
        )

    assert body_path.read_bytes() == body_before
    assert not sidecar_path.exists()
    assert _snapshot(sample_graph.root) == before_repo


def test_update_body_corrupt_sidecar_after_index_load_writes_nothing(
    sample_graph: SampleGraph,
) -> None:
    """A sidecar corrupted after the index was loaded is rejected before the body is
    written; both files keep their bytes."""
    doc_id = sample_graph.ids["story"]
    body_path, sidecar_path = _document_files(sample_graph, doc_id)
    workspace = Workspace.open(sample_graph.root)
    assert doc_id in workspace.index.documents
    base = _current_hash(sample_graph, doc_id)
    body_before = body_path.read_bytes()
    sidecar_path.write_bytes(b"{ not json")
    sidecar_before = sidecar_path.read_bytes()
    before_repo = _snapshot(sample_graph.root)

    with pytest.raises(ValidationError):
        update_body(
            workspace,
            doc_id=doc_id,
            text="# Title that needs the sidecar\n\nNew prose.\n",
            base_hash=base,
        )

    assert body_path.read_bytes() == body_before
    assert sidecar_path.read_bytes() == sidecar_before
    assert _snapshot(sample_graph.root) == before_repo
