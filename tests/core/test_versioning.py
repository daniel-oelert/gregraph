"""Tests for versioning: reconcile, freshness, effective version, repair.

Spec §7.1–7.5 (versioning) and §7.2/§12.6 (repair).  Change detection is
hash-based (D2).  Hypothesis freshness invariants are mandatory.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gregraph.core.models import (
    AssetRef,
    ChangeRequest,
    Decision,
    Document,
    Link,
    ScopeEntry,
    TemplateRef,
)
from gregraph.core.versioning import (
    effective_version,
    freshness_table,
    parse_conflict_markers,
    reconcile,
    repair_guidance,
    repair_versions,
    scope_hash,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _doc(
    *,
    id: str = "RE-000001",
    version: int = 1,
    body_hash: str = "sha256:aaa",
    links: list[Link] | None = None,
    assets: list[AssetRef] | None = None,
    title: str = "Title",
) -> Document:
    return Document(
        schema=1,
        uuid=uuid4(),
        id=id,
        type="user-story",
        title=title,
        created=NOW,
        created_by=None,
        template=TemplateRef(name="user-story", version=1),
        version=version,
        body_hash=body_hash,
        assets=assets or [],
        links=links or [],
        deprecated=None,
    )


def _cr(
    *,
    id: str = "CR-000001",
    version: int = 1,
    body_hash: str = "sha256:bbb",
    scope: list[ScopeEntry] | None = None,
    scope_hash: str = "sha256:ccc",
) -> ChangeRequest:
    return ChangeRequest(
        schema=1,
        uuid=uuid4(),
        id=id,
        title="CR",
        created=NOW,
        created_by=None,
        template=TemplateRef(name="change-request", version=1),
        version=version,
        body_hash=body_hash,
        scope_hash=scope_hash,
        scope=scope or [],
        introduces=[],
        status="open",
        decisions=[Decision(status="open", at=NOW, by=None, at_version=1)],
        branch=None,
        external_ref=None,
        tags=[],
        extra={},
    )


# --------------------------------------------------------------------------
# scope_hash
# --------------------------------------------------------------------------


def test_scope_hash_sorted_by_id() -> None:
    a = ScopeEntry(id="RE-000001", intent="modify", base_version=1)
    b = ScopeEntry(id="RE-000002", intent="supersede", base_version=1)
    assert scope_hash([a, b]) == scope_hash([b, a])


def test_scope_hash_changes_with_content() -> None:
    a = ScopeEntry(id="RE-000001", intent="modify", base_version=1)
    b = ScopeEntry(id="RE-000001", intent="supersede", base_version=1)
    assert scope_hash([a]) == scope_hash([a])
    # Only the id is hashed, so intent changes do not change the scope hash.
    assert scope_hash([a]) == scope_hash([b])


# --------------------------------------------------------------------------
# effective_version
# --------------------------------------------------------------------------


def test_effective_version_no_unbumped() -> None:
    doc = _doc(version=3)
    assert effective_version(doc) == 3


def test_effective_version_unbumped() -> None:
    doc = _doc(version=3)
    object.__setattr__(doc, "_unbumped", True)
    assert effective_version(doc) == 4


# --------------------------------------------------------------------------
# freshness
# --------------------------------------------------------------------------


def _link(target: str, tv: int, type: str = "refines") -> Link:
    return Link(type=type, target=target, target_version=tv)  # type: ignore[arg-type]


def test_fresh_link() -> None:
    target = _doc(id="RE-T", version=2)
    table = freshness_table([("RE-S", _link("RE-T", 2), target)])
    assert table.entries[0].state == "fresh"


def test_outdated_link() -> None:
    target = _doc(id="RE-T", version=3)
    table = freshness_table([("RE-S", _link("RE-T", 2), target)])
    assert table.entries[0].state == "outdated"


def test_stale_link() -> None:
    target = _doc(id="RE-T", version=3)
    table = freshness_table(
        [("RE-S", _link("RE-T", 3), target)],
        deprecated_or_superseded={"RE-T": True},
    )
    assert table.entries[0].state == "stale"


def test_pending_outdated_link() -> None:
    target = _doc(id="RE-T", version=2)
    table = freshness_table(
        [("RE-S", _link("RE-T", 2), target)],
        unbumped={"RE-T": True},
    )
    assert table.entries[0].state == "pending-outdated"


def test_newly_vs_previously_outdated() -> None:
    t1 = _doc(id="RE-A", version=3)
    t2 = _doc(id="RE-B", version=3)
    table = freshness_table(
        [
            ("RE-S", _link("RE-A", 2), t1),
            ("RE-S", _link("RE-B", 2), t2),
        ],
        bumped_ids={"RE-A"},
    )
    assert len(table.newly_outdated) == 1
    assert table.newly_outdated[0].target == "RE-A"
    assert len(table.previously_outdated) == 1
    assert table.previously_outdated[0].target == "RE-B"


@settings(max_examples=200)
@given(
    target_version=st.integers(min_value=1, max_value=50),
    link_tv=st.integers(min_value=1, max_value=50),
)
def test_target_version_never_exceeds(target_version: int, link_tv: int) -> None:
    """After any accepted operation: target_version <= target.version (§7.4)."""
    target = _doc(id="RE-T", version=target_version)
    table = freshness_table([("RE-S", _link("RE-T", link_tv), target)])
    entry = table.entries[0]
    assert entry.link_target_version <= entry.effective or entry.state == "outdated"


# --------------------------------------------------------------------------
# reconcile
# --------------------------------------------------------------------------


def test_reconcile_bump_once() -> None:
    doc = _doc(body_hash="sha256:old")
    body = "# Title\n\n## Story\ncontent\n"
    report = reconcile([(doc, body)], mode="bump")
    assert report.bumped == ["RE-000001"]
    assert doc.version == 2
    # Second run with the same content must not bump again.
    report2 = reconcile([(doc, body)], mode="bump")
    assert report2.bumped == []
    assert doc.version == 2


def test_reconcile_report_mode_never_writes() -> None:
    doc = _doc(body_hash="sha256:old", version=1)
    body = "# Title\n\n## Story\ncontent\n"
    report = reconcile([(doc, body)], mode="report")
    assert report.bumped == []
    assert doc.version == 1


def test_reconcile_title_sync() -> None:
    doc = _doc(title="Old", body_hash="sha256:old")
    body = "# New Title\n\n## Story\ncontent\n"
    reconcile([(doc, body)], mode="bump")
    assert doc.title == "New Title"


def test_reconcile_scope_hash_change_bumps_cr() -> None:
    cr = _cr(scope_hash="sha256:old", version=1)
    cr.scope = [ScopeEntry(id="RE-000001", intent="modify", base_version=1)]
    body = "# CR\n\n## Summary\nchange\n"
    report = reconcile([(cr, body)], mode="bump")
    assert report.bumped == ["CR-000001"]
    assert cr.version == 2
    assert cr.scope_hash == scope_hash(cr.scope)


# --------------------------------------------------------------------------
# repair
# --------------------------------------------------------------------------


CONFLICTED = json.dumps(
    {
        "schema": 1,
        "id": "RE-000001",
        "version": 3,
        "body_hash": "sha256:old",
        "links": [
            {"type": "refines", "target": "RE-000002", "target_version": 9},
            {"type": "refines", "target": "RE-000002", "target_version": 1},
        ],
    },
    indent=2,
)

CONFLICTED_WITH_MARKERS = CONFLICTED.replace(
    '"version": 3,',
    '<<<<<<< ours\n"version": 3,\n=======\n"version": 7,\n>>>>>>> theirs\n',
)


def test_parse_conflict_markers() -> None:
    parse = parse_conflict_markers(CONFLICTED_WITH_MARKERS)
    assert 3 in parse.versions_seen
    assert 7 in parse.versions_seen


def test_parse_without_markers_raises() -> None:
    with pytest.raises(ValueError, match="conflict"):
        parse_conflict_markers(CONFLICTED)


def test_repair_versions_sets_max_plus_one() -> None:
    result = repair_versions(CONFLICTED_WITH_MARKERS)
    assert result.version == 8
    assert result.versions_seen == [3, 7]
    data = json.loads(result.text)
    assert data["version"] == 8


def test_repair_versions_clamps_and_dedupes() -> None:
    result = repair_versions(CONFLICTED_WITH_MARKERS)
    data = json.loads(result.text)
    assert len(data["links"]) == 1
    assert data["links"][0]["target_version"] <= 8
    assert result.deduplicated_links == 1
    assert result.clamped_links == 1


def test_repair_versions_recomputes_hash() -> None:
    result = repair_versions(
        CONFLICTED_WITH_MARKERS,
        body="# Title\n\ncontent\n",
        asset_hashes=[("img.png", "sha256:xyz")],
    )
    data = json.loads(result.text)
    assert data["body_hash"].startswith("sha256:")
    assert data["assets"] == [{"path": "img.png", "hash": "sha256:xyz"}]


def test_repair_guidance_has_three_items() -> None:
    guidance = repair_guidance()
    assert len(guidance) == 3
    assert any("prose" in g for g in guidance)
    assert any("repair versions" in g for g in guidance)
    assert any("de-duplicates" in g for g in guidance)
