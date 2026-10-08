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
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

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
    cr_new,
    create_document,
    deprecate,
    link,
    link_refresh,
    record_introduction,
    set_fields,
    supersede,
    supersession_chain,
    undeprecate,
    unlink,
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
