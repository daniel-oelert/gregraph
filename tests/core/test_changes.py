"""Tests for ``gregraph.core.changes`` and the ``cr`` operations (spec §9).

Test-first (appendix C): the change-request subsystem outside the graph —
content hashing contract (§9.2, D14), scope add/remove with baseline base
versions (§9.4), the decision state machine and effective status (§9.3),
drift and implementation checks (§9.6), origin tracking (§9.5), the CR
validation codes of §14 (one test each), both §9.9 workflows as state
sequences, and the BOOT-302/303 acceptance scenarios.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from gregraph.core.config import Config, CrSection, write_config
from gregraph.core.git import GitAdapter
from gregraph.core.hashing import body_hash
from gregraph.core.ids import decode_body, derive_id
from gregraph.core.models import (
    ChangeRequest,
    CrStatus,
    Decision,
    Deprecation,
    Document,
    Finding,
    Identity,
    Link,
    OperationRefused,
    ScopeEntry,
    TemplateRef,
)
from gregraph.core.operations import (
    cr_list,
    cr_new,
    cr_reaffirm,
    cr_reanalyze,
    cr_scope_add,
    cr_scope_remove,
    cr_set,
    cr_show,
    create_document,
    record_introduction,
    supersede,
)
from gregraph.core.storage import (
    config_path,
    read_body,
    read_sidecar,
    write_body,
    write_sidecar,
)
from gregraph.core.validation import (
    CODE_SEVERITIES,
    has_errors,
    validate_workspace,
)
from gregraph.core.versioning import scope_hash as reconcile_scope_hash
from gregraph.core.workspace import Workspace

UTC = dt.UTC
CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=UTC)
DOC = "RE-AAAAAA"
DOC2 = "RE-BBBBBB"
CR = "RE-CCCCCC"
CR2 = "RE-DDDDDD"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def uuid_for(body: str) -> UUID:
    """Deterministic UUID whose §4.1 ID body is ``body``."""
    return UUID(int=decode_body(body) << 98)


def id_for(body: str) -> str:
    return derive_id(uuid_for(body), "RE")


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


def setup_repo(root: Path, *, config: Config | None = None) -> None:
    """Default config plus empty-section templates so validate stays quiet."""
    write_config(config_path(root), config if config is not None else Config())
    add_template(root, "user-story")
    add_template(root, "change-request")


def make_doc(
    root: Path,
    body: str = "AAAAAA",
    *,
    version: int = 1,
    title: str = "First document",
    type: str = "user-story",
    links: Sequence[Link] = (),
    deprecated: Deprecation | None = None,
    origin_cr: str | None = None,
    text: str | None = None,
) -> str:
    """Write a structurally valid document pair; returns its ID."""
    doc_id = id_for(body)
    content = text if text is not None else f"# {title}\n\nText.\n"
    folder = Config().types[type].folder
    document = Document(
        schema=1,
        uuid=uuid_for(body),
        id=doc_id,
        type=type,
        title=title,
        created=CREATED,
        created_by=None,
        template=TemplateRef(name=Config().types[type].template, version=1),
        version=version,
        body_hash=body_hash(content),
        assets=[],
        links=list(links),
        deprecated=deprecated,
        tags=[],
        extra={},
        origin_cr=origin_cr,
    )
    write_body(root / "documents" / folder / f"{doc_id}.md", content)
    write_sidecar(root / "documents" / folder / f"{doc_id}.json", document)
    return doc_id


def make_cr(
    root: Path,
    body: str = "CCCCCC",
    *,
    title: str = "Raise the limit",
    status: CrStatus = "open",
    scope: Sequence[ScopeEntry] = (),
    introduces: Sequence[str] = (),
    decisions: Sequence[Decision] | None = None,
    version: int = 1,
    text: str | None = None,
    by: Identity | None = None,
    branch: str | None = None,
    external_ref: str | None = None,
    tags: Sequence[str] = (),
    extra: Mapping[str, str] | None = None,
) -> str:
    """Write a change-request pair with consistent content hashes; returns its ID."""
    cr_id = id_for(body)
    content = text if text is not None else f"# {title}\n\nBody.\n"
    entries = sorted(scope, key=lambda entry: entry.id)
    cr = ChangeRequest(
        schema=1,
        uuid=uuid_for(body),
        id=cr_id,
        title=title,
        created=CREATED,
        created_by=by,
        template=TemplateRef(name="change-request", version=1),
        version=version,
        body_hash=body_hash(content),
        scope_hash=reconcile_scope_hash(entries),
        scope=list(entries),
        introduces=sorted(introduces),
        status=status,
        decisions=(
            list(decisions)
            if decisions is not None
            else [Decision(status="open", at=CREATED, by=by, at_version=1)]
        ),
        branch=branch,
        external_ref=external_ref,
        tags=list(tags),
        extra=dict(extra or {}),
    )
    write_body(root / "changes" / f"{cr_id}.md", content)
    write_sidecar(root / "changes" / f"{cr_id}.json", cr)
    return cr_id


def read_cr(root: Path, cr_id: str) -> ChangeRequest:
    return read_sidecar(root / "changes" / f"{cr_id}.json", ChangeRequest)


def read_doc(root: Path, doc_id: str) -> Document:
    return read_sidecar(next((root / "documents").rglob(f"{doc_id}.json")), Document)


def write_doc_sidecar(root: Path, document: Document) -> None:
    write_sidecar(next((root / "documents").rglob(f"{document.id}.json")), document)


def bump_doc(root: Path, doc_id: str, text: str) -> None:
    """Record a content change the way the hook would (spec §7.2)."""
    document = read_doc(root, doc_id)
    document.version += 1
    document.body_hash = body_hash(text)
    write_body(next((root / "documents").rglob(f"{doc_id}.md")), text)
    write_doc_sidecar(root, document)


def write_doc_body(root: Path, doc_id: str, text: str) -> None:
    write_body(next((root / "documents").rglob(f"{doc_id}.md")), text)


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.org", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def require_git(root: Path) -> GitAdapter:
    """Skip without git; force the unborn HEAD onto ``main`` (spec §12.4)."""
    if not (root / ".git").exists():
        pytest.skip("requires a git-initialised tmp_repo (spec §12.1)")
    _run_git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    return GitAdapter(root)


def git_commit(root: Path, message: str) -> None:
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "--allow-empty", "-m", message)


def git_checkout(root: Path, branch: str, *, new: bool = False) -> None:
    if new:
        _run_git(root, "checkout", "-b", branch)
    else:
        _run_git(root, "checkout", branch)


def ws_of(root: Path, *, git: bool = True) -> Workspace:
    adapter = GitAdapter(root) if git and (root / ".git").exists() else None
    return Workspace.open(root, git=adapter)


def codes(findings: Sequence[Finding]) -> list[str]:
    return [finding.code for finding in findings]


def of_code(findings: Sequence[Finding], code: str) -> list[Finding]:
    return [finding for finding in findings if finding.code == code]


def cr_codes(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if f.code.startswith(("E-CR", "W-CR"))]


def refused(call: Any, code: str) -> Finding:
    with pytest.raises(OperationRefused) as excinfo:
        call()
    finding = excinfo.value.finding
    assert finding.code == code
    return finding


# --------------------------------------------------------------------------
# content hashing contract (spec §9.2, D14)
# --------------------------------------------------------------------------


def test_content_hashes_match_reconcile_inputs(tmp_repo: Path) -> None:
    from gregraph.core.changes import content_hashes

    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=3)
    scope = [ScopeEntry(id=DOC, intent="modify", base_version=3)]
    cr_id = make_cr(tmp_repo, scope=scope)
    cr = read_cr(tmp_repo, cr_id)
    text = "# Raise the limit\n\nBody.\n"
    assert content_hashes(cr, text) == (body_hash(text), reconcile_scope_hash(scope))
    assert cr.scope_hash == reconcile_scope_hash(scope)


def test_content_excludes_metadata_fields(tmp_repo: Path) -> None:
    from gregraph.core.changes import content_changed

    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    cr = read_cr(tmp_repo, cr_id)
    cr.status = "accepted"
    cr.decisions = [
        *cr.decisions,
        Decision(status="accepted", at=CREATED, by=None, at_version=1),
    ]
    cr.introduces = [DOC]
    cr.branch = "cr/a"
    cr.external_ref = "JIRA-1"
    cr.tags = ["x"]
    cr.extra = {"k": "v"}
    assert not content_changed(cr, "# Raise the limit\n\nBody.\n")


def test_scope_change_is_content_change(tmp_repo: Path) -> None:
    from gregraph.core.changes import content_changed

    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(tmp_repo)
    cr = read_cr(tmp_repo, cr_id)
    cr.scope = [ScopeEntry(id=DOC, intent="modify", base_version=1)]
    assert content_changed(cr, "# Raise the limit\n\nBody.\n")


def test_cr_new_initial_state(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    ws = ws_of(tmp_repo, git=False)
    result = cr_new(ws, title="Raise the limit", scope=[DOC])
    cr = read_cr(tmp_repo, result.id)
    assert cr.status == "open"
    assert cr.version == 1
    assert cr.decisions == [
        Decision(status="open", at=cr.created, by=None, at_version=1)
    ]
    assert cr.scope == [ScopeEntry(id=DOC, intent="modify", base_version=1)]
    assert cr.introduces == []
    assert cr.body_hash == body_hash(
        read_body(tmp_repo / "changes" / f"{result.id}.md")
    )
    assert cr.scope_hash == reconcile_scope_hash(cr.scope)


def test_cr_new_scope_specs_parsing(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    make_doc(tmp_repo, "BBBBBB")
    ws = ws_of(tmp_repo, git=False)
    result = cr_new(ws, title="T", scope=[f"{DOC}:supersede", f"{DOC2}:deprecate"])
    assert [(entry.id, entry.intent) for entry in result.scope] == [
        (DOC, "supersede"),
        (DOC2, "deprecate"),
    ]
    with pytest.raises(ValueError):
        cr_new(ws, title="T", scope=[f"{DOC}:bogus"])
    with pytest.raises(ValueError):
        cr_new(ws, title=None)


# --------------------------------------------------------------------------
# scope (spec §9.4)
# --------------------------------------------------------------------------


def test_scope_add_base_version_degraded(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=4)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    result = cr_scope_add(ws, cr_id=cr_id, target=DOC)
    assert result.scope == (ScopeEntry(id=DOC, intent="modify", base_version=4),)
    assert read_cr(tmp_repo, cr_id).scope[0].base_version == 4


def test_scope_add_bumps_version(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(tmp_repo, version=1)
    ws = ws_of(tmp_repo, git=False)
    result = cr_scope_add(ws, cr_id=cr_id, target=DOC)
    assert result.version == 2
    cr = read_cr(tmp_repo, cr_id)
    assert cr.version == 2
    assert cr.scope_hash == reconcile_scope_hash(cr.scope)


def test_scope_add_base_version_from_baseline(tmp_repo: Path) -> None:
    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=5)
    git_commit(tmp_repo, "v5")
    cr_id = make_cr(tmp_repo)
    git_commit(tmp_repo, "cr")
    # the working tree already carries this CR's own edit of the target
    bump_doc(tmp_repo, DOC, "# First document\n\nCR edit.\n")
    ws = ws_of(tmp_repo)
    result = cr_scope_add(ws, cr_id=cr_id, target=DOC)
    assert result.scope[0].base_version == 5


def test_scope_add_refuses_new_work(tmp_repo: Path) -> None:
    require_git(tmp_repo)
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    git_commit(tmp_repo, "baseline without documents")
    make_doc(tmp_repo, "AAAAAA")  # new work: absent from the baseline branch
    finding = refused(
        lambda: cr_scope_add(ws_of(tmp_repo), cr_id=cr_id, target=DOC),
        "E-CR-SCOPE-TARGET",
    )
    assert "--cr" in (finding.fix or "") + finding.message
    assert read_cr(tmp_repo, cr_id).scope == []


def test_scope_add_refuses_dead_target(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(
        tmp_repo,
        "AAAAAA",
        deprecated=Deprecation(at=CREATED, by=None, reason="r"),
    )
    make_doc(tmp_repo, "BBBBBB")
    make_doc(
        tmp_repo,
        "FFFFF1",
        links=[Link(type="supersedes", target=DOC2, target_version=1)],
    )
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    refused(lambda: cr_scope_add(ws, cr_id=cr_id, target=DOC), "E-CR-SCOPE-TARGET")
    refused(lambda: cr_scope_add(ws, cr_id=cr_id, target=DOC2), "E-CR-SCOPE-TARGET")
    assert read_cr(tmp_repo, cr_id).scope == []


def test_scope_add_refuses_duplicate_and_non_documents(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    make_cr(tmp_repo, "DDDDDD")
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    cr_scope_add(ws, cr_id=cr_id, target=DOC)
    refused(lambda: cr_scope_add(ws, cr_id=cr_id, target=DOC), "E-CR-SCOPE-TARGET")
    refused(
        lambda: cr_scope_add(ws, cr_id=cr_id, target=id_for("DDDDDD")),
        "E-CR-SCOPE-TARGET",
    )
    refused(
        lambda: cr_scope_add(ws, cr_id=cr_id, target="RE-NOSUCH"), "E-CR-SCOPE-TARGET"
    )


def test_scope_remove(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(
        tmp_repo, scope=[ScopeEntry(id=DOC, intent="modify", base_version=1)]
    )
    ws = ws_of(tmp_repo, git=False)
    result = cr_scope_remove(ws, cr_id=cr_id, target=DOC)
    assert result.scope == ()
    assert result.version == 2
    assert read_cr(tmp_repo, cr_id).scope == []
    noop = cr_scope_remove(ws, cr_id=cr_id, target=DOC)
    assert not noop.changed
    assert noop.notices


def test_reanalyze_updates_base_version_and_bumps(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2)
    cr_id = make_cr(
        tmp_repo,
        scope=[ScopeEntry(id=DOC, intent="modify", base_version=1)],
        version=3,
    )
    ws = ws_of(tmp_repo, git=False)
    result = cr_reanalyze(ws, cr_id=cr_id)
    assert result.scope[0].base_version == 2
    assert result.version == 4
    cr = read_cr(tmp_repo, cr_id)
    assert cr.version == 4
    assert cr.scope_hash == reconcile_scope_hash(cr.scope)


def test_reanalyze_selected_target_and_unknown_refused(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2)
    make_doc(tmp_repo, "BBBBBB", version=2)
    cr_id = make_cr(
        tmp_repo,
        scope=[
            ScopeEntry(id=DOC, intent="modify", base_version=1),
            ScopeEntry(id=DOC2, intent="modify", base_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    result = cr_reanalyze(ws, cr_id=cr_id, targets=[DOC])
    assert {entry.id: entry.base_version for entry in result.scope} == {DOC: 2, DOC2: 1}
    refused(
        lambda: cr_reanalyze(ws, cr_id=cr_id, targets=["RE-NOSUCH"]),
        "E-CR-SCOPE-TARGET",
    )


# --------------------------------------------------------------------------
# decisions and status (spec §9.3)
# --------------------------------------------------------------------------


def test_transition_table() -> None:
    from gregraph.core.changes import transition_allowed

    assert transition_allowed(None, "open")
    assert not transition_allowed(None, "accepted")
    for from_status, to_status in [
        ("open", "accepted"),
        ("open", "rejected"),
        ("accepted", "implemented"),
        ("accepted", "open"),
        ("rejected", "open"),
        ("implemented", "open"),
    ]:
        assert transition_allowed(from_status, to_status)
    for from_status, to_status in [
        ("open", "implemented"),
        ("rejected", "accepted"),
        ("rejected", "implemented"),
        ("implemented", "accepted"),
    ]:
        assert not transition_allowed(from_status, to_status)


def test_decide_transitions_and_records_effective_version(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    cr_scope_add(ws, cr_id=cr_id, target=DOC)  # content change -> version 2
    result = cr_set(ws, cr_id=cr_id, assignments=["status=accepted"])
    cr = read_cr(tmp_repo, cr_id)
    assert result.status == "accepted"
    assert cr.status == "accepted"
    assert cr.decisions[-1].status == "accepted"
    assert cr.decisions[-1].at_version == 2
    assert cr.version == 2  # decisions excluded from content (D14)


def test_decide_refuses_invalid_transition(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    finding = refused(
        lambda: cr_set(ws, cr_id=cr_id, assignments=["status=implemented"]),
        "E-CR-STATUS",
    )
    assert "open" in finding.message


def test_decide_refuses_same_status_pointing_at_reaffirm(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(
        tmp_repo,
        status="accepted",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    finding = refused(
        lambda: cr_set(ws, cr_id=cr_id, assignments=["status=accepted"]), "E-CR-STATUS"
    )
    assert "reaffirm" in (finding.fix or "") + finding.message


def test_reaffirm_records_current_status_at_effective_version(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(
        tmp_repo,
        status="accepted",
        version=1,
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    cr_scope_add(ws, cr_id=cr_id, target=DOC)  # content change -> version 2
    result = cr_reaffirm(ws, cr_id=cr_id)
    assert result.decision is not None
    assert result.decision.status == "accepted"
    assert result.decision.at_version == 2
    cr = read_cr(tmp_repo, cr_id)
    assert cr.status == "accepted"
    assert cr.version == 2  # reaffirm itself excluded from content


def test_modified_after_decision_detection(tmp_repo: Path) -> None:
    from gregraph.core.changes import effective_cr_version, modified_after_decision

    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(
        tmp_repo,
        status="accepted",
        version=1,
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    cr = read_cr(tmp_repo, cr_id)
    assert not modified_after_decision(cr, effective_cr_version(ws, cr_id))
    cr_scope_add(ws, cr_id=cr_id, target=DOC)
    cr = read_cr(tmp_repo, cr_id)
    assert modified_after_decision(cr, effective_cr_version(ws, cr_id))


def test_modified_after_decision_quiet_while_open(tmp_repo: Path) -> None:
    from gregraph.core.changes import effective_cr_version, modified_after_decision

    setup_repo(tmp_repo)
    cr_id = make_cr(
        tmp_repo,
        version=5,
        decisions=[Decision(status="open", at=CREATED, by=None, at_version=1)],
    )
    ws = ws_of(tmp_repo, git=False)
    cr = read_cr(tmp_repo, cr_id)
    assert not modified_after_decision(cr, effective_cr_version(ws, cr_id))


# --------------------------------------------------------------------------
# effective status and drift (spec §9.3, §9.6)
# --------------------------------------------------------------------------


def test_effective_status_degraded_equals_proposed(tmp_repo: Path) -> None:
    from gregraph.core.changes import BaselineView, effective_status

    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo, status="accepted")
    cr = read_cr(tmp_repo, cr_id)
    view = BaselineView(GitAdapter(tmp_repo), "main")
    assert effective_status(view, cr) == "accepted"


def test_effective_status_from_baseline_or_none(tmp_repo: Path) -> None:
    from gregraph.core.changes import BaselineView, effective_status

    require_git(tmp_repo)
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo, status="open")
    git_commit(tmp_repo, "cr on main")
    make_cr(tmp_repo, "DDDDDD", status="open")
    git_checkout(tmp_repo, "feature", new=True)
    cr = read_cr(tmp_repo, cr_id)
    cr.status = "accepted"
    cr.decisions = [
        *cr.decisions,
        Decision(status="accepted", at=CREATED, by=None, at_version=1),
    ]
    write_sidecar(tmp_repo / "changes" / f"{cr_id}.json", cr)
    view = BaselineView(GitAdapter(tmp_repo), "main")
    assert effective_status(view, cr) == "open"  # proposed accepted; effective open
    missing = read_cr(tmp_repo, CR2)
    assert effective_status(view, missing) == "none"


def test_drift_version_and_lifecycle(tmp_repo: Path) -> None:
    from gregraph.core.changes import BaselineView, drift_entries

    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2)
    make_doc(tmp_repo, "BBBBBB", version=2)
    cr_id = make_cr(
        tmp_repo,
        scope=[
            ScopeEntry(id=DOC, intent="modify", base_version=2),
            ScopeEntry(id=DOC2, intent="supersede", base_version=2),
        ],
    )
    git_commit(tmp_repo, "baseline")
    bump_doc(tmp_repo, DOC, "# First document\n\nEdited.\n")  # version drift
    make_doc(
        tmp_repo,
        "FFFFF1",
        links=[Link(type="supersedes", target=DOC2, target_version=2)],
    )  # lifecycle drift
    git_commit(tmp_repo, "targets changed on baseline")
    view = BaselineView(GitAdapter(tmp_repo), "main")
    drift = drift_entries(view, read_cr(tmp_repo, cr_id))
    assert {entry.id for entry in drift} == {DOC, DOC2}
    by_id = {entry.id: entry for entry in drift}
    assert by_id[DOC].baseline_version == 3
    assert by_id[DOC2].superseded


def test_drift_skipped_when_effective_status_closed(tmp_repo: Path) -> None:
    from gregraph.core.changes import BaselineView, drift_entries

    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2)
    cr_id = make_cr(
        tmp_repo,
        status="implemented",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
            Decision(status="implemented", at=CREATED, by=None, at_version=1),
        ],
        scope=[ScopeEntry(id=DOC, intent="modify", base_version=1)],
    )
    git_commit(tmp_repo, "cr implemented on main")
    bump_doc(tmp_repo, DOC, "# First document\n\nDone.\n")
    git_commit(tmp_repo, "x changed")
    view = BaselineView(GitAdapter(tmp_repo), "main")
    assert drift_entries(view, read_cr(tmp_repo, cr_id)) == ()


def test_drift_requires_git(tmp_repo: Path) -> None:
    from gregraph.core.changes import BaselineView, drift_entries

    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2)
    cr_id = make_cr(
        tmp_repo, scope=[ScopeEntry(id=DOC, intent="modify", base_version=1)]
    )
    view = BaselineView(GitAdapter(tmp_repo), "main")
    assert drift_entries(view, read_cr(tmp_repo, cr_id)) == ()


# --------------------------------------------------------------------------
# implementation check (spec §9.6)
# --------------------------------------------------------------------------


def test_implemented_unchanged_detects_unmet_entries(tmp_repo: Path) -> None:
    from gregraph.core.changes import unimplemented_entries

    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=1)
    make_doc(tmp_repo, "BBBBBB", version=1)
    cr_id = make_cr(
        tmp_repo,
        status="implemented",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
            Decision(status="implemented", at=CREATED, by=None, at_version=1),
        ],
        scope=[
            ScopeEntry(id=DOC, intent="modify", base_version=1),
            ScopeEntry(id=DOC2, intent="deprecate", base_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    unmet = unimplemented_entries(ws, read_cr(tmp_repo, cr_id))
    assert [entry.id for entry in unmet] == [DOC, DOC2]
    bump_doc(tmp_repo, DOC, "# First document\n\nImplemented.\n")
    make_doc(
        tmp_repo,
        "BBBBBB",
        version=1,
        deprecated=Deprecation(at=CREATED, by=None, reason="r"),
    )
    ws = ws_of(tmp_repo, git=False)
    assert unimplemented_entries(ws, read_cr(tmp_repo, cr_id)) == ()


def test_implemented_supersede_met_by_inbound_edge(tmp_repo: Path) -> None:
    from gregraph.core.changes import unimplemented_entries

    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(
        tmp_repo,
        status="implemented",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
            Decision(status="implemented", at=CREATED, by=None, at_version=1),
        ],
        scope=[ScopeEntry(id=DOC, intent="supersede", base_version=1)],
    )
    ws = ws_of(tmp_repo, git=False)
    assert unimplemented_entries(ws, read_cr(tmp_repo, cr_id))
    make_doc(
        tmp_repo,
        "BBBBBB",
        links=[Link(type="supersedes", target=DOC, target_version=1)],
    )
    ws = ws_of(tmp_repo, git=False)
    assert unimplemented_entries(ws, read_cr(tmp_repo, cr_id)) == ()


# --------------------------------------------------------------------------
# origin tracking (spec §9.5)
# --------------------------------------------------------------------------


def test_record_introduction_updates_introduces_without_bump(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo, version=3)
    ws = ws_of(tmp_repo, git=False)
    result = record_introduction(ws, cr_id=cr_id, doc_id=id_for("BBBBBB"))
    assert result.changed
    assert result.introduces == (id_for("BBBBBB"),)
    cr = read_cr(tmp_repo, cr_id)
    assert cr.introduces == [id_for("BBBBBB")]
    assert cr.version == 3  # introduces excluded from content (D14)
    again = record_introduction(ws, cr_id=cr_id, doc_id=id_for("BBBBBB"))
    assert not again.changed


def test_record_introduction_refuses_closed_cr(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(
        tmp_repo,
        status="rejected",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="rejected", at=CREATED, by=None, at_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    refused(lambda: record_introduction(ws, cr_id=cr_id, doc_id=DOC), "E-CR-CLOSED")


def test_create_document_cr_updates_introduces(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    result = create_document(ws, type="user-story", title="From CR", cr=cr_id)
    cr = read_cr(tmp_repo, cr_id)
    assert cr.introduces == [result.id]
    assert read_doc(tmp_repo, result.id).origin_cr == cr_id


def test_supersede_cr_updates_introduces(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(
        tmp_repo,
        scope=[ScopeEntry(id=DOC, intent="supersede", base_version=1)],
    )
    ws = ws_of(tmp_repo, git=False)
    result = supersede(ws, targets=[DOC], title="New", cr=cr_id)
    cr = read_cr(tmp_repo, cr_id)
    assert cr.introduces == [result.id]
    assert read_doc(tmp_repo, result.id).origin_cr == cr_id


# --------------------------------------------------------------------------
# cr set / cr list / cr show (spec §13.18, §9.8)
# --------------------------------------------------------------------------


def test_cr_set_fields_and_tags(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    result = cr_set(
        ws,
        cr_id=cr_id,
        assignments=["branch=cr/a", "external_ref=JIRA-1", "tags=a,b", "extra.k=v"],
    )
    assert result.branch == "cr/a"
    assert result.external_ref == "JIRA-1"
    assert result.tags == ("a", "b")
    assert result.extra == {"k": "v"}
    cr = read_cr(tmp_repo, cr_id)
    assert cr.version == 1  # metadata excluded from content (D14)
    cr_set(ws, cr_id=cr_id, assignments=["tags+=c", "extra.k="])
    cr = read_cr(tmp_repo, cr_id)
    assert cr.tags == ["a", "b", "c"]
    assert cr.extra == {}


def test_cr_set_invalid_key_refused(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    refused(lambda: cr_set(ws, cr_id=cr_id, assignments=["title=X"]), "E-SET-KEY")
    refused(lambda: cr_set(ws, cr_id=cr_id, assignments=["nonsense"]), "E-SET-VALUE")
    refused(lambda: cr_set(ws, cr_id=cr_id, assignments=["tags=Bad"]), "E-TAG-INVALID")
    cr = read_cr(tmp_repo, cr_id)
    assert cr.branch is None and cr.tags == []  # atomic: nothing was written


def test_cr_list_filters(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    open_id = make_cr(tmp_repo, "CCCCCC")
    accepted_id = make_cr(
        tmp_repo,
        "DDDDDD",
        status="accepted",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    result = cr_list(ws)
    assert [entry.id for entry in result.entries] == sorted([open_id, accepted_id])
    assert [e.id for e in cr_list(ws, statuses=["accepted"]).entries] == [accepted_id]
    assert cr_list(ws, pending=True).entries == ()
    assert cr_list(ws, drift=True).entries == ()


def test_cr_show_impact_and_scope_states(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")  # X
    make_doc(
        tmp_repo,
        "BBBBBB",
        links=[Link(type="refines", target=DOC, target_version=1)],
    )  # Y refines X -> downstream of X
    make_doc(tmp_repo, "FFFFF1")  # Z
    z = id_for("FFFFF1")
    x_doc = read_doc(tmp_repo, DOC)
    x_doc.links = [Link(type="refines", target=z, target_version=1)]
    write_doc_sidecar(tmp_repo, x_doc)  # X refines Z -> Z is 1-up of X
    cr_id = make_cr(
        tmp_repo,
        scope=[ScopeEntry(id=DOC, intent="modify", base_version=1)],
        introduces=[id_for("BBBBBB")],
    )
    ws = ws_of(tmp_repo, git=False)
    result = cr_show(ws, cr_id)
    assert result.status == "open"
    assert result.effective == "open"  # degraded: equals proposed
    assert [row.id for row in result.scope] == [DOC]
    assert result.scope[0].working_version == 1
    assert result.scope[0].live == "live"
    assert result.impact == (id_for("BBBBBB"), z)
    assert [row.doc_id for row in result.introduces] == [id_for("BBBBBB")]

    # scope targets are the declared change: never repeated in the impact set
    both = make_cr(
        tmp_repo,
        "EEEEE1",
        scope=[
            ScopeEntry(id=DOC, intent="modify", base_version=1),
            ScopeEntry(id=DOC2, intent="modify", base_version=1),
        ],
    )
    result = cr_show(ws_of(tmp_repo, git=False), both)
    assert result.impact == (z,)


# --------------------------------------------------------------------------
# CR validation codes (spec §14) — one test per code
# --------------------------------------------------------------------------


def test_code_registry_matches_issue_codes() -> None:
    from gregraph.core.changes import ISSUE_CODES

    for code in ISSUE_CODES:
        assert code in CODE_SEVERITIES


def test_e_cr_disabled_refusal_surface(tmp_repo: Path) -> None:
    setup_repo(tmp_repo, config=Config(cr=CrSection(enabled=False)))
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    for call in (
        lambda: cr_new(ws, title="T"),
        lambda: cr_scope_add(ws, cr_id=cr_id, target=DOC),
        lambda: cr_scope_remove(ws, cr_id=cr_id, target=DOC),
        lambda: cr_set(ws, cr_id=cr_id, assignments=["branch=x"]),
        lambda: cr_reaffirm(ws, cr_id=cr_id),
        lambda: cr_reanalyze(ws, cr_id=cr_id),
        lambda: cr_list(ws),
        lambda: cr_show(ws, cr_id),
        lambda: record_introduction(ws, cr_id=cr_id, doc_id=DOC),
    ):
        refused(call, "E-CR-DISABLED")
    # existing CR files are still validated (§9.1)
    findings = validate_workspace(ws_of(tmp_repo, git=False))
    assert "E-CR-DISABLED" not in codes(findings)


def test_e_cr_status_validation(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(
        tmp_repo,
        status="accepted",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="rejected", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
        ],
    )
    findings = of_code(validate_workspace(ws_of(tmp_repo, git=False)), "E-CR-STATUS")
    assert findings and findings[0].subject == cr_id


def test_e_cr_scope_target_validation(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    make_cr(tmp_repo, "DDDDDD")
    cr_id = make_cr(
        tmp_repo,
        scope=[
            ScopeEntry(id=DOC, intent="modify", base_version=1),
            ScopeEntry(id=DOC, intent="modify", base_version=1),
            ScopeEntry(id=CR2, intent="modify", base_version=1),
            ScopeEntry(id="RE-NOSUCH", intent="modify", base_version=1),
        ],
    )
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "E-CR-SCOPE-TARGET"
    )
    assert len(findings) == 3  # duplicate, non-document, missing
    assert all(f.subject == cr_id for f in findings)


def test_e_cr_origin_missing(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", origin_cr="RE-NOSUCH")
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "E-CR-ORIGIN-MISSING"
    )
    assert findings and findings[0].subject == DOC


def test_e_cr_origin_mismatch(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    make_cr(tmp_repo, introduces=[DOC, DOC2])  # DOC has no origin_cr; DOC2 is missing
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "E-CR-ORIGIN-MISMATCH"
    )
    assert len(findings) == 2
    assert all(f.subject == CR for f in findings)


def test_w_cr_modified_after_decision(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(
        tmp_repo,
        status="accepted",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
        ],
    )
    ws = ws_of(tmp_repo, git=False)
    cr_scope_add(ws, cr_id=cr_id, target=DOC)  # scope change after the decision
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-MODIFIED-AFTER-DECISION"
    )
    assert findings and findings[0].subject == cr_id
    assert findings[0].severity == "W"
    cr_reaffirm(ws_of(tmp_repo, git=False), cr_id=cr_id)
    assert not of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-MODIFIED-AFTER-DECISION"
    )


def test_w_cr_decider_unknown(tmp_repo: Path) -> None:
    setup_repo(tmp_repo, config=Config(cr=CrSection(deciders=["jane@example.org"])))
    known = Identity(name="Jane", email="jane@example.org")
    cr_id = make_cr(
        tmp_repo,
        status="accepted",
        by=known,
        decisions=[
            Decision(status="open", at=CREATED, by=known, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
        ],
    )
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-DECIDER-UNKNOWN"
    )
    assert findings and findings[0].subject == cr_id
    cr = read_cr(tmp_repo, cr_id)
    cr.decisions = [
        Decision(status="open", at=CREATED, by=known, at_version=1),
        Decision(status="accepted", at=CREATED, by=known, at_version=1),
    ]
    write_sidecar(tmp_repo / "changes" / f"{cr_id}.json", cr)
    assert not of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-DECIDER-UNKNOWN"
    )


def test_w_cr_base_drift(tmp_repo: Path) -> None:
    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2)
    cr_id = make_cr(
        tmp_repo,
        scope=[ScopeEntry(id=DOC, intent="modify", base_version=2)],
    )
    git_commit(tmp_repo, "baseline")
    bump_doc(tmp_repo, DOC, "# First document\n\nOther change.\n")
    git_commit(tmp_repo, "x changed")
    findings = of_code(validate_workspace(ws_of(tmp_repo)), "W-CR-BASE-DRIFT")
    assert findings and findings[0].subject == cr_id
    assert DOC in findings[0].message


def test_w_cr_implemented_unchanged(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=1)
    cr_id = make_cr(
        tmp_repo,
        status="implemented",
        decisions=[
            Decision(status="open", at=CREATED, by=None, at_version=1),
            Decision(status="accepted", at=CREATED, by=None, at_version=1),
            Decision(status="implemented", at=CREATED, by=None, at_version=1),
        ],
        scope=[ScopeEntry(id=DOC, intent="modify", base_version=1)],
    )
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-IMPLEMENTED-UNCHANGED"
    )
    assert findings and findings[0].subject == cr_id
    bump_doc(tmp_repo, DOC, "# First document\n\nImplemented.\n")
    assert not of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-IMPLEMENTED-UNCHANGED"
    )


def test_w_cr_mention_unscoped(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    make_doc(tmp_repo, "BBBBBB")
    cr_id = make_cr(tmp_repo, text=f"# Raise the limit\n\nTouches [[{DOC2}]].\n")
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-MENTION-UNSCOPED"
    )
    assert findings and findings[0].subject == cr_id
    assert DOC2 in findings[0].message
    make_cr(
        tmp_repo,
        text=f"# Raise the limit\n\nTouches [[{DOC2}]].\n",
        scope=[ScopeEntry(id=DOC2, intent="modify", base_version=1)],
    )
    assert not of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "W-CR-MENTION-UNSCOPED"
    )


def test_e_mention_unknown_in_cr_body(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo, text="# Raise the limit\n\nSee [[RE-ZZZZZZ]].\n")
    findings = of_code(
        validate_workspace(ws_of(tmp_repo, git=False)), "E-MENTION-UNKNOWN"
    )
    assert findings and findings[0].subject == cr_id


def test_cr_body_bare_ids_are_not_mentions(tmp_repo: Path) -> None:
    # D-AGENT-6 (§5.2): bare ID-shaped prose in a CR body is not a mention
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    make_cr(tmp_repo, text="# Raise the limit\n\nTouches RE-BBBBBB.\n")
    make_cr(
        tmp_repo,
        text="# Raise the limit\n\nSee RE-ZZZZZZ and multi-target here.\n",
    )
    findings = validate_workspace(ws_of(tmp_repo, git=False))
    assert not of_code(findings, "W-CR-MENTION-UNSCOPED")
    assert not of_code(findings, "E-MENTION-UNKNOWN")


def test_cr_body_validated_against_template(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    add_template(
        tmp_repo,
        "change-request",
        sections=[
            {"heading": "Motivation", "required": True, "placeholder": "Explain."},
            {"heading": "Notes", "required": False, "placeholder": ""},
        ],
    )
    make_cr(tmp_repo, text="# Raise the limit\n\n## Notes\n\nKept.\n")
    findings = validate_workspace(ws_of(tmp_repo, git=False))
    assert "E-SECTION-REQUIRED-MISSING" in codes(findings)
    make_cr(
        tmp_repo,
        text="# Raise the limit\n\n## Motivation\n\nWhy.\n\n## Notes\n\nKept.\n",
    )
    findings = validate_workspace(ws_of(tmp_repo, git=False))
    assert "E-SECTION-REQUIRED-MISSING" not in codes(findings)
    assert "E-TITLE-MISSING" not in codes(findings)


# --------------------------------------------------------------------------
# acceptance scenarios (appendix A)
# --------------------------------------------------------------------------


def _accepted_cr_with_drift(tmp_repo: Path) -> str:
    """Accepted CR on ``cr/a`` with scope X at base 2; X moves to 3 on main."""
    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2, title="X", text="# X\n\nBody.\n")
    git_commit(tmp_repo, "X at v2")
    created = cr_new(ws_of(tmp_repo), title="Change X", scope=[DOC])
    assert created.scope[0].base_version == 2
    git_commit(tmp_repo, "CR open on main")
    git_checkout(tmp_repo, "other", new=True)
    bump_doc(tmp_repo, DOC, "# X\n\nOther change.\n")
    git_commit(tmp_repo, "X at v3")
    git_checkout(tmp_repo, "main")
    _run_git(tmp_repo, "merge", "other")
    git_checkout(tmp_repo, "cr/a", new=True)
    cr_set(ws_of(tmp_repo), cr_id=created.id, assignments=["status=accepted"])
    git_commit(tmp_repo, "accepted on cr/a")
    return created.id


def test_boot302_drift_reanalyze_modified_reaffirm(tmp_repo: Path) -> None:
    cr_id = _accepted_cr_with_drift(tmp_repo)
    findings = validate_workspace(ws_of(tmp_repo))
    drift = of_code(findings, "W-CR-BASE-DRIFT")
    assert drift and drift[0].subject == cr_id and DOC in drift[0].message
    assert not of_code(findings, "W-CR-MODIFIED-AFTER-DECISION")

    cr_reanalyze(ws_of(tmp_repo), cr_id=cr_id)
    findings = validate_workspace(ws_of(tmp_repo))
    assert not of_code(findings, "W-CR-BASE-DRIFT")
    modified = of_code(findings, "W-CR-MODIFIED-AFTER-DECISION")
    assert modified and modified[0].subject == cr_id

    cr_reaffirm(ws_of(tmp_repo), cr_id=cr_id)
    findings = validate_workspace(ws_of(tmp_repo))
    assert not of_code(findings, "W-CR-BASE-DRIFT")
    assert not of_code(findings, "W-CR-MODIFIED-AFTER-DECISION")


def test_boot303_hook_must_not_block_on_scope_edits(tmp_repo: Path) -> None:
    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2, title="X", text="# X\n\nBody.\n")
    git_commit(tmp_repo, "X at v2")
    created = cr_new(ws_of(tmp_repo), title="Change X", scope=[DOC])
    git_commit(tmp_repo, "CR on main")
    git_checkout(tmp_repo, "cr/a", new=True)
    cr_set(ws_of(tmp_repo), cr_id=created.id, assignments=["status=accepted"])
    git_commit(tmp_repo, "accepted on cr/a")
    # the scope target is edited on the CR's branch (implementation work)
    write_doc_body(tmp_repo, DOC, "# X\n\nImplemented by the CR.\n")
    findings = validate_workspace(ws_of(tmp_repo))
    assert not cr_codes(findings)
    assert not [f for f in findings if f.subject == created.id]
    # the hook aborts only on errors (BOOT-128: never because of drift/scope)
    assert not has_errors(findings)


def test_workflow_proposal_first(tmp_repo: Path) -> None:
    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2, title="X", text="# X\n\nBody.\n")
    git_commit(tmp_repo, "X at v2")
    created = cr_new(ws_of(tmp_repo), title="Change X", scope=[DOC])
    git_commit(tmp_repo, "CR merged: effective open")
    assert cr_show(ws_of(tmp_repo), created.id).effective == "open"

    git_checkout(tmp_repo, "cr/a", new=True)
    cr_set(ws_of(tmp_repo), cr_id=created.id, assignments=["status=accepted"])
    git_commit(tmp_repo, "decision branch")
    git_checkout(tmp_repo, "main")
    _run_git(tmp_repo, "merge", "cr/a")
    assert cr_show(ws_of(tmp_repo), created.id).effective == "accepted"

    git_checkout(tmp_repo, "impl", new=True)
    bump_doc(tmp_repo, DOC, "# X\n\nImplemented.\n")
    introduced = create_document(
        ws_of(tmp_repo), type="user-story", title="Introduced", cr=created.id
    )
    cr_set(ws_of(tmp_repo), cr_id=created.id, assignments=["status=implemented"])
    git_commit(tmp_repo, "implementation merged")
    git_checkout(tmp_repo, "main")
    _run_git(tmp_repo, "merge", "impl")
    show = cr_show(ws_of(tmp_repo), created.id)
    assert show.effective == "implemented"
    assert [row.doc_id for row in show.introduces] == [introduced.id]
    # effective implemented: drift is no longer evaluated (§9.6)
    assert not of_code(validate_workspace(ws_of(tmp_repo)), "W-CR-BASE-DRIFT")


def test_workflow_single_pr(tmp_repo: Path) -> None:
    require_git(tmp_repo)
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2, title="X", text="# X\n\nBody.\n")
    git_commit(tmp_repo, "X at v2")
    git_checkout(tmp_repo, "single", new=True)
    created = cr_new(ws_of(tmp_repo), title="Change X", scope=[DOC])
    cr_set(ws_of(tmp_repo), cr_id=created.id, assignments=["status=accepted"])
    bump_doc(tmp_repo, DOC, "# X\n\nImplemented.\n")
    create_document(
        ws_of(tmp_repo), type="user-story", title="Introduced", cr=created.id
    )
    cr_set(ws_of(tmp_repo), cr_id=created.id, assignments=["status=implemented"])
    findings = validate_workspace(ws_of(tmp_repo))
    assert not of_code(findings, "W-CR-MODIFIED-AFTER-DECISION")
    assert not of_code(findings, "W-CR-BASE-DRIFT")
    # not merged yet: no effective status on the baseline
    assert cr_show(ws_of(tmp_repo), created.id).effective == "none"
    git_commit(tmp_repo, "single PR merged")
    git_checkout(tmp_repo, "main")
    _run_git(tmp_repo, "merge", "single")
    assert cr_show(ws_of(tmp_repo), created.id).effective == "implemented"


# --------------------------------------------------------------------------
# remaining decision-history edge cases
# --------------------------------------------------------------------------


def test_status_issues_empty_and_mismatch(tmp_repo: Path) -> None:
    from gregraph.core.changes import status_issues

    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo, decisions=[])
    assert status_issues(read_cr(tmp_repo, cr_id))
    cr = read_cr(tmp_repo, cr_id)
    cr.status = "implemented"
    cr.decisions = [Decision(status="open", at=CREATED, by=None, at_version=1)]
    write_sidecar(tmp_repo / "changes" / f"{cr_id}.json", cr)
    issues = status_issues(read_cr(tmp_repo, cr_id))
    assert any("differs" in issue.message for issue in issues)


# --------------------------------------------------------------------------
# v1 grace period (AGENT_READINESS §3.3, AGENT-012)
# --------------------------------------------------------------------------


def test_document_effective_version_grace(tmp_repo: Path) -> None:
    """An uncommitted ``v1`` document stays effectively at 1 (AGENT-012)."""
    from gregraph.core.changes import document_effective_version

    require_git(tmp_repo)
    setup_repo(tmp_repo)
    doc_id = make_doc(tmp_repo, "AAAAAA")
    ws = ws_of(tmp_repo)
    assert document_effective_version(ws, doc_id) == 1
    write_doc_body(tmp_repo, doc_id, "# First document\n\nEdited.\n")
    ws = ws_of(tmp_repo)
    assert document_effective_version(ws, doc_id) == 1  # populated in place
    git_commit(tmp_repo, "initial")
    write_doc_body(tmp_repo, doc_id, "# First document\n\nEdited again.\n")
    ws = ws_of(tmp_repo)
    assert document_effective_version(ws, doc_id) == 2  # grace ended (AGENT-013)


def test_document_effective_version_degraded_bumps(tmp_repo: Path) -> None:
    """Degraded mode has no grace period (AGENT-014)."""
    from gregraph.core.changes import document_effective_version

    setup_repo(tmp_repo)
    doc_id = make_doc(tmp_repo, "AAAAAA")
    ws = ws_of(tmp_repo, git=False)
    assert document_effective_version(ws, doc_id) == 1
    write_doc_body(tmp_repo, doc_id, "# First document\n\nEdited.\n")
    ws = ws_of(tmp_repo, git=False)
    assert document_effective_version(ws, doc_id) == 2


def test_cr_effective_version_grace(tmp_repo: Path) -> None:
    """An uncommitted ``v1`` CR is populated at 1 (§3.3 edge cases)."""
    from gregraph.core.changes import effective_cr_version

    require_git(tmp_repo)
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo)
    assert effective_cr_version(ws, cr_id) == 1
    write_body(tmp_repo / "changes" / f"{cr_id}.md", "# Raise the limit\n\nEdited.\n")
    ws = ws_of(tmp_repo)
    assert effective_cr_version(ws, cr_id) == 1
    git_commit(tmp_repo, "cr")
    write_body(tmp_repo / "changes" / f"{cr_id}.md", "# Raise the limit\n\nAgain.\n")
    ws = ws_of(tmp_repo)
    assert effective_cr_version(ws, cr_id) == 2


def test_effective_version_from_in_grace_flag(tmp_repo: Path) -> None:
    from gregraph.core.changes import effective_version_from

    setup_repo(tmp_repo)
    cr = read_cr(tmp_repo, make_cr(tmp_repo))
    body = "# Raise the limit\n\nBody.\n"
    assert effective_version_from(cr, body) == 1  # unchanged content
    assert effective_version_from(cr, "# Other\n", in_grace=True) == 1
    assert effective_version_from(cr, "# Other\n") == 2  # no grace flag
    # a missing body is never a grace case
    assert effective_version_from(cr, None, in_grace=True) == 2
    cr2 = read_cr(tmp_repo, make_cr(tmp_repo, "DDDDDD", version=3))
    assert effective_version_from(cr2, "# Other\n", in_grace=True) == 4


# --------------------------------------------------------------------------
# rich cr payloads (AGENT_READINESS §2.4.4)
# --------------------------------------------------------------------------


def test_cr_new_sections_and_rich_result(tmp_repo: Path) -> None:
    add_template(
        tmp_repo,
        "change-request",
        sections=[
            {"heading": "Motivation", "required": True, "placeholder": "Explain."},
            {"heading": "Notes", "required": False, "placeholder": ""},
        ],
        body="# {{ title }}\n\n## Motivation\n*Explain.*\n\n## Notes\n",
    )
    make_doc(tmp_repo, "AAAAAA")
    ws = ws_of(tmp_repo, git=False)
    result = cr_new(ws, title="Raise the limit", sections=[("Motivation", "Why.")])
    text = read_body(tmp_repo / "changes" / f"{result.id}.md")
    assert result.body_text == text
    assert [section.heading for section in result.sections] == ["Motivation", "Notes"]
    assert "## Motivation\n\nWhy." in text
    assert result.sidecar_model is not None
    assert result.sidecar_model.id == result.id
    with pytest.raises(OperationRefused) as excinfo:
        cr_new(ws, title="T", sections=[("Bogus", "x")])
    finding = excinfo.value.finding
    assert finding.code == "E-SECTION-UNKNOWN"
    assert finding.details is not None and "template_sections" in finding.details
    assert not list((tmp_repo / "changes").glob("*.md"))[1:]


def test_cr_new_strict_refuses_unfilled_required(tmp_repo: Path) -> None:
    add_template(
        tmp_repo,
        "change-request",
        sections=[
            {"heading": "Motivation", "required": True, "placeholder": "Explain."},
        ],
        body="# {{ title }}\n\n## Motivation\n*Explain.*\n",
    )
    ws = ws_of(tmp_repo, git=False)
    before = sorted(p.name for p in (tmp_repo / "changes").iterdir())
    with pytest.raises(OperationRefused) as excinfo:
        cr_new(ws, title="T", strict=True)
    assert excinfo.value.finding.code == "E-SECTION-REQUIRED-EMPTY"
    assert sorted(p.name for p in (tmp_repo / "changes").iterdir()) == before
    ok = cr_new(ws, title="T", sections=[("Motivation", "Why.")], strict=True)
    assert read_cr(tmp_repo, ok.id).version == 1


def test_scope_add_remove_rich_fields(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA")
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    added = cr_scope_add(ws, cr_id=cr_id, target=DOC)
    assert added.added == ScopeEntry(id=DOC, intent="modify", base_version=1)
    removed = cr_scope_remove(ws, cr_id=cr_id, target=DOC)
    assert removed.removed == DOC
    assert removed.scope == ()


def test_cr_set_applied_keys(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    result = cr_set(
        ws, cr_id=cr_id, assignments=["branch=cr/a", "tags=a,b", "extra.k=v"]
    )
    assert result.applied == {"branch": "cr/a", "tags": ["a", "b"], "extra.k": "v"}
    result = cr_set(ws, cr_id=cr_id, assignments=["status=accepted", "extra.k="])
    assert result.applied["status"] == "accepted"
    assert result.applied["extra.k"] is None
    assert result.decision is not None


def test_cr_reanalyze_updated_entries(tmp_repo: Path) -> None:
    from gregraph.core.changes import CrScopeUpdate

    setup_repo(tmp_repo)
    make_doc(tmp_repo, "AAAAAA", version=2)
    cr_id = make_cr(
        tmp_repo, scope=[ScopeEntry(id=DOC, intent="supersede", base_version=1)]
    )
    ws = ws_of(tmp_repo, git=False)
    result = cr_reanalyze(ws, cr_id=cr_id)
    assert result.updated == (
        CrScopeUpdate(
            id=DOC, intent="supersede", old_base_version=1, new_base_version=2
        ),
    )
    again = cr_reanalyze(ws, cr_id=cr_id)
    assert again.updated == ()
    assert not again.changed


def test_cr_show_carries_body(tmp_repo: Path) -> None:
    setup_repo(tmp_repo)
    cr_id = make_cr(tmp_repo)
    ws = ws_of(tmp_repo, git=False)
    result = cr_show(ws, cr_id)
    assert result.body == read_body(tmp_repo / "changes" / f"{cr_id}.md")
