"""Tests for the S15 operations: templates, migrate, baselines, repair.

Spec §7.7 (migration execution on top of S5's pure planner), §13.16–13.17
(``migrate``, ``template``), §12.4/§13.21 (baselines as annotated tags with a
manifest message), §12.6/§13.19 (``repair versions``, ``repair cache``) and
§4.4 (``repair regenerate-id`` on an ``E-ID-DUPLICATE`` pair).

M4 acceptance: additive migration bumps the version on the next commit
(simulated with S9's ``reconcile``), renamed migration rewrites headings, and
breaking migration takes the supersede path with
``## Unmapped content (migration)`` and a manual-attention report.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from gregraph.core.config import Config, write_config
from gregraph.core.git import GitAdapter
from gregraph.core.hashing import body_hash
from gregraph.core.ids import decode_body, is_derivable_from, split_id
from gregraph.core.models import Document, Link, OperationRefused, TemplateRef
from gregraph.core.operations import (
    baseline_create,
    baseline_list,
    migrate,
    repair_cache,
    repair_regenerate_id,
    repair_versions,
    template_add,
    template_bump,
    template_list,
    template_show,
)
from gregraph.core.storage import (
    CacheIndex,
    config_path,
    read_sidecar,
    write_body,
    write_sidecar,
)
from gregraph.core.templates import load_template_dir
from gregraph.core.versioning import reconcile
from gregraph.core.workspace import Workspace

CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=dt.UTC)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


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


def _write_layout(root: Path) -> None:
    write_config(config_path(root), Config())
    (root / ".gregraph" / "templates").mkdir(parents=True, exist_ok=True)
    for name in ("documents", "changes", "glossary", "assets"):
        (root / name).mkdir(exist_ok=True)
    (root / ".gitignore").write_text(".gregraph/cache/\n", encoding="utf-8")


def _init_repo(root: Path) -> Path:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Test Author")
    _git(root, "config", "user.email", "test.author@example.org")
    _write_layout(root)
    _commit_all(root, "init")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Git repository on ``main`` with the spec §3 layout and an init commit."""
    return _init_repo(tmp_path)


def _workspace(root: Path, *, git: bool = True) -> Workspace:
    return Workspace.open(root, git=GitAdapter(root) if git else None)


def _write_template(
    root: Path,
    name: str,
    version: int,
    *,
    sections: list[tuple[str, bool, str]] | None = None,
    breaking: bool = False,
    deprecated: bool = False,
    renamed: dict[str, list[str]] | None = None,
) -> None:
    """Write one template version into the repository (spec §5.5)."""
    directory = root / ".gregraph" / "templates" / name / f"v{version}"
    directory.mkdir(parents=True, exist_ok=True)
    if sections is None:
        sections = [("Summary", True, "Write a summary.")]
    renamed = renamed or {}
    descriptor = {
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
    (directory / "template.json").write_text(
        json.dumps(descriptor, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# {{ title }}", ""]
    for heading, _required, placeholder in sections:
        lines.append(f"## {heading}")
        lines.append(f"*{placeholder}*")
        lines.append("")
    (directory / "template.md").write_text("\n".join(lines), encoding="utf-8")


def _uuid_for(doc_id: str) -> UUID:
    """Deterministic UUID whose §4.1 derivation is ``doc_id``."""
    parts = split_id(doc_id)
    assert parts is not None
    return UUID(int=decode_body(parts.body) << 98)


def _write_doc(
    root: Path,
    doc_id: str,
    *,
    title: str = "Sample",
    body: str | None = None,
    template: tuple[str, int] = ("user-story", 1),
    folder: str = "user-story",
    links: tuple[tuple[str, str], ...] = (),
    doc_type: str = "user-story",
    doc_uuid: UUID | None = None,
) -> Path:
    """Write one document pair directly (repo-relative sidecar path returned)."""
    if body is None:
        body = f"# {title}\n\n## Summary\nFilled in.\n"
    document = Document(
        schema=1,
        uuid=doc_uuid if doc_uuid is not None else _uuid_for(doc_id),
        id=doc_id,
        type=doc_type,
        title=title,
        created=CREATED,
        created_by=None,
        template=TemplateRef(name=template[0], version=template[1]),
        version=1,
        body_hash=body_hash(body),
        assets=[],
        links=[
            Link(type=link_type, target=target, target_version=1)
            for link_type, target in links
        ],
        deprecated=None,
        tags=[],
        extra={},
    )
    body_rel = Path("documents") / folder / f"{doc_id}.md"
    sidecar_rel = Path("documents") / folder / f"{doc_id}.json"
    write_body(root / body_rel, body)
    write_sidecar(root / sidecar_rel, document)
    return sidecar_rel


def _read_doc(root: Path, sidecar_rel: Path) -> Document:
    return read_sidecar(root / sidecar_rel, Document)


def _read_body(root: Path, body_rel: Path) -> str:
    return (root / body_rel).read_text(encoding="utf-8")


def _simulate_commit_bump(root: Path, sidecar_rel: Path) -> Document:
    """What the pre-commit hook does to a staged document (spec §7.5)."""
    document = _read_doc(root, sidecar_rel)
    body = _read_body(root, sidecar_rel.with_suffix(".md"))
    reconcile([(document, body)], mode="bump")
    write_sidecar(root / sidecar_rel, document)
    return document


# --------------------------------------------------------------------------
# template list / add / bump / show (spec §13.17)
# --------------------------------------------------------------------------


def test_template_list_reports_versions_and_counts(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_template(tmp_repo, "user-story", 2, deprecated=True)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    _write_doc(tmp_repo, "RE-STORY-BBBBBB", template=("user-story", 1))
    _write_doc(tmp_repo, "RE-STORY-CCCCCC", template=("user-story", 2))
    result = template_list(_workspace(tmp_repo, git=False))
    assert [t.name for t in result.templates] == ["user-story"]
    versions = result.templates[0].versions
    assert [(v.version, v.deprecated, v.document_count) for v in versions] == [
        (1, False, 2),
        (2, True, 1),
    ]


def test_template_add_copies_builtin_as_v1(tmp_repo: Path) -> None:
    result = template_add(_workspace(tmp_repo, git=False), "user-story")
    assert result.name == "user-story"
    assert result.version == 1
    directory = tmp_repo / ".gregraph" / "templates" / "user-story" / "v1"
    assert (directory / "template.json").is_file()
    assert (directory / "template.md").is_file()
    loaded = load_template_dir(tmp_repo / ".gregraph" / "templates")["user-story"]
    assert [t.version for t in loaded] == [1]
    assert loaded[0].descriptor.name == "user-story"


def test_template_add_existing_name_gets_next_version(tmp_repo: Path) -> None:
    template_add(_workspace(tmp_repo, git=False), "user-story")
    result = template_add(_workspace(tmp_repo, git=False), "user-story")
    assert result.version == 2
    loaded = load_template_dir(tmp_repo / ".gregraph" / "templates")["user-story"]
    assert [t.version for t in loaded] == [1, 2]
    assert loaded[1].descriptor.version == 2


def test_template_add_unknown_builtin_refused(tmp_repo: Path) -> None:
    with pytest.raises(OperationRefused) as excinfo:
        template_add(_workspace(tmp_repo, git=False), "nope")
    assert excinfo.value.finding.code == "E-TEMPLATE-UNKNOWN"


def test_template_bump_copies_latest_version(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    result = template_bump(_workspace(tmp_repo, git=False), "user-story")
    assert result.version == 2
    loaded = load_template_dir(tmp_repo / ".gregraph" / "templates")["user-story"]
    assert [t.version for t in loaded] == [1, 2]
    assert loaded[1].descriptor.version == 2
    assert loaded[1].descriptor.breaking is False
    assert loaded[1].descriptor.sections == loaded[0].descriptor.sections


def test_template_bump_breaking_flag(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    result = template_bump(_workspace(tmp_repo, git=False), "user-story", breaking=True)
    assert result.breaking is True
    loaded = load_template_dir(tmp_repo / ".gregraph" / "templates")["user-story"]
    assert loaded[1].descriptor.breaking is True


def test_template_bump_unknown_refused(tmp_repo: Path) -> None:
    with pytest.raises(OperationRefused) as excinfo:
        template_bump(_workspace(tmp_repo, git=False), "ghost")
    assert excinfo.value.finding.code == "E-TEMPLATE-UNKNOWN"


def test_template_show_returns_descriptor_and_skeleton(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_template(tmp_repo, "user-story", 2)
    result = template_show(_workspace(tmp_repo, git=False), "user-story")
    assert result.descriptor.version == 2
    assert "## Summary" in result.skeleton
    pinned = template_show(_workspace(tmp_repo, git=False), "user-story", version=1)
    assert pinned.descriptor.version == 1


def test_template_show_unknown_refused(tmp_repo: Path) -> None:
    with pytest.raises(OperationRefused) as excinfo:
        template_show(_workspace(tmp_repo, git=False), "ghost")
    assert excinfo.value.finding.code == "E-TEMPLATE-UNKNOWN"


# --------------------------------------------------------------------------
# migrate — selection (spec §13.16, §7.7)
# --------------------------------------------------------------------------


def test_migrate_requires_a_selection(tmp_repo: Path) -> None:
    with pytest.raises(ValueError):
        migrate(_workspace(tmp_repo, git=False))


def test_migrate_rejects_conflicting_selection(tmp_repo: Path) -> None:
    with pytest.raises(ValueError):
        migrate(
            _workspace(tmp_repo, git=False),
            doc_ids=["RE-STORY-AAAAAA"],
            select_all=True,
        )


def test_migrate_unknown_id_refused(tmp_repo: Path) -> None:
    with pytest.raises(OperationRefused) as excinfo:
        migrate(_workspace(tmp_repo, git=False), doc_ids=["RE-STORY-ZZZZZZ"])
    assert excinfo.value.finding.code == "E-ID-UNKNOWN"


def test_migrate_selects_all_and_template(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_template(tmp_repo, "user-story", 2)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    _write_doc(tmp_repo, "RE-STORY-BBBBBB", template=("user-story", 1))
    result = migrate(_workspace(tmp_repo, git=False), select_all=True)
    assert sorted(item.id for item in result.items) == [
        "RE-STORY-AAAAAA",
        "RE-STORY-BBBBBB",
    ]
    result = migrate(_workspace(tmp_repo, git=False), template="user-story")
    assert len(result.items) == 2
    result = migrate(_workspace(tmp_repo, git=False), template="ghost")
    assert result.items == ()
    result = migrate(_workspace(tmp_repo, git=False), doc_ids=["RE-STORY-AAAAAA"])
    assert [item.id for item in result.items] == ["RE-STORY-AAAAAA"]


def test_migrate_up_to_date_is_skipped(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    result = migrate(_workspace(tmp_repo, git=False), select_all=True)
    assert result.items[0].kind == "skipped"


# --------------------------------------------------------------------------
# migrate — M4 acceptance scenarios (spec §7.7)
# --------------------------------------------------------------------------


def test_migrate_additive_in_place_bumps_on_next_commit(tmp_repo: Path) -> None:
    """M4: additive → in-place; the next commit bumps ``version`` (spec §7.7)."""
    _write_template(tmp_repo, "user-story", 1)
    _write_template(
        tmp_repo,
        "user-story",
        2,
        sections=[
            ("Summary", True, "Write a summary."),
            ("Outlook", False, "Look ahead."),
        ],
    )
    sidecar_rel = _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    ws = _workspace(tmp_repo, git=False)
    result = migrate(ws, doc_ids=["RE-STORY-AAAAAA"])
    item = result.items[0]
    assert item.kind == "in-place"
    assert item.inserted == ("Outlook",)
    body = _read_body(tmp_repo, Path("documents/user-story/RE-STORY-AAAAAA.md"))
    assert "## Outlook" in body
    assert "*Look ahead.*" in body
    document = _read_doc(tmp_repo, sidecar_rel)
    assert document.template == TemplateRef(name="user-story", version=2)
    assert document.version == 1
    bumped = _simulate_commit_bump(tmp_repo, sidecar_rel)
    assert bumped.version == 2


def test_migrate_renamed_headings(tmp_repo: Path) -> None:
    """M4: renamed → headings renamed via ``renamed_from`` (spec §5.5, §7.7)."""
    _write_template(
        tmp_repo,
        "user-story",
        1,
        sections=[
            ("Summary", True, "Write a summary."),
            ("Motivation", False, "Why?"),
        ],
    )
    _write_template(
        tmp_repo,
        "user-story",
        2,
        sections=[
            ("Summary", True, "Write a summary."),
            (
                "Rationale",
                False,
                "Why?",
            ),
        ],
        renamed={"Rationale": ["Motivation"]},
    )
    _write_doc(
        tmp_repo,
        "RE-STORY-AAAAAA",
        template=("user-story", 1),
        body="# Sample\n\n## Summary\nDone.\n\n## Motivation\nBecause.\n",
    )
    result = migrate(_workspace(tmp_repo, git=False), doc_ids=["RE-STORY-AAAAAA"])
    item = result.items[0]
    assert item.kind == "in-place"
    assert item.renamed == (("Motivation", "Rationale"),)
    body = _read_body(tmp_repo, Path("documents/user-story/RE-STORY-AAAAAA.md"))
    assert "## Rationale" in body
    assert "## Motivation" not in body
    assert "Because." in body


def test_migrate_breaking_takes_supersede_path(tmp_repo: Path) -> None:
    """M4: breaking → superseding migration (spec §7.7)."""
    _write_template(tmp_repo, "user-story", 1)
    _write_template(
        tmp_repo,
        "user-story",
        2,
        breaking=True,
        sections=[
            ("Summary", True, "Write a summary."),
            ("Outlook", False, "Look ahead."),
        ],
    )
    old_rel = _write_doc(
        tmp_repo,
        "RE-STORY-AAAAAA",
        template=("user-story", 1),
        body="# Sample\n\n## Summary\nDone.\n\n## Custom\nExtra content.\n",
    )
    ws = _workspace(tmp_repo, git=False)
    result = migrate(ws, doc_ids=["RE-STORY-AAAAAA"])
    item = result.items[0]
    assert item.kind == "superseding"
    assert item.new_id is not None
    assert item.unmapped == ("Custom",)
    assert any("breaking" in note for note in item.manual_attention)
    old = _read_doc(tmp_repo, old_rel)
    assert old.template == TemplateRef(name="user-story", version=1)
    new_rel = Path("documents/user-story") / f"{item.new_id}.json"
    new = _read_doc(tmp_repo, new_rel)
    assert new.template == TemplateRef(name="user-story", version=2)
    assert any(
        link.type == "supersedes" and link.target == "RE-STORY-AAAAAA"
        for link in new.links
    )
    body = _read_body(tmp_repo, new_rel.with_suffix(".md"))
    assert "## Unmapped content (migration)" in body
    assert "Extra content." in body
    assert "## Summary" in body


def test_migrate_supersede_flag_forces_superseding(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_template(tmp_repo, "user-story", 2)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    result = migrate(
        _workspace(tmp_repo, git=False), doc_ids=["RE-STORY-AAAAAA"], supersede=True
    )
    assert result.items[0].kind == "superseding"
    assert result.items[0].new_id is not None


def test_migrate_dry_run_writes_nothing(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_template(
        tmp_repo,
        "user-story",
        2,
        breaking=True,
        sections=[
            ("Summary", True, "Write a summary."),
            ("Outlook", False, "Look ahead."),
        ],
    )
    sidecar_rel = _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    before = sorted(p.name for p in (tmp_repo / "documents").rglob("*"))
    result = migrate(_workspace(tmp_repo, git=False), select_all=True, dry_run=True)
    assert result.dry_run is True
    assert result.items[0].kind == "superseding"
    assert result.items[0].new_id is None
    assert sorted(p.name for p in (tmp_repo / "documents").rglob("*")) == before
    assert _read_doc(tmp_repo, sidecar_rel).template.version == 1


def test_migrate_to_explicit_version(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_template(tmp_repo, "user-story", 2)
    _write_template(tmp_repo, "user-story", 3)
    sidecar_rel = _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    result = migrate(
        _workspace(tmp_repo, git=False), doc_ids=["RE-STORY-AAAAAA"], to_version=2
    )
    assert result.items[0].to_version == 2
    assert _read_doc(tmp_repo, sidecar_rel).template.version == 2


def test_migrate_missing_target_version_skipped(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA", template=("user-story", 1))
    result = migrate(
        _workspace(tmp_repo, git=False), doc_ids=["RE-STORY-AAAAAA"], to_version=9
    )
    assert result.items[0].kind == "skipped"


# --------------------------------------------------------------------------
# baseline create / list (spec §12.4, §13.21)
# --------------------------------------------------------------------------


def test_baseline_create_writes_manifest_tag_and_list_sees_it(repo: Path) -> None:
    """M4: the tag message contains the manifest; ``baseline list`` sees it."""
    _write_template(repo, "user-story", 1)
    first = _write_doc(repo, "RE-STORY-AAAAAA", title="First")
    second = _write_doc(repo, "RE-STORY-BBBBBB", title="Second")
    _commit_all(repo, "add docs")
    ws = _workspace(repo)
    result = baseline_create(ws, "base-1", message="Release 1")
    assert result.tag == "baseline/base-1"
    message = _git(repo, "cat-file", "-p", "refs/tags/baseline/base-1").stdout
    assert "Release 1" in message
    manifest = json.loads(
        re.search(r"\{.*\}", message, re.DOTALL).group(0)  # type: ignore[union-attr]
    )
    assert manifest["schema"] == 1
    assert manifest["id_prefix"] == "RE"
    assert manifest["tool_version"]
    entries = {entry["id"]: entry for entry in manifest["documents"]}
    assert set(entries) == {"RE-STORY-AAAAAA", "RE-STORY-BBBBBB"}
    assert entries["RE-STORY-AAAAAA"]["version"] == 1
    assert entries["RE-STORY-AAAAAA"]["body_hash"] == body_hash(
        _read_body(repo, first.with_suffix(".md"))
    )
    assert entries["RE-STORY-AAAAAA"]["status"] in {"draft", "active", "unknown"}
    assert entries["RE-STORY-BBBBBB"]["status"] in {"draft", "active", "unknown"}
    assert second.stem == "RE-STORY-BBBBBB"
    listing = baseline_list(_workspace(repo))
    assert "baseline/base-1" in listing.tags


def test_baseline_create_refuses_uncommitted_managed_files(repo: Path) -> None:
    _write_template(repo, "user-story", 1)
    _write_doc(repo, "RE-STORY-AAAAAA")
    _commit_all(repo, "add doc")
    body = repo / "documents" / "user-story" / "RE-STORY-AAAAAA.md"
    write_body(body, "# Sample\n\n## Summary\nEdited but uncommitted.\n")
    with pytest.raises(OperationRefused) as excinfo:
        baseline_create(_workspace(repo), "base-1")
    assert excinfo.value.finding.code == "E-BASELINE-UNCOMMITTED"


def test_baseline_create_refuses_validation_errors(repo: Path) -> None:
    _write_template(repo, "user-story", 1)
    _write_doc(
        repo,
        "RE-STORY-AAAAAA",
        body="# Sample\n\n## Summary\n*Write a summary.*\n",
    )
    _commit_all(repo, "add doc with empty required section")
    with pytest.raises(OperationRefused) as excinfo:
        baseline_create(_workspace(repo), "base-1")
    assert excinfo.value.finding.code == "E-BASELINE-INVALID"


def test_baseline_create_refuses_duplicate_tag(repo: Path) -> None:
    _write_template(repo, "user-story", 1)
    _write_doc(repo, "RE-STORY-AAAAAA")
    _commit_all(repo, "add doc")
    baseline_create(_workspace(repo), "base-1")
    with pytest.raises(OperationRefused) as excinfo:
        baseline_create(_workspace(repo), "base-1")
    assert excinfo.value.finding.code == "E-BASELINE-EXISTS"


def test_baseline_create_requires_git(tmp_repo: Path) -> None:
    if (tmp_repo / ".git").exists():
        pytest.skip("needs a repository without git")
    _write_template(tmp_repo, "user-story", 1)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA")
    with pytest.raises(OperationRefused) as excinfo:
        baseline_create(_workspace(tmp_repo, git=False), "base-1")
    assert excinfo.value.finding.code == "E-GIT-UNAVAILABLE"


def test_baseline_create_rejects_bad_name(repo: Path) -> None:
    with pytest.raises(ValueError):
        baseline_create(_workspace(repo), "bad name")


def test_baseline_list_empty_without_tags(repo: Path) -> None:
    assert baseline_list(_workspace(repo)).tags == ()


# --------------------------------------------------------------------------
# repair versions (spec §7.2, §12.6, §13.19)
# --------------------------------------------------------------------------


def test_repairs_conflicted_sidecar(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    sidecar_rel = _write_doc(
        tmp_repo, "RE-STORY-AAAAAA", links=(("refines", "RE-STORY-BBBBBB"),)
    )
    _write_doc(tmp_repo, "RE-STORY-BBBBBB")
    raw = (tmp_repo / "documents" / "user-story" / "RE-STORY-AAAAAA.json").read_text(
        encoding="utf-8"
    )
    conflicted = raw.replace(
        '\n  "version": 1',
        '\n  <<<<<<< ours\n  "version": 3\n  =======\n  "version": 7\n  >>>>>>> theirs',
        1,
    )
    assert conflicted != raw
    (tmp_repo / "documents" / "user-story" / "RE-STORY-AAAAAA.json").write_text(
        conflicted, encoding="utf-8"
    )
    result = repair_versions(_workspace(tmp_repo, git=False))
    assert len(result.repaired) == 1
    repaired = result.repaired[0]
    assert repaired.version == 8
    assert set(repaired.versions_seen) == {3, 7}
    document = _read_doc(tmp_repo, sidecar_rel)
    assert document.version == 8
    assert document.body_hash == body_hash(
        _read_body(tmp_repo, sidecar_rel.with_suffix(".md"))
    )


def test_repair_versions_reports_clean_repo(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA")
    result = repair_versions(_workspace(tmp_repo, git=False))
    assert result.repaired == ()
    assert result.notices


# --------------------------------------------------------------------------
# repair regenerate-id (spec §4.4, §13.19)
# --------------------------------------------------------------------------


def _duplicate_fixture(root: Path) -> None:
    """Synthesised ``E-ID-DUPLICATE`` pair plus an inbound link and a mention."""
    _write_doc(root, "RE-STORY-7F3K2Q", folder="keep", title="Kept")
    _write_doc(
        root,
        "RE-STORY-7F3K2Q",
        folder="move",
        title="Moved",
        doc_uuid=UUID(int=0x2222 << 98),
    )
    _write_doc(
        root,
        "RE-STORY-2K7QMB",
        folder="other",
        title="Linking",
        body="# Linking\n\nSee [[RE-STORY-7F3K2Q]] for details.\n",
        links=(("refines", "RE-STORY-7F3K2Q"),),
    )


def test_regenerate_id_resolves_duplicate_and_rewrites_links(repo: Path) -> None:
    """M4: regenerate-id on a synthesised ``E-ID-DUPLICATE`` fixture (§4.4)."""
    _duplicate_fixture(repo)
    _commit_all(repo, "duplicate pair")
    before = _workspace(repo).index.findings
    assert any(finding.code == "E-ID-DUPLICATE" for finding in before)
    ws = _workspace(repo)
    result = repair_regenerate_id(ws, Path("documents/move/RE-STORY-7F3K2Q.json"))
    assert result.old_id == "RE-STORY-7F3K2Q"
    assert result.new_id != "RE-STORY-7F3K2Q"
    assert is_derivable_from(result.new_id, result.uuid, "RE", "STORY")
    new_sidecar = repo / "documents" / "move" / f"{result.new_id}.json"
    assert new_sidecar.is_file()
    assert not (repo / "documents" / "move" / "RE-STORY-7F3K2Q.json").exists()
    moved = read_sidecar(new_sidecar, Document)
    assert moved.id == result.new_id
    assert moved.uuid == result.uuid
    assert (repo / "documents" / "move" / f"{result.new_id}.md").is_file()
    kept = _read_doc(repo, Path("documents/keep/RE-STORY-7F3K2Q.json"))
    assert kept.id == "RE-STORY-7F3K2Q"
    linking = _read_doc(repo, Path("documents/other/RE-STORY-2K7QMB.json"))
    assert [link.target for link in linking.links] == [result.new_id]
    assert result.rewritten
    assert result.rewritten[0].old_target == "RE-STORY-7F3K2Q"
    assert any("RE-STORY-7F3K2Q" in entry for entry in result.manual)
    assert any("RE-STORY-7F3K2Q" in notice for notice in result.notices)
    findings = _workspace(repo).index.findings
    assert not any(finding.code == "E-ID-DUPLICATE" for finding in findings)


def test_regenerate_id_lists_untracked_links_for_manual(repo: Path) -> None:
    _duplicate_fixture(repo)
    _commit_all(repo, "duplicate pair")
    _write_doc(
        repo,
        "RE-STORY-3M4N5P",
        folder="other",
        title="Fresh",
        links=(("refines", "RE-STORY-7F3K2Q"),),
    )
    result = repair_regenerate_id(
        _workspace(repo), Path("documents/move/RE-STORY-7F3K2Q.md")
    )
    fresh = _read_doc(repo, Path("documents/other/RE-STORY-3M4N5P.json"))
    assert [link.target for link in fresh.links] == ["RE-STORY-7F3K2Q"]
    assert any("RE-STORY-3M4N5P" in entry for entry in result.manual)
    assert all(rewritten.source != "RE-STORY-3M4N5P" for rewritten in result.rewritten)


def test_regenerate_id_rewrites_all_without_git(tmp_repo: Path) -> None:
    if (tmp_repo / ".git").exists():
        pytest.skip("needs a repository without git")
    _duplicate_fixture(tmp_repo)
    result = repair_regenerate_id(
        _workspace(tmp_repo, git=False), Path("documents/move/RE-STORY-7F3K2Q.json")
    )
    linking = _read_doc(tmp_repo, Path("documents/other/RE-STORY-2K7QMB.json"))
    assert [link.target for link in linking.links] == [result.new_id]


def test_regenerate_id_unknown_path_refused(repo: Path) -> None:
    with pytest.raises(OperationRefused) as excinfo:
        repair_regenerate_id(
            _workspace(repo), Path("documents/move/RE-STORY-ZZZZZZ.json")
        )
    assert excinfo.value.finding.code == "E-ID-UNKNOWN"


# --------------------------------------------------------------------------
# repair cache (spec §16.5, §13.19)
# --------------------------------------------------------------------------


def test_repair_cache_rebuilds_corrupt_cache(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA")
    cache_path = tmp_repo / ".gregraph" / "cache" / "index.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("not json at all", encoding="utf-8")
    result = repair_cache(_workspace(tmp_repo, git=False))
    assert result.file_count == 1
    cache = read_sidecar(cache_path, CacheIndex)
    assert cache.tool_version
    key = "documents/user-story/RE-STORY-AAAAAA.md"
    assert key in cache.files
    assert cache.files[key].body_hash == body_hash(_read_body(tmp_repo, Path(key)))
    assert cache.types_seen["user-story"] == "requirement"
    assert cache.templates_seen["user-story/v1"]


def test_repair_cache_drops_stale_entries(tmp_repo: Path) -> None:
    _write_template(tmp_repo, "user-story", 1)
    _write_doc(tmp_repo, "RE-STORY-AAAAAA")
    cache_path = tmp_repo / ".gregraph" / "cache" / "index.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "tool_version": "0.0.0",
                "files": {
                    "ghost.md": {"mtime_ns": 1, "size": 1, "body_hash": "sha256:x"}
                },
                "types_seen": {"gone": "goal"},
                "templates_seen": {"ghost/v1": "sha256:y"},
            }
        ),
        encoding="utf-8",
    )
    repair_cache(_workspace(tmp_repo, git=False))
    cache = read_sidecar(cache_path, CacheIndex)
    assert "ghost.md" not in cache.files
    assert "gone" not in cache.types_seen
    assert "ghost/v1" not in cache.templates_seen
    assert "user-story" in cache.types_seen
