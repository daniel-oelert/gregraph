"""Tests for ``gregraph.core.operations`` (spec §4.2, §5.4, §5.6, §7.4, §7.6,
§11.2, §13.2–13.6, §13.14–13.15).

Test-first (appendix C): the document lifecycle subset — create (ID
generation, template render, checked initial links), link/unlink (rules,
exclusivity, cycles with path, duplicate no-op, target state, effective
``target_version``, symmetric edges), link refresh (``--from/--to/--all``,
``--follow`` chains and forks, deprecated refusal), ``set`` (tags/extra and
the pointer refusals), supersede (multi-target compromise, copy-body/link
defaults and per-edge checks, stale inbound, ``--cr`` notices), and
deprecate/undeprecate. Refusals raise ``OperationRefused`` with the right code
(docs/decisions.md ``D-S12-OPERATIONS``).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from gregraph.core import agents
from gregraph.core.git import GitAdapter
from gregraph.core.hashing import body_hash
from gregraph.core.ids import is_derivable_from
from gregraph.core.models import (
    ChangeRequest,
    Document,
    Link,
    LinkType,
    OperationRefused,
    TemplateRef,
)
from gregraph.core.operations import (
    _effective_version,
    body_state,
    build_context,
    check,
    cr_new,
    create_document,
    deprecate,
    describe_schema,
    hook_pre_commit,
    init_repository,
    link,
    link_candidates,
    link_refresh,
    list_documents,
    record_introduction,
    repair_agents,
    set_fields,
    supersede,
    supersession_chain,
    sync,
    template_sections,
    template_show,
    term_add,
    undeprecate,
    unlink,
    update_body,
    update_sections,
)
from gregraph.core.storage import read_sidecar, write_body, write_sidecar
from gregraph.core.versioning import scope_hash
from gregraph.core.workspace import Workspace

if TYPE_CHECKING:
    from conftest import GitIdentity, SampleGraph

CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=dt.UTC)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.org", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def commit_tree(root: Path, message: str = "initial") -> None:
    """Commit the whole tree when ``root`` is a Git repository (no-op otherwise).

    Git-mode fixtures rely on this before effective-version assertions: an
    uncommitted ``v1`` document is in the initial-grace state (§3.3) whose
    effective version stays ``1``.
    """
    if not (root / ".git").exists():
        return
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "--allow-empty", "-m", message)


def add_template(
    root: Path,
    name: str,
    *,
    version: int = 1,
    deprecated: bool = False,
    sections: list[dict[str, object]] | None = None,
    body: str | None = None,
) -> None:
    """Write one template version into the repository (spec §5.5)."""
    directory = root / ".gregraph" / "templates" / name / f"v{version}"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = {
        "schema": 1,
        "name": name,
        "version": version,
        "description": f"{name} v{version}",
        "deprecated": deprecated,
        "breaking": False,
        "sections": sections
        or [{"heading": "Notes", "required": False, "placeholder": ""}],
    }
    (directory / "template.json").write_text(json.dumps(descriptor), encoding="utf-8")
    (directory / "template.md").write_text(
        body if body is not None else "# {{ title }}\n\n## Notes\n",
        encoding="utf-8",
    )


def add_cr(root: Path, cr_id: str = "CR-ABCDEF") -> str:
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


def document_sidecar_rel(root: Path, doc_id: str) -> Path:
    return next((root / "documents").rglob(f"{doc_id}.json")).relative_to(root)


def read_doc(root: Path, doc_id: str) -> Document:
    return read_sidecar(next((root / "documents").rglob(f"{doc_id}.json")), Document)


def write_link(root: Path, doc_id: str, link_type: LinkType, target: str) -> None:
    """Attach an unchecked edge directly (invalid setups, broken targets)."""
    document = read_doc(root, doc_id)
    document.links = [
        *document.links,
        Link(type=link_type, target=target, target_version=1),
    ]
    write_sidecar(root / document_sidecar_rel(root, doc_id), document)


# --------------------------------------------------------------------------
# create_document (spec §13.2)
# --------------------------------------------------------------------------


def test_create_document_writes_pair(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    result = create_document(
        ws, type="user-story", title="Upload documents", tags=["upload"]
    )
    body_path = tmp_repo / result.body
    sidecar_path = tmp_repo / result.sidecar
    assert result.body == Path("documents/user-story") / f"{result.id}.md"
    assert body_path.is_file() and sidecar_path.is_file()
    assert body_path.read_text(encoding="utf-8").startswith("# Upload documents\n")
    document = read_sidecar(sidecar_path, Document)
    assert document.id == result.id
    assert is_derivable_from(document.id, document.uuid, "RE")
    assert document.title == "Upload documents"
    assert document.version == 1
    assert document.template == TemplateRef(name="user-story", version=1)
    assert document.body_hash == body_hash(body_path.read_text(encoding="utf-8"))
    assert document.tags == ["upload"]
    assert document.deprecated is None
    assert document.origin_cr is None
    assert result.id in Workspace.open(tmp_repo).index.documents


def test_create_document_ids_unique(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    first = create_document(ws, type="user-story", title="One")
    second = create_document(ws, type="user-story", title="Two")
    assert first.id != second.id
    assert first.uuid != second.uuid


def test_create_document_unknown_type_refused(tmp_repo: Path) -> None:
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="nope", title="X")
    assert excinfo.value.finding.code == "E-TYPE-UNKNOWN"
    assert not list((tmp_repo / "documents").rglob("*.md"))


def test_create_document_missing_template_refused(tmp_repo: Path) -> None:
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X")
    assert excinfo.value.finding.code == "E-TEMPLATE-UNKNOWN"


def test_create_document_deprecated_template_refused(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story", deprecated=True)
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X")
    assert excinfo.value.finding.code == "W-TEMPLATE-DEPRECATED"
    pinned = create_document(
        ws, type="user-story", title="X", template_version=1, allow_deprecated=True
    )
    assert pinned.template == TemplateRef(name="user-story", version=1)


def test_create_document_initial_links_checked(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    add_template(root, "user-story")
    ws = Workspace.open(root)
    feature = sample_graph.ids["feature"]
    story_old = sample_graph.ids["story_old"]
    result = create_document(
        ws, type="user-story", title="New story", links=[("refines", feature)]
    )
    assert [entry.type for entry in result.links] == ["refines"]
    assert result.links[0].target == feature
    assert result.links[0].target_version == 1
    with pytest.raises(OperationRefused) as excinfo:
        create_document(
            ws, type="user-story", title="Bad", links=[("refines", story_old)]
        )
    assert excinfo.value.finding.code == "E-TARGET-SUPERSEDED"
    with pytest.raises(OperationRefused) as excinfo:
        create_document(
            ws, type="user-story", title="Missing", links=[("refines", "RE-NOSUCH")]
        )
    assert excinfo.value.finding.code == "E-LINK-TARGET-MISSING"


def test_create_document_duplicate_initial_link_notice(
    sample_graph: SampleGraph,
) -> None:
    root = sample_graph.root
    add_template(root, "user-story")
    ws = Workspace.open(root)
    feature = sample_graph.ids["feature"]
    result = create_document(
        ws,
        type="user-story",
        title="Dup",
        links=[("refines", feature), ("refines", feature)],
    )
    assert len(result.links) == 1
    assert any("duplicate" in notice for notice in result.notices)


def test_create_document_invalid_tag_refused(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X", tags=["Bad"])
    assert excinfo.value.finding.code == "E-TAG-INVALID"


def test_create_document_effective_target_version(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="goal", title="Goal")
    commit_tree(tmp_repo)
    body = tmp_repo / goal.body
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    story = create_document(
        ws, type="user-story", title="Story", links=[("refines", goal.id)]
    )
    assert story.links[0].target_version == 2


def test_create_document_cr_wiring(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_template(tmp_repo, "user-story")
    cr_id = add_cr(tmp_repo)
    calls: list[tuple[str, str]] = []

    def fake_record(workspace: Workspace, *, cr_id: str, doc_id: str) -> None:
        calls.append((cr_id, doc_id))

    monkeypatch.setattr("gregraph.core.operations.record_introduction", fake_record)
    ws = Workspace.open(tmp_repo)
    result = create_document(ws, type="user-story", title="From CR", cr=cr_id)
    assert calls == [(cr_id, result.id)]
    document = read_sidecar(tmp_repo / result.sidecar, Document)
    assert document.origin_cr == cr_id


def test_create_document_cr_disabled_refused(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_template(tmp_repo, "user-story")
    cr_id = add_cr(tmp_repo)
    config = tmp_repo / ".gregraph" / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\n[cr]\nenabled = false\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "gregraph.core.operations.record_introduction",
        lambda workspace, *, cr_id, doc_id: calls.append((cr_id, doc_id)),
    )
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X", cr=cr_id)
    assert excinfo.value.finding.code == "E-CR-DISABLED"
    assert not calls


def test_create_document_unknown_cr_refused(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X", cr="CR-NOSUCH")
    assert excinfo.value.finding.code == "E-ID-UNKNOWN"


def test_create_document_identity_warning(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    result = create_document(ws, type="user-story", title="X")
    assert {finding.code for finding in result.findings} == {"W-NO-GIT-IDENTITY"}
    assert read_sidecar(tmp_repo / result.sidecar, Document).created_by is None


def test_create_document_identity_filled(tmp_repo: Path, identity: GitIdentity) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    result = create_document(ws, type="user-story", title="X")
    assert result.findings == ()
    document = read_sidecar(tmp_repo / result.sidecar, Document)
    assert document.created_by is not None
    assert document.created_by.name == identity.name


# --------------------------------------------------------------------------
# link / unlink (spec §13.3–13.4)
# --------------------------------------------------------------------------


def test_link_records_effective_version(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    commit_tree(root)
    ws = Workspace.open(root)
    feature = sample_graph.ids["feature"]
    orphan = sample_graph.ids["orphan"]
    body = root / "documents" / "feature" / f"{feature}.md"
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    result = link(ws, source=orphan, link_type="relates-to", target=feature)
    assert result.created and result.link is not None
    assert result.link.target_version == 2
    assert read_doc(root, orphan).links[-1].target_version == 2


def test_link_duplicate_noop(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    result = link(ws, source=story, link_type="refines", target=feature)
    assert not result.created
    assert result.notice is not None


def test_link_edge_rule_refused(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    stakeholder = sample_graph.ids["stakeholder"]
    goal = sample_graph.ids["goal"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=stakeholder, link_type="refines", target=goal)
    assert excinfo.value.finding.code == "E-EDGE-RULE"


def test_link_exclusive_refused(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    fr = sample_graph.ids["fr"]
    scan_story = sample_graph.ids["scan_story"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=fr, link_type="derives-from", target=scan_story)
    assert excinfo.value.finding.code == "E-EDGE-EXCLUSIVE"
    assert excinfo.value.finding.fix is not None


def test_link_cycle_refused_with_path(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    goal = sample_graph.ids["goal"]
    epic = sample_graph.ids["epic"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=goal, link_type="refines", target=epic)
    finding = excinfo.value.finding
    assert finding.code == "E-CYCLE"
    assert "→" in finding.message
    assert goal in finding.message and epic in finding.message


def test_link_superseded_target_refused_except_supersedes(
    sample_graph: SampleGraph,
) -> None:
    ws = Workspace.open(sample_graph.root)
    fr = sample_graph.ids["fr"]
    story_old = sample_graph.ids["story_old"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=fr, link_type="depends-on", target=story_old)
    assert excinfo.value.finding.code == "E-TARGET-SUPERSEDED"
    result = link(ws, source=fr, link_type="supersedes", target=story_old)
    assert result.created


def test_link_deprecated_target_refused(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    stale_note = sample_graph.ids["stale_note"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=orphan, link_type="relates-to", target=stale_note)
    assert excinfo.value.finding.code == "E-TARGET-DEPRECATED"


def test_link_missing_target_refused(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=orphan, link_type="relates-to", target="RE-NOSUCH")
    assert excinfo.value.finding.code == "E-LINK-TARGET-MISSING"


def test_link_unknown_source_refused(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source="RE-NOSUCH", link_type="relates-to", target=orphan)
    assert excinfo.value.finding.code == "E-ID-UNKNOWN"


def test_unlink_removes_directed(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    ws = Workspace.open(root)
    fr = sample_graph.ids["fr"]
    scan_story = sample_graph.ids["scan_story"]
    result = unlink(ws, source=fr, link_type="refines", target=scan_story)
    assert result.removed and result.removed_from == fr
    assert all(
        not (entry.type == "refines" and entry.target == scan_story)
        for entry in read_doc(root, fr).links
    )


def test_unlink_symmetric_either_endpoint(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    ws = Workspace.open(root)
    compliance = sample_graph.ids["compliance"]
    design = sample_graph.ids["design"]
    # stored on compliance as compliance --conflicts-with--> design
    result = unlink(ws, source=design, link_type="conflicts-with", target=compliance)
    assert result.removed and result.removed_from == compliance
    assert all(
        entry.type != "conflicts-with" for entry in read_doc(root, compliance).links
    )
    again = unlink(ws, source=design, link_type="conflicts-with", target=compliance)
    assert not again.removed and again.notice is not None


def test_unlink_missing_noop(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    story = sample_graph.ids["story"]
    goal = sample_graph.ids["goal"]
    result = unlink(ws, source=story, link_type="refines", target=goal)
    assert not result.removed and result.notice is not None


def test_unlink_broken_edge(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    orphan = sample_graph.ids["orphan"]
    write_link(root, orphan, "relates-to", "RE-NOSUCH")
    ws = Workspace.open(root)
    result = unlink(ws, source=orphan, link_type="relates-to", target="RE-NOSUCH")
    assert result.removed


# --------------------------------------------------------------------------
# link refresh (spec §13.5)
# --------------------------------------------------------------------------


def test_link_refresh_to_updates_inbound(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    commit_tree(root)
    feature = sample_graph.ids["feature"]
    body = root / "documents" / "feature" / f"{feature}.md"
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    ws = Workspace.open(root)
    result = link_refresh(ws, to_id=feature)
    assert len(result.refreshed) == 4
    assert all(item.new_target_version == 2 for item in result.refreshed)
    assert all(not item.repointed for item in result.refreshed)
    for item in result.refreshed:
        document = read_doc(root, item.source)
        stored = [
            entry.target_version
            for entry in document.links
            if entry.type == item.type and entry.target == feature
        ]
        assert stored == [2]


def test_link_refresh_from_and_all_and_dry_run(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    commit_tree(root)
    feature = sample_graph.ids["feature"]
    story = sample_graph.ids["story"]
    body = root / "documents" / "feature" / f"{feature}.md"
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    ws = Workspace.open(root)
    dry = link_refresh(ws, to_id=feature, dry_run=True)
    assert dry.dry_run and dry.refreshed
    assert read_doc(root, story).links[0].target_version == 1
    from_result = link_refresh(ws, from_id=story)
    assert from_result.refreshed and from_result.refreshed[0].new_target_version == 2
    feature_body = root / "documents" / "feature" / f"{feature}.md"
    write_body(feature_body, feature_body.read_text(encoding="utf-8") + "\nMore.\n")
    ws = Workspace.open(root)
    all_result = link_refresh(ws, select_all=True)
    assert all_result.refreshed


def test_link_refresh_follow_chain(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    x = create_document(ws, type="user-story", title="X", links=[("refines", old.id)])
    middle = supersede(ws, targets=[old.id], title="Middle")
    end = supersede(ws, targets=[middle.id], title="End")
    ws = Workspace.open(tmp_repo)
    result = link_refresh(
        ws, source=x.id, link_type="refines", target=old.id, follow=True
    )
    assert len(result.refreshed) == 1
    entry = result.refreshed[0]
    assert entry.repointed and entry.new_target == end.id
    stored = read_doc(tmp_repo, x.id).links
    assert [(item.type, item.target) for item in stored] == [("refines", end.id)]
    chain = supersession_chain(ws, old.id)
    assert chain.end == end.id
    assert chain.path == (old.id, middle.id, end.id)


def test_link_refresh_follow_fork_refused(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    x = create_document(ws, type="user-story", title="X", links=[("refines", old.id)])
    first = supersede(ws, targets=[old.id], title="First")
    second = supersede(ws, targets=[old.id], title="Second")
    ws = Workspace.open(tmp_repo)
    chain = supersession_chain(ws, old.id)
    assert chain.end is None
    assert chain.fork_at == old.id
    assert chain.fork_successors == tuple(sorted((first.id, second.id)))
    with pytest.raises(OperationRefused) as excinfo:
        link_refresh(ws, source=x.id, link_type="refines", target=old.id, follow=True)
    assert excinfo.value.finding.code == "E-SUPERSEDE-FORK"


def test_link_refresh_stale_without_follow(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    x = create_document(ws, type="user-story", title="X", links=[("refines", old.id)])
    successor = supersede(ws, targets=[old.id], title="Successor")
    ws = Workspace.open(tmp_repo)
    result = link_refresh(ws, source=x.id, link_type="refines", target=old.id)
    assert result.refreshed == ()
    assert len(result.stale) == 1
    assert result.stale[0].chain.successors == (successor.id,)
    assert {finding.code for finding in result.findings} == {"W-LINK-STALE"}
    stored = read_doc(tmp_repo, x.id).links
    assert [(item.type, item.target, item.target_version) for item in stored] == [
        ("refines", old.id, 1)
    ]


def test_link_refresh_deprecated_target_refused(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="goal", title="Goal")
    x = create_document(ws, type="user-story", title="X", links=[("refines", goal.id)])
    deprecate(ws, doc_id=goal.id, reason="obsolete")
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        link_refresh(ws, source=x.id, link_type="refines", target=goal.id)
    assert excinfo.value.finding.code == "E-TARGET-DEPRECATED"
    assert excinfo.value.finding.fix is not None


def test_link_refresh_supersedes_quiet(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    new = supersede(ws, targets=[old.id], title="New")
    ws = Workspace.open(tmp_repo)
    result = link_refresh(
        ws,
        source=new.id,
        link_type="supersedes",
        target=old.id,
        follow=True,
    )
    assert result.stale == ()
    assert not any(item.repointed for item in result.refreshed)


def test_link_refresh_missing_target_refused(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    orphan = sample_graph.ids["orphan"]
    write_link(root, orphan, "relates-to", "RE-NOSUCH")
    ws = Workspace.open(root)
    with pytest.raises(OperationRefused) as excinfo:
        link_refresh(ws, select_all=True)
    assert excinfo.value.finding.code == "E-LINK-TARGET-MISSING"


# --------------------------------------------------------------------------
# set (spec §13.6)
# --------------------------------------------------------------------------


def test_set_tags_operations(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    ws = Workspace.open(root)
    orphan = sample_graph.ids["orphan"]
    result = set_fields(ws, doc_id=orphan, assignments=["tags=a,b"])
    assert result.tags == ("a", "b")
    result = set_fields(ws, doc_id=orphan, assignments=["tags+=c"])
    assert result.tags == ("a", "b", "c")
    result = set_fields(ws, doc_id=orphan, assignments=["tags-=b"])
    assert result.tags == ("a", "c")
    assert read_doc(root, orphan).tags == ["a", "c"]


def test_set_extra_operations(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    result = set_fields(ws, doc_id=orphan, assignments=["extra.owner=alice"])
    assert result.extra == {"owner": "alice"}
    result = set_fields(ws, doc_id=orphan, assignments=["extra.owner="])
    assert result.extra == {}
    assert any("not present" in notice for notice in result.notices) is False
    result = set_fields(
        ws, doc_id=orphan, assignments=["extra.priority=high", "extra.owner=bob"]
    )
    assert result.extra == {"priority": "high", "owner": "bob"}


def test_set_unknown_keys_point_elsewhere(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    for key, expected in (
        ("title=New", "gregraph edit"),
        ("type=feature", "gregraph supersede"),
        ("status=accepted", "gregraph cr set"),
    ):
        with pytest.raises(OperationRefused) as excinfo:
            set_fields(ws, doc_id=orphan, assignments=[key])
        finding = excinfo.value.finding
        assert finding.code == "E-SET-KEY"
        assert finding.fix is not None and expected in finding.fix


def test_set_value_and_tag_refusals(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    with pytest.raises(OperationRefused) as excinfo:
        set_fields(ws, doc_id=orphan, assignments=["garbage"])
    assert excinfo.value.finding.code == "E-SET-VALUE"
    with pytest.raises(OperationRefused) as excinfo:
        set_fields(ws, doc_id=orphan, assignments=["tags+=Bad"])
    assert excinfo.value.finding.code == "E-TAG-INVALID"
    with pytest.raises(OperationRefused) as excinfo:
        set_fields(ws, doc_id=orphan, assignments=["extra.x+=y"])
    assert excinfo.value.finding.code == "E-SET-VALUE"


def test_set_atomic_on_refusal(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    ws = Workspace.open(root)
    orphan = sample_graph.ids["orphan"]
    with pytest.raises(OperationRefused):
        set_fields(ws, doc_id=orphan, assignments=["tags=ok", "title=Nope"])
    assert read_doc(root, orphan).tags == []


# --------------------------------------------------------------------------
# supersede (spec §7.6, §11.2)
# --------------------------------------------------------------------------


def test_supersede_single_target(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old", tags=["t"])
    x = create_document(ws, type="user-story", title="X", links=[("refines", old.id)])
    result = supersede(ws, targets=[old.id], title="New")
    assert result.supersedes == (old.id,)
    assert result.type == "user-story"
    assert result.template == TemplateRef(name="user-story", version=1)
    new_document = read_doc(tmp_repo, result.id)
    assert [(entry.type, entry.target) for entry in new_document.links] == [
        ("supersedes", old.id)
    ]
    body_text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert body_text.startswith("# New\n")
    assert "## Notes" in body_text
    old_document = read_doc(tmp_repo, old.id)
    assert old_document.links == []
    assert old_document.title == "Old"
    assert len(result.stale_inbound) == 1
    assert result.stale_inbound[0].source == x.id
    assert result.stale_inbound[0].target == old.id


def test_supersede_copy_body_and_links(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="goal", title="Goal")
    old = create_document(
        ws, type="user-story", title="Old", links=[("refines", goal.id)]
    )
    result = supersede(ws, targets=[old.id], title="New")
    assert result.copied_links and result.copied_links[0].target == goal.id
    assert result.copied_links[0].target_version == 1
    body_text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert body_text.startswith("# New\n")
    assert "## Notes" in body_text
    explicit = supersede(
        ws, targets=[goal.id], title="Goal 2", copy_body=False, copy_links=False
    )
    assert explicit.copied_links == ()
    assert (
        (tmp_repo / explicit.body).read_text(encoding="utf-8").startswith("# Goal 2\n")
    )


def test_supersede_copy_body_default_off_when_template_differs(
    tmp_repo: Path,
) -> None:
    add_template(tmp_repo, "user-story", version=1)
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    add_template(
        tmp_repo,
        "user-story",
        version=2,
        body="# {{ title }}\n\n## Story\n*As a…*\n",
    )
    ws = Workspace.open(tmp_repo)
    result = supersede(ws, targets=[old.id], title="New")
    body_text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert "## Story" in body_text
    assert result.template == TemplateRef(name="user-story", version=2)


def test_supersede_multi_target_compromise(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "feature")
    add_template(tmp_repo, "design")
    ws = Workspace.open(tmp_repo)
    feature = create_document(ws, type="feature", title="Feature")
    design = create_document(ws, type="design", title="Design")
    first = create_document(
        ws, type="user-story", title="A", links=[("refines", feature.id)]
    )
    second = create_document(
        ws,
        type="user-story",
        title="B",
        links=[("derives-from", feature.id)],
    )
    link(ws, source=first.id, link_type="conflicts-with", target=second.id)
    link(ws, source=first.id, link_type="relates-to", target=design.id)
    link(ws, source=second.id, link_type="relates-to", target=design.id)
    ws = Workspace.open(tmp_repo)
    result = supersede(ws, targets=[first.id, second.id], title="Compromise")
    assert result.supersedes == (first.id, second.id)
    copied = {(entry.type, entry.target) for entry in result.copied_links}
    assert ("refines", feature.id) in copied
    assert ("relates-to", design.id) in copied
    assert sum(1 for entry in result.copied_links if entry.type == "relates-to") == 1
    codes = {finding.code for finding in result.skipped_links}
    assert codes == {"E-EDGE-EXCLUSIVE", "E-TARGET-SUPERSEDED"}
    assert any("collapsed" in notice for notice in result.notices)
    new_document = read_doc(tmp_repo, result.id)
    supersedes = [
        entry.target for entry in new_document.links if entry.type == "supersedes"
    ]
    assert sorted(supersedes) == sorted((first.id, second.id))
    # the conflict edge stays on the old documents as history (§11.2)
    assert any(
        entry.type == "conflicts-with" for entry in read_doc(tmp_repo, first.id).links
    )


def test_supersede_multi_target_type_default(sample_graph: SampleGraph) -> None:
    root = sample_graph.root
    add_template(root, "user-story")
    add_template(root, "feature")
    ws = Workspace.open(root)
    story = sample_graph.ids["story"]
    feature = sample_graph.ids["feature"]
    result = supersede(ws, targets=[story, feature], title="Both")
    assert result.type == "user-story"
    assert any("different types" in notice for notice in result.notices)
    assert ("supersedes", feature) in [
        (entry.type, entry.target) for entry in read_doc(root, result.id).links
    ]


def test_supersede_unknown_target_refused(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        supersede(ws, targets=["RE-NOSUCH"], title="X")
    assert excinfo.value.finding.code == "E-ID-UNKNOWN"
    with pytest.raises(ValueError):
        supersede(ws, targets=[], title="X")


def test_supersede_cr_scope_notice(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_template(tmp_repo, "user-story")
    cr_id = add_cr(tmp_repo)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "gregraph.core.operations.record_introduction",
        lambda workspace, *, cr_id, doc_id: calls.append((cr_id, doc_id)),
    )
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    result = supersede(ws, targets=[old.id], title="New", cr=cr_id)
    assert calls == [(cr_id, result.id)]
    assert any("cr scope add" in notice for notice in result.notices)
    assert read_doc(tmp_repo, result.id).origin_cr == cr_id


def test_superseded_target_cannot_be_linked(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    goal = create_document(ws, type="goal", title="Goal")
    supersede(ws, targets=[old.id], title="New")
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=goal.id, link_type="depends-on", target=old.id)
    assert excinfo.value.finding.code == "E-TARGET-SUPERSEDED"
    replacement = create_document(ws, type="user-story", title="Replacement")
    result = link(ws, source=replacement.id, link_type="supersedes", target=old.id)
    assert result.created


# --------------------------------------------------------------------------
# deprecate / undeprecate (spec §13.15, §11.2 pattern 2)
# --------------------------------------------------------------------------


def test_deprecate_and_undeprecate(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="goal", title="Goal")
    x = create_document(ws, type="user-story", title="X", links=[("refines", goal.id)])
    result = deprecate(ws, doc_id=goal.id, reason="Resolved in favour of A")
    assert result.changed and result.deprecated is not None
    assert result.deprecated.reason == "Resolved in favour of A"
    assert len(result.stale_inbound) == 1
    assert result.stale_inbound[0].source == x.id
    document = read_doc(tmp_repo, goal.id)
    assert document.deprecated is not None
    again = deprecate(ws, doc_id=goal.id, reason="twice")
    assert not again.changed and again.notices
    back = undeprecate(ws, doc_id=goal.id)
    assert back.changed and back.deprecated is None
    assert read_doc(tmp_repo, goal.id).deprecated is None
    noop = undeprecate(ws, doc_id=goal.id)
    assert not noop.changed and noop.notices


# --------------------------------------------------------------------------
# refusals and stub surface
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# change request operations (S13, spec §13.18) — full suite in test_changes.py
# --------------------------------------------------------------------------


def test_cr_operations_smoke(tmp_repo: Path) -> None:
    add_template(tmp_repo, "change-request", body="# {{ title }}\n\n## Notes\n")
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    story = create_document(ws, type="user-story", title="Target")
    created = cr_new(ws, title="Change", scope=[story.id])
    body_path = tmp_repo / "changes" / f"{created.id}.md"
    sidecar_path = tmp_repo / "changes" / f"{created.id}.json"
    assert body_path.is_file() and sidecar_path.is_file()
    cr = read_sidecar(sidecar_path, ChangeRequest)
    assert cr.status == "open"
    assert [entry.id for entry in cr.scope] == [story.id]
    result = record_introduction(ws, cr_id=created.id, doc_id=story.id)
    assert result.changed
    assert read_sidecar(sidecar_path, ChangeRequest).introduces == [story.id]


def test_unknown_id_refusals(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    for call in (
        lambda: set_fields(ws, doc_id="RE-NOSUCH", assignments=["tags=a"]),
        lambda: deprecate(ws, doc_id="RE-NOSUCH", reason="r"),
        lambda: undeprecate(ws, doc_id="RE-NOSUCH"),
        lambda: link_refresh(ws, from_id="RE-NOSUCH"),
    ):
        with pytest.raises(OperationRefused) as excinfo:
            call()
        assert excinfo.value.finding.code == "E-ID-UNKNOWN"


def test_operation_refused_carries_finding(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=orphan, link_type="relates-to", target="RE-NOSUCH")
    finding = excinfo.value.finding
    assert finding.severity == "E"
    assert "E-LINK-TARGET-MISSING" in str(excinfo.value)


# --------------------------------------------------------------------------
# remaining branches
# --------------------------------------------------------------------------


def test_link_unknown_edge_type_refused(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    goal = sample_graph.ids["goal"]
    with pytest.raises(OperationRefused) as excinfo:
        link(ws, source=orphan, link_type="bogus", target=goal)  # type: ignore[arg-type]
    assert excinfo.value.finding.code == "E-LINK-TYPE-UNKNOWN"


def test_link_refresh_selector_validation(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    with pytest.raises(ValueError):
        link_refresh(ws)
    with pytest.raises(ValueError):
        link_refresh(ws, select_all=True, from_id=sample_graph.ids["story"])
    with pytest.raises(ValueError):
        link_refresh(ws, source=sample_graph.ids["story"])


def test_link_refresh_no_match_notices(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    story = sample_graph.ids["story"]
    goal = sample_graph.ids["goal"]
    result = link_refresh(ws, source=story, link_type="refines", target=goal)
    assert result.refreshed == ()
    assert any("no link" in notice for notice in result.notices)
    add_template(sample_graph.root, "user-story")
    lonely = create_document(ws, type="user-story", title="Lonely")
    result = link_refresh(ws, to_id=lonely.id)
    assert result.notices == ("no matching links",)


def test_link_refresh_duplicate_collapse_repoint(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    x = create_document(ws, type="user-story", title="X", links=[("refines", old.id)])
    successor = supersede(ws, targets=[old.id], title="Successor")
    link(ws, source=x.id, link_type="refines", target=successor.id)
    ws = Workspace.open(tmp_repo)
    result = link_refresh(
        ws, source=x.id, link_type="refines", target=old.id, follow=True
    )
    assert any("already has" in notice for notice in result.notices)
    stored = read_doc(tmp_repo, x.id).links
    assert [(item.type, item.target) for item in stored] == [("refines", successor.id)]


def test_supersession_chain_loop_refused(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    first = create_document(ws, type="user-story", title="First")
    second = create_document(ws, type="user-story", title="Second")
    x = create_document(ws, type="user-story", title="X", links=[("refines", first.id)])
    write_link(tmp_repo, first.id, "supersedes", second.id)
    write_link(tmp_repo, second.id, "supersedes", first.id)
    ws = Workspace.open(tmp_repo)
    chain = supersession_chain(ws, first.id)
    assert chain.looped and chain.end is None
    with pytest.raises(OperationRefused) as excinfo:
        link_refresh(ws, source=x.id, link_type="refines", target=first.id, follow=True)
    assert excinfo.value.finding.code == "E-CYCLE"


def test_supersede_replaces_missing_h1(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    write_body(tmp_repo / old.body, "Just text.\n")
    ws = Workspace.open(tmp_repo)
    result = supersede(ws, targets=[old.id], title="New", copy_body=True)
    body_text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert body_text.startswith("# New\n")
    assert "Just text." in body_text


def test_supersede_copy_body_explicit_across_versions(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story", version=1)
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    add_template(
        tmp_repo,
        "user-story",
        version=2,
        body="# {{ title }}\n\n## Story\n*As a…*\n",
    )
    ws = Workspace.open(tmp_repo)
    result = supersede(ws, targets=[old.id], title="New", copy_body=True)
    body_text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert body_text.startswith("# New\n")
    assert "## Notes" in body_text
    assert "## Story" not in body_text


def test_create_missing_pinned_template_version(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X", template_version=99)
    assert excinfo.value.finding.code == "E-TEMPLATE-UNKNOWN"


def test_effective_version_accounts_for_assets(tmp_repo: Path) -> None:
    add_template(tmp_repo, "goal")
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="goal", title="Goal")
    commit_tree(tmp_repo)
    asset_dir = tmp_repo / "assets" / goal.id
    asset_dir.mkdir(parents=True)
    (asset_dir / "pic.png").write_bytes(b"png")
    body = tmp_repo / goal.body
    write_body(
        body,
        body.read_text(encoding="utf-8") + f"\n![x](../../assets/{goal.id}/pic.png)\n",
    )
    ws = Workspace.open(tmp_repo)
    story = create_document(
        ws, type="user-story", title="Story", links=[("refines", goal.id)]
    )
    assert story.links[0].target_version == 2
    (asset_dir / "pic.png").write_bytes(b"png2")
    ws = Workspace.open(tmp_repo)
    second = create_document(
        ws, type="user-story", title="Second", links=[("refines", goal.id)]
    )
    assert second.links[0].target_version == 2


def test_set_extra_absent_removal_notice(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    result = set_fields(ws, doc_id=orphan, assignments=["extra.nope="])
    assert any("not present" in notice for notice in result.notices)
    assert not result.changed


def test_supersede_duplicate_target_collapsed(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    result = supersede(ws, targets=[old.id, old.id], title="New")
    assert result.supersedes == (old.id,)
    assert any("collapsed" in notice for notice in result.notices)


def test_supersede_asset_notice_for_copied_body(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    asset_dir = tmp_repo / "assets" / old.id
    asset_dir.mkdir(parents=True)
    (asset_dir / "pic.png").write_bytes(b"png")
    write_body(
        tmp_repo / old.body,
        f"# Old\n\n![x](../../assets/{old.id}/pic.png)\n",
    )
    ws = Workspace.open(tmp_repo)
    result = supersede(ws, targets=[old.id], title="New")
    assert any("single-owner" in notice for notice in result.notices)


def test_set_tag_removal_absent_notice(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]
    result = set_fields(ws, doc_id=orphan, assignments=["tags-=ghost"])
    assert result.notices and "not present" in result.notices[0]
    assert not result.changed


# --------------------------------------------------------------------------
# v1 grace period (AGENT_READINESS §3.3, AGENT-011…AGENT-014)
# --------------------------------------------------------------------------


def test_v1_grace_effective_version_stays_one(tmp_repo: Path) -> None:
    """An uncommitted ``v1`` document is populated in place (effective 1)."""
    if not (tmp_repo / ".git").exists():
        pytest.skip("grace period requires a git-initialised tmp_repo (§3.3)")
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    goal = create_document(ws, type="user-story", title="Draft")
    body = tmp_repo / goal.body
    write_body(body, body.read_text(encoding="utf-8") + "\nFilled in.\n")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    assert _effective_version(ws, goal.id) == 1
    # the grace state also feeds links: target_version stays 1
    story = create_document(ws, type="user-story", title="Other")
    result = link(ws, source=story.id, link_type="relates-to", target=goal.id)
    assert result.link is not None and result.link.target_version == 1


def test_v1_grace_degraded_mode_bumps_normally(tmp_repo: Path) -> None:
    """Degraded mode has no grace period: sync bumps the edited v1 to 2."""
    if (tmp_repo / ".git").exists():
        pytest.skip("degraded-mode behaviour requires the no-git tmp_repo")
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="user-story", title="Draft")
    body = tmp_repo / goal.body
    write_body(body, body.read_text(encoding="utf-8") + "\nFilled in.\n")
    ws = Workspace.open(tmp_repo)
    assert _effective_version(ws, goal.id) == 2
    result = sync(ws, bump=True)
    assert result.initialised == ()
    assert result.bumped == (goal.id,)
    assert read_sidecar(tmp_repo / goal.sidecar, Document).version == 2


def test_sync_bump_initialises_uncommitted_v1(tmp_repo: Path) -> None:
    """``sync --bump`` populates the initial version in place (AGENT-011)."""
    if not (tmp_repo / ".git").exists():
        pytest.skip("grace period requires a git-initialised tmp_repo (§3.3)")
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    goal = create_document(ws, type="user-story", title="Draft")
    body = tmp_repo / goal.body
    write_body(body, body.read_text(encoding="utf-8") + "\nFilled in.\n")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    result = sync(ws, bump=True)
    assert result.initialised == (goal.id,)
    assert goal.id not in result.bumped
    document = read_sidecar(tmp_repo / goal.sidecar, Document)
    assert document.version == 1
    assert document.body_hash == body_hash(body.read_text(encoding="utf-8"))
    assert document.title == "Draft"


def test_check_reports_initialised_bucket(tmp_repo: Path) -> None:
    """``check`` classifies grace items under ``initialised``, not blocking."""
    if not (tmp_repo / ".git").exists():
        pytest.skip("grace period requires a git-initialised tmp_repo (§3.3)")
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    goal = create_document(ws, type="goal", title="Goal")
    create_document(ws, type="user-story", title="Story", links=[("refines", goal.id)])
    body = tmp_repo / goal.body
    write_body(body, body.read_text(encoding="utf-8") + "\nFilled in.\n")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    result = check(ws)
    assert result.initialised == (goal.id,)
    assert goal.id not in result.would_bump
    assert not result.blocked


def test_v1_grace_ends_after_first_commit(tmp_repo: Path) -> None:
    """After the initial commit, normal bump semantics resume (AGENT-013)."""
    if not (tmp_repo / ".git").exists():
        pytest.skip("grace period requires a git-initialised tmp_repo (§3.3)")
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    goal = create_document(ws, type="user-story", title="Draft")
    commit_tree(tmp_repo)
    body = tmp_repo / goal.body
    write_body(body, body.read_text(encoding="utf-8") + "\nEdited.\n")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    assert _effective_version(ws, goal.id) == 2
    result = sync(ws, bump=True)
    assert result.initialised == ()
    assert result.bumped == (goal.id,)
    assert read_sidecar(tmp_repo / goal.sidecar, Document).version == 2


def test_hook_pre_commit_initialises_uncommitted_v1(tmp_repo: Path) -> None:
    """The hook populates uncommitted ``v1`` bodies at version 1 (AGENT-011)."""
    if not (tmp_repo / ".git").exists():
        pytest.skip("hook grace requires a git-initialised tmp_repo (§3.3)")
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    goal = create_document(ws, type="user-story", title="Draft")
    body = tmp_repo / goal.body
    write_body(body, body.read_text(encoding="utf-8") + "\nFilled in.\n")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    ws.git.stage([goal.body, goal.sidecar])
    result = hook_pre_commit(ws)
    assert result.initialised == (goal.id,)
    assert result.bumped == ()
    document = read_sidecar(tmp_repo / goal.sidecar, Document)
    assert document.version == 1
    assert document.body_hash == body_hash(body.read_text(encoding="utf-8"))
    # the rewritten sidecar is staged so it travels with the commit
    staged = ws.git.staged_paths()
    assert goal.sidecar in staged


# --------------------------------------------------------------------------
# authoring flags (AGENT_READINESS §3.2–§3.5, AGENT-015…AGENT-019)
# --------------------------------------------------------------------------


def _story_sections() -> list[dict[str, object]]:
    return [
        {"heading": "Story", "required": True, "placeholder": "As a <role>, …"},
        {"heading": "Rationale", "required": False, "placeholder": "Why."},
    ]


def _story_template(root: Path) -> None:
    add_template(
        root,
        "user-story",
        sections=_story_sections(),
        body="# {{ title }}\n\n## Story\n*As a <role>, …*\n\n## Rationale\n*Why.*\n",
    )


def test_create_document_with_sections(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    result = create_document(
        ws, type="user-story", title="Upload", sections=[("Story", "As a user, …")]
    )
    text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert result.kind == "requirement"
    assert result.version == 1
    assert result.body_hash == body_hash(text)
    assert [section.heading for section in result.sections] == ["Story", "Rationale"]
    assert result.body_text == text
    assert result.sidecar_document is not None
    assert result.sidecar_document.id == result.id
    assert text == "# Upload\n\n## Story\n\nAs a user, …\n\n## Rationale\n\n*Why.*\n"


def test_create_document_with_body_text(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    result = create_document(
        ws, type="user-story", title="Upload", body_text="# Custom\n\nFilled.\n"
    )
    text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert text == "# Upload\n\nFilled.\n"
    assert any("replaced H1" in notice for notice in result.notices)
    document = read_sidecar(tmp_repo / result.sidecar, Document)
    assert document.body_hash == body_hash(text)


def test_create_document_body_and_section_conflict(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    with pytest.raises(ValueError):
        create_document(
            ws,
            type="user-story",
            title="X",
            body_text="# X\n",
            sections=[("Story", "y")],
        )
    assert not list((tmp_repo / "documents").rglob("*.md"))


def test_create_document_strict_refuses_unfilled_required(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X", strict=True)
    assert excinfo.value.finding.code == "E-SECTION-REQUIRED-EMPTY"
    assert not list((tmp_repo / "documents").rglob("*.md"))
    ok = create_document(
        ws,
        type="user-story",
        title="X",
        sections=[("Story", "As a user…")],
        strict=True,
    )
    assert ok.body_hash == body_hash((tmp_repo / ok.body).read_text(encoding="utf-8"))


def test_create_document_unknown_section_self_describing(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        create_document(ws, type="user-story", title="X", sections=[("Storyline", "s")])
    finding = excinfo.value.finding
    assert finding.code == "E-SECTION-UNKNOWN"
    details = finding.details or {}
    assert details["given_heading"] == "Storyline"
    assert [item["heading"] for item in details["template_sections"]] == [
        "Story",
        "Rationale",
    ]
    assert not list((tmp_repo / "documents").rglob("*.md"))


def test_body_state_reads_current_body(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    created = create_document(ws, type="user-story", title="Upload")
    write_body(tmp_repo / created.body, "# Upload\n\n## Story\n\nAs a user.\n")
    ws = Workspace.open(tmp_repo)
    state = body_state(ws, doc_id=created.id)
    assert state.id == created.id
    assert state.body == created.body
    assert state.body_hash == body_hash(state.text)
    assert [section.heading for section in state.sections] == ["Story"]
    (tmp_repo / created.body).unlink()
    ws = Workspace.open(tmp_repo)
    with pytest.raises(OperationRefused) as excinfo:
        body_state(ws, doc_id=created.id)
    assert excinfo.value.finding.code == "E-BODY-MISSING"


def test_update_sections_preserves_unmentioned_content(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    created = create_document(ws, type="user-story", title="Upload")
    write_body(
        tmp_repo / created.body,
        "# Upload\n\n## Story\n\nAs a user.\n\n## Extra\n\nKept.\n",
    )
    ws = Workspace.open(tmp_repo)
    state = body_state(ws, doc_id=created.id)
    result = update_sections(
        ws,
        doc_id=created.id,
        content={"Rationale": "Because."},
        base_hash=state.body_hash,
    )
    text = (tmp_repo / result.md_path).read_text(encoding="utf-8")
    assert "## Story\n\nAs a user." in text
    assert "## Rationale\n\nBecause." in text
    assert "## Extra\n\nKept." in text
    assert [section.heading for section in result.sections] == ["Story", "Rationale"]
    assert result.json_path == created.sidecar
    with pytest.raises(OperationRefused) as excinfo:
        update_sections(
            ws,
            doc_id=created.id,
            content={"Rationale": "Again."},
            base_hash=state.body_hash,
        )
    assert excinfo.value.finding.code == "E-BODY-STALE"


def test_update_sections_refuses_unknown_heading(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    created = create_document(ws, type="user-story", title="Upload")
    state = body_state(ws, doc_id=created.id)
    with pytest.raises(OperationRefused) as excinfo:
        update_sections(
            ws,
            doc_id=created.id,
            content={"Storyline": "s"},
            base_hash=state.body_hash,
        )
    assert excinfo.value.finding.code == "E-SECTION-UNKNOWN"


def test_update_sections_refuses_required_empty(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    created = create_document(
        ws, type="user-story", title="Upload", sections=[("Story", "As a user.")]
    )
    state = body_state(ws, doc_id=created.id)
    with pytest.raises(OperationRefused) as excinfo:
        update_sections(
            ws,
            doc_id=created.id,
            content={"Story": ""},
            base_hash=state.body_hash,
        )
    assert excinfo.value.finding.code == "E-SECTION-REQUIRED-EMPTY"


def test_update_body_strict_refuses_unfilled_required(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    created = create_document(ws, type="user-story", title="Upload")
    state = body_state(ws, doc_id=created.id)
    with pytest.raises(OperationRefused) as excinfo:
        update_body(
            ws,
            doc_id=created.id,
            text=state.text,
            base_hash=state.body_hash,
            strict=True,
        )
    assert excinfo.value.finding.code == "E-SECTION-REQUIRED-EMPTY"
    assert (
        not (tmp_repo / created.body).exists()
        or (tmp_repo / created.body).read_text(encoding="utf-8") == state.text
    )
    filled = "# Upload\n\n## Story\n\nAs a user.\n\n## Rationale\n\nWhy.\n"
    result = update_body(
        ws, doc_id=created.id, text=filled, base_hash=state.body_hash, strict=True
    )
    assert result.changed
    assert result.md_path == created.body
    assert result.json_path == created.sidecar
    assert result.notices == ()


def test_update_body_carries_notices(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    created = create_document(ws, type="user-story", title="Upload")
    state = body_state(ws, doc_id=created.id)
    result = update_body(
        ws,
        doc_id=created.id,
        text=state.text,
        base_hash=state.body_hash,
        notices=("stdin read",),
    )
    assert result.notices == ("stdin read",)
    document = read_sidecar(tmp_repo / created.sidecar, Document)
    assert result.sections == template_sections(ws, template=document.template)


def test_supersede_with_body_text(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    result = supersede(
        ws,
        targets=[old.id],
        title="New",
        body_text="# Whatever\n\n## Story\n\nNew story.\n",
    )
    text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert text == "# New\n\n## Story\n\nNew story.\n"
    assert result.new is not None
    assert result.new.kind == "requirement"
    assert result.new.version == 1
    assert result.new.body_hash == body_hash(text)
    assert result.new.body_text == text
    assert result.new.sections is not None
    assert [s.heading for s in result.new.sections] == ["Story", "Rationale"]
    assert result.new.sidecar_document is not None


def test_supersede_with_sections_over_copy(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    old = create_document(
        ws, type="user-story", title="Old", sections=[("Story", "Old story.")]
    )
    result = supersede(ws, targets=[old.id], title="New", sections=[("Story", "New.")])
    text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert "## Story\n\nNew." in text
    assert "Old story." not in text
    assert "## Rationale" in text
    with pytest.raises(ValueError):
        supersede(
            ws,
            targets=[old.id],
            title="X",
            body_text="# X\n",
            sections=[("Story", "y")],
        )


def test_supersede_strict_refuses_unfilled_required(tmp_repo: Path) -> None:
    _story_template(tmp_repo)
    ws = Workspace.open(tmp_repo)
    old = create_document(ws, type="user-story", title="Old")
    with pytest.raises(OperationRefused) as excinfo:
        supersede(ws, targets=[old.id], title="New", strict=True)
    assert excinfo.value.finding.code == "E-SECTION-REQUIRED-EMPTY"
    filled = supersede(
        ws,
        targets=[old.id],
        title="New",
        sections=[("Story", "As a user.")],
        strict=True,
    )
    assert filled.new is not None and filled.new.body_hash


def test_cr_new_with_sections(tmp_repo: Path) -> None:
    add_template(
        tmp_repo,
        "change-request",
        sections=[
            {"heading": "Motivation", "required": True, "placeholder": "Explain."},
            {"heading": "Notes", "required": False, "placeholder": ""},
        ],
        body="# {{ title }}\n\n## Motivation\n*Explain.*\n\n## Notes\n",
    )
    ws = Workspace.open(tmp_repo)
    result = cr_new(ws, title="Raise the limit", sections=[("Motivation", "Why.")])
    text = (tmp_repo / "changes" / f"{result.id}.md").read_text(encoding="utf-8")
    assert result.sections is not None
    assert [section.heading for section in result.sections] == ["Motivation", "Notes"]
    assert result.body_text == text
    assert "## Motivation\n\nWhy." in text
    assert result.sidecar_model is not None
    assert result.sidecar_model.id == result.id
    assert result.sidecar_model.status == "open"
    with pytest.raises(OperationRefused) as excinfo:
        cr_new(ws, title="T", sections=[("Rationale", "x")])
    assert excinfo.value.finding.code == "E-SECTION-UNKNOWN"
    with pytest.raises(OperationRefused) as excinfo:
        cr_new(ws, title="T", strict=True)
    assert excinfo.value.finding.code == "E-SECTION-REQUIRED-EMPTY"


def test_term_add_with_sections(tmp_repo: Path) -> None:
    add_template(
        tmp_repo,
        "term",
        sections=[
            {"heading": "Definition", "required": True, "placeholder": "Define."},
            {"heading": "Notes", "required": False, "placeholder": ""},
        ],
        body="# {{ title }}\n\n## Definition\n*Define.*\n\n## Notes\n",
    )
    ws = Workspace.open(tmp_repo)
    result = term_add(
        ws, term="Knowledge base", aliases=["KB"], sections=[("Definition", "A store.")]
    )
    text = (tmp_repo / result.body).read_text(encoding="utf-8")
    assert result.aliases == ("KB",)
    assert [section.heading for section in result.sections] == ["Definition", "Notes"]
    assert result.body_text == text
    assert "## Definition\n\nA store." in text
    assert result.body_hash == body_hash(text)
    with pytest.raises(OperationRefused) as excinfo:
        term_add(ws, term="Other", strict=True)
    assert excinfo.value.finding.code == "E-SECTION-REQUIRED-EMPTY"


# --------------------------------------------------------------------------
# introspection (AGENT_READINESS §4.1–§4.3, AGENT-021…AGENT-023)
# --------------------------------------------------------------------------


def test_describe_schema_rulebook(tmp_repo: Path) -> None:
    from gregraph import __version__

    add_template(tmp_repo, "user-story", sections=_story_sections())
    add_template(tmp_repo, "change-request")
    ws = Workspace.open(tmp_repo)
    info = describe_schema(ws)
    assert info.schema_ == 1
    assert info.tool_version == __version__
    assert info.id_prefix == "RE"
    assert info.baseline_branch == "main"
    assert info.versioning == {"on_outdated_links": "block", "on_cr_modified": "warn"}
    assert info.graph == {"open_conflicts": "warn"}
    assert info.assets == {"max_size_kb": 5120}
    assert info.cr["enabled"] is True and info.cr["template"] == "change-request"
    assert info.kinds == (
        "goal",
        "requirement",
        "design",
        "verification",
        "information",
    )
    assert len(info.edge_rules) == 9
    refines = next(rule for rule in info.edge_rules if rule.type == "refines")
    assert refines.direction == "directed"
    assert refines.hierarchical and refines.acyclic
    assert refines.source_kinds == ("goal", "requirement")
    assert refines.mutually_exclusive_with == ("derives-from",)
    assert refines.mutually_exclusive_opposite == ("depends-on",)
    depends = next(rule for rule in info.edge_rules if rule.type == "depends-on")
    assert depends.mutually_exclusive_opposite == ("derives-from", "refines")
    conflicts = next(rule for rule in info.edge_rules if rule.type == "conflicts-with")
    assert conflicts.direction == "symmetric" and not conflicts.acyclic
    assert info.types["user-story"].kind == "requirement"
    assert info.types["user-story"].template == "user-story"
    assert info.types["user-story"].id_prefix == "RE"
    assert info.types["user-story"].description == "user-story v1"
    template_info = info.templates["user-story"]
    assert template_info.latest_version == 1
    assert template_info.versions == (1,)
    assert [section.heading for section in template_info.sections] == [
        "Story",
        "Rationale",
    ]
    assert info.cr_lifecycle.statuses == ("open", "accepted", "rejected", "implemented")
    assert info.cr_lifecycle.transitions["open"] == ("accepted", "rejected")
    assert info.cr_lifecycle.transitions["implemented"] == ("open",)
    assert info.cr_lifecycle.scope_intents == ("modify", "supersede", "deprecate")


def test_describe_schema_type_filter(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "change-request")
    ws = Workspace.open(tmp_repo)
    info = describe_schema(ws, type="user-story")
    assert set(info.types) == {"user-story"}
    # the type's template, plus the CR template while CRs are enabled
    assert set(info.templates) == {"user-story", "change-request"}
    assert info.kinds == (
        "goal",
        "requirement",
        "design",
        "verification",
        "information",
    )
    with pytest.raises(OperationRefused) as excinfo:
        describe_schema(ws, type="nope")
    assert excinfo.value.finding.code == "E-TYPE-UNKNOWN"


def test_link_candidates_kind_rule_and_liveness(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    story = sample_graph.ids["story"]
    result = link_candidates(ws, source=story, edge_type="refines")
    assert result.source == story
    assert result.source_kind == "requirement"
    targets = {candidate.target for candidate in result.candidates}
    assert sample_graph.ids["feature"] in targets
    assert sample_graph.ids["goal"] in targets
    # dead targets are excluded: superseded and deprecated
    assert sample_graph.ids["story_old"] not in targets
    assert sample_graph.ids["stale_note"] not in targets
    # kind rule: refines needs goal|requirement on both ends
    assert sample_graph.ids["design"] not in targets
    assert sample_graph.ids["test"] not in targets


def test_link_candidates_excludes_cycles(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="goal", title="Goal")
    story = create_document(
        ws, type="user-story", title="Story", links=[("refines", goal.id)]
    )
    ws = Workspace.open(tmp_repo)
    result = link_candidates(ws, source=goal.id, edge_type="refines")
    # story refines goal, so goal refines story would close a directed cycle
    assert story.id not in {candidate.target for candidate in result.candidates}
    other = create_document(ws, type="user-story", title="Other")
    ws = Workspace.open(tmp_repo)
    result = link_candidates(ws, source=goal.id, edge_type="refines")
    assert other.id in {candidate.target for candidate in result.candidates}


def test_link_candidates_all_types_and_cycle(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    orphan = sample_graph.ids["orphan"]  # assumption → information kind
    result = link_candidates(ws, source=orphan)
    assert result.allowed_edge_types == ("supersedes", "relates-to")
    supersedes_targets = {
        candidate.target
        for candidate in result.candidates
        if candidate.type == "supersedes"
    }
    # same-kind-only: stakeholder is information like orphan; stale_note is dead
    assert supersedes_targets == {sample_graph.ids["stakeholder"]}
    relates = {
        candidate.target
        for candidate in result.candidates
        if candidate.type == "relates-to"
    }
    assert sample_graph.ids["goal"] in relates
    with pytest.raises(ValueError):
        link_candidates(ws, source=orphan, edge_type="bogus")  # type: ignore[arg-type]
    with pytest.raises(OperationRefused) as excinfo:
        link_candidates(ws, source="RE-NOSUCH")
    assert excinfo.value.finding.code == "E-ID-UNKNOWN"


# --------------------------------------------------------------------------
# context packing (AGENT_READINESS §6.1, §6.3, AGENT-027, AGENT-030)
# --------------------------------------------------------------------------


def test_build_context_targets_and_neighbors(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    story = sample_graph.ids["story"]
    result = build_context(ws, ids=[story])
    assert result.requested == (story,)
    assert result.depth == 1
    assert result.direction == "both"
    target = result.targets[0]
    assert target.show.id == story
    assert target.show.body_text is not None
    neighbours = {neighbour.id: neighbour for neighbour in result.neighbors}
    # downstream: story's own edges; upstream: edges stored on the neighbours
    assert set(neighbours) == {
        sample_graph.ids["feature"],
        sample_graph.ids["story_old"],
        sample_graph.ids["fr"],
        sample_graph.ids["test"],
    }
    feature = neighbours[sample_graph.ids["feature"]]
    assert feature.direction == "downstream"
    assert feature.depth == 1
    assert feature.freshness == "fresh"
    assert feature.via.source == story and feature.via.type == "refines"
    assert feature.sidecar.id == feature.id
    assert "Sample body" in feature.body
    fr = neighbours[sample_graph.ids["fr"]]
    assert fr.direction == "upstream"
    assert fr.via.type == "depends-on"


def test_build_context_direction_and_depth(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    story = sample_graph.ids["story"]
    downstream = build_context(ws, ids=[story], direction="downstream")
    assert {n.id for n in downstream.neighbors} == {
        sample_graph.ids["feature"],
        sample_graph.ids["story_old"],
    }
    upstream = build_context(ws, ids=[story], direction="upstream")
    assert {n.id for n in upstream.neighbors} == {
        sample_graph.ids["fr"],
        sample_graph.ids["test"],
    }
    deep = build_context(ws, ids=[story], depth=2)
    neighbours = {n.id: n for n in deep.neighbors}
    assert neighbours[sample_graph.ids["scan_story"]].depth == 2
    shallow = build_context(ws, ids=[story], depth=0)
    assert shallow.neighbors == ()


def test_build_context_validation_errors(sample_graph: SampleGraph) -> None:
    ws = Workspace.open(sample_graph.root)
    with pytest.raises(ValueError):
        build_context(ws, ids=[], depth=1)
    with pytest.raises(ValueError):
        build_context(ws, ids=["RE-X"], depth=-1)
    with pytest.raises(ValueError):
        build_context(ws, ids=["RE-X"], direction="sideways")  # type: ignore[arg-type]
    with pytest.raises(OperationRefused) as excinfo:
        build_context(ws, ids=["RE-NOSUCH"])
    assert excinfo.value.finding.code == "E-ID-UNKNOWN"
    assert excinfo.value.finding.subject == "RE-NOSUCH"


def test_build_context_terms(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(
        tmp_repo,
        "term",
        sections=[
            {"heading": "Definition", "required": True, "placeholder": "Define."},
            {"heading": "Notes", "required": False, "placeholder": ""},
        ],
        body="# {{ title }}\n\n## Definition\n*Define.*\n\n## Notes\n",
    )
    ws = Workspace.open(tmp_repo)
    doc = create_document(ws, type="user-story", title="Upload")
    term_add(ws, term="Knowledge base", aliases=["KB"])
    write_body(
        tmp_repo / doc.body, "# Upload\n\nThe Knowledge base (KB) stores files.\n"
    )
    ws = Workspace.open(tmp_repo)
    result = build_context(ws, ids=[doc.id])
    assert [term.slug for term in result.terms] == ["knowledge-base"]
    entry = result.terms[0]
    assert entry.term == "Knowledge base"
    assert entry.aliases == ("KB",)
    assert "## Definition" in entry.body
    without_terms = build_context(ws, ids=[doc.id], include_terms=False)
    assert without_terms.terms == ()


def test_build_context_findings_scoped_to_bundle(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    inside = create_document(ws, type="user-story", title="Inside")
    outside = create_document(ws, type="user-story", title="Outside")
    write_body(
        tmp_repo / outside.body,
        "# Outside\n\n## Story\n\n*As a <role>, …*\n",
    )  # unfilled required section only on the outside document
    ws = Workspace.open(tmp_repo)
    result = build_context(ws, ids=[inside.id])
    subjects = {str(finding.subject) for finding in result.findings}
    assert all(subject == inside.id for subject in subjects)
    result = build_context(ws, ids=[inside.id, outside.id])
    subjects = {str(finding.subject) for finding in result.findings}
    assert outside.id in subjects


def test_build_context_pending_finding_git_mode(tmp_repo: Path) -> None:
    if not (tmp_repo / ".git").exists():
        pytest.skip("pending freshness is a git-mode state (§7.4)")
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    goal = create_document(ws, type="goal", title="Goal")
    story = create_document(
        ws, type="user-story", title="Story", links=[("refines", goal.id)]
    )
    commit_tree(tmp_repo)
    write_body(
        tmp_repo / goal.body,
        (tmp_repo / goal.body).read_text(encoding="utf-8") + "\nEdited.\n",
    )
    ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
    result = build_context(ws, ids=[story.id])
    pending = [f for f in result.findings if f.code == "W-LINK-PENDING"]
    assert pending and pending[0].subject == story.id
    neighbour = next(n for n in result.neighbors if n.id == goal.id)
    assert neighbour.freshness == "pending-outdated"


def test_build_context_synthesises_pending_without_git(tmp_repo: Path) -> None:
    """Degraded mode: validate gates W-LINK-PENDING on git; context synthesises."""
    if (tmp_repo / ".git").exists():
        pytest.skip("synthesis covers the no-git gate (§6.1)")
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "goal")
    ws = Workspace.open(tmp_repo)
    goal = create_document(ws, type="goal", title="Goal")
    story = create_document(
        ws, type="user-story", title="Story", links=[("refines", goal.id)]
    )
    write_body(
        tmp_repo / goal.body,
        (tmp_repo / goal.body).read_text(encoding="utf-8") + "\nEdited.\n",
    )
    ws = Workspace.open(tmp_repo)
    result = build_context(ws, ids=[story.id])
    pending = [f for f in result.findings if f.code == "W-LINK-PENDING"]
    assert pending and pending[0].subject == story.id
    assert any(
        n.id == goal.id and n.freshness == "pending-outdated" for n in result.neighbors
    )


def test_build_context_cr_targets_and_scope_neighbors(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    add_template(tmp_repo, "change-request")
    ws = Workspace.open(tmp_repo)
    doc = create_document(ws, type="user-story", title="Target")
    created = cr_new(ws, title="Change", scope=[doc.id])
    ws = Workspace.open(tmp_repo)
    result = build_context(ws, ids=[created.id])
    assert result.requested == (created.id,)
    target = result.targets[0]
    assert target.show.change_request is not None
    assert target.show.change_request.body != ""
    neighbour = next(n for n in result.neighbors if n.id == doc.id)
    assert neighbour.via.type == "scope"
    assert neighbour.via.source == created.id
    assert neighbour.direction == "downstream"
    assert neighbour.freshness == "fresh"


def test_list_documents_include_body(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    created = create_document(ws, type="user-story", title="Upload")
    with_body = list_documents(ws, include_body=True)
    assert with_body.rows[0].body == (tmp_repo / created.body).read_text(
        encoding="utf-8"
    )
    without_body = list_documents(ws)
    assert without_body.rows[0].body is None


# --------------------------------------------------------------------------
# agent scaffolding (AGENT_READINESS §7.1–§7.3, AGENT-031…AGENT-033)
# --------------------------------------------------------------------------


def test_init_writes_agent_files(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    result = init_repository(target, no_git=True)
    assert result.agents_files == agents.AGENTS_FILES
    agents_md = target / "AGENTS.md"
    skill_md = target / ".agents" / "skills" / "gregraph" / "SKILL.md"
    assert agents_md.is_file() and skill_md.is_file()
    text = agents_md.read_text(encoding="utf-8")
    assert agents.AGENTS_BLOCK_START in text and agents.AGENTS_BLOCK_END in text
    assert skill_md.read_text(encoding="utf-8").startswith("---\nname: gregraph\n")


def test_repair_agents_writes_and_is_idempotent(tmp_repo: Path) -> None:
    ws = Workspace.open(tmp_repo)
    first = repair_agents(ws)
    assert first.agents_files == agents.AGENTS_FILES
    assert first.changed == agents.AGENTS_FILES
    assert (tmp_repo / "AGENTS.md").is_file()
    second = repair_agents(ws)
    assert second.changed == ()
    (tmp_repo / "AGENTS.md").write_text("# Custom instructions\n", encoding="utf-8")
    third = repair_agents(ws)
    assert third.changed == (agents.AGENTS_REL_PATH,)
    text = (tmp_repo / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Custom instructions\n")
    assert text.count(agents.AGENTS_BLOCK_START) == 1


def test_sync_refreshes_agent_files(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    create_document(ws, type="user-story", title="Draft")
    result = sync(ws, bump=True)
    assert result.agents_files_changed == agents.AGENTS_FILES
    again = sync(ws, bump=True)
    assert again.agents_files_changed == ()


def test_template_show_reports_path(tmp_repo: Path) -> None:
    add_template(tmp_repo, "user-story")
    ws = Workspace.open(tmp_repo)
    result = template_show(ws, "user-story")
    assert result.path == Path(".gregraph/templates/user-story/v1/template.md")
