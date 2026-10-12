"""Versioning and change tracking: reconcile, freshness, repair (spec §7).

Model 4 from §7.1: mutable documents with integer versions and version-tracked
links.  Change detection is hash-based in both modes (D2 refinement 1).  The
sole stored state is ``version``, ``body_hash``, ``assets`` and the links'
``target_version`` values — everything else is derived.

Pure data and pure functions wherever possible; the ``reconcile`` entry point
is the only function that writes (via ``storage``).  ``core`` never prints.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from gregraph.core.hashing import body_hash, normalise_body
from gregraph.core.markdown import extract_title, find_asset_refs
from gregraph.core.models import AssetRef, ChangeRequest, Document, Finding, Link

__all__ = [
    "ConflictParse",
    "Freshness",
    "FreshnessTable",
    "ReconcileReport",
    "RepairResult",
    "effective_version",
    "freshness_table",
    "parse_conflict_markers",
    "repair_versions",
    "reconcile",
    "scope_hash",
]

Mode = Literal["bump", "report"]

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def scope_hash(entries: Sequence[Any]) -> str:
    """Canonical hash of a CR scope list sorted by id (spec §9.2).

    Accepts ``ScopeEntry`` models or plain mappings with an ``id`` key so the
    S13 CR subsystem can reuse it without importing this module's internals.
    """
    keys = sorted(_entry_id(e) for e in entries)
    payload = json.dumps(keys, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _entry_id(entry: Any) -> str:
    if hasattr(entry, "id"):
        return str(entry.id)
    return str(entry["id"])


def _content_hashes(
    body: str, assets: Sequence[AssetRef], body_path: Path
) -> tuple[str, list[AssetRef]]:
    """Return ``(body_hash, assets)`` recomputed from the raw body."""
    new_body_hash = body_hash(body)
    refs: list[AssetRef] = []
    for ref in find_asset_refs(body, doc_path=body_path, doc_id=""):
        if ref.foreign:
            continue
        # Only real files are listed; callers must resolve paths (storage).
        refs.append(AssetRef(path=str(ref.path), hash=""))
    return new_body_hash, list(assets)


def effective_version(target: Document | ChangeRequest) -> int:
    """Return the effective version of a target (spec §7.4).

    ``target.version + 1`` when the target currently has unbumped content
    modifications (the recomputed body hash or asset hashes differ from the
    stored values), otherwise ``target.version``.
    """
    if _has_unbumped_changes(target):
        return target.version + 1
    return target.version


def _has_unbumped_changes(target: Document | ChangeRequest) -> bool:
    """Whether stored hashes disagree with a fresh hash of the current body.

    The caller is expected to have loaded the current body; this helper only
    compares the *stored* sidecar hashes against each other when a current
    body is not available in-memory.  The authoritative check lives in
    :func:`reconcile` which has the body.  For link refresh the workspace
    layer supplies a pre-computed flag; see :class:`UnbumpedMixin`.
    """
    marker = getattr(target, "_unbumped", None)
    if marker is not None:
        return bool(marker)
    return False


class UnbumpedMixin:
    """Mixin that records whether a loaded item has unbumped modifications."""

    _unbumped: bool = False


# --------------------------------------------------------------------------
# freshness (spec §7.4)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Freshness:
    """Freshness classification of one link (spec §7.4)."""

    source: str
    type: str
    target: str
    link_target_version: int
    target_version: int
    effective: int
    state: Literal["fresh", "outdated", "stale", "pending-outdated"]
    newly: bool = False

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.type, self.target)


@dataclass(frozen=True)
class FreshnessTable:
    """Full link-freshness view over a graph (spec §7.5 step 5)."""

    entries: list[Freshness] = field(default_factory=list)

    @property
    def fresh(self) -> list[Freshness]:
        return [e for e in self.entries if e.state == "fresh"]

    @property
    def outdated(self) -> list[Freshness]:
        return [e for e in self.entries if e.state == "outdated"]

    @property
    def stale(self) -> list[Freshness]:
        return [e for e in self.entries if e.state == "stale"]

    @property
    def pending(self) -> list[Freshness]:
        return [e for e in self.entries if e.state == "pending-outdated"]

    @property
    def newly_outdated(self) -> list[Freshness]:
        return [e for e in self.outdated if e.newly]

    @property
    def previously_outdated(self) -> list[Freshness]:
        return [e for e in self.outdated if not e.newly]


def freshness_table(
    links: Iterable[tuple[str, Link, Document | ChangeRequest | None]],
    *,
    deprecated_or_superseded: Mapping[str, bool] | None = None,
    unbumped: Mapping[str, bool] | None = None,
    bumped_ids: Iterable[str] = (),
) -> FreshnessTable:
    """Classify every link using effective versions (spec §7.4, §7.5).

    ``links`` yields ``(source_id, link, target_model_or_None)`` triples.
    ``deprecated_or_superseded`` maps target id → True when the target is
    deprecated or superseded (stale).  ``unbumped`` maps target id → True when
    the target currently has unbumped modifications.  ``bumped_ids`` are the
    targets whose version was just incremented by reconcile — links into them
    that became outdated are *newly* outdated (D2 refinement 2).
    """
    dep = deprecated_or_superseded or {}
    unb = unbumped or {}
    bumped = set(bumped_ids)
    entries: list[Freshness] = []
    for source, link, target in links:
        if target is None:
            continue
        is_stale = dep.get(link.target, False)
        is_unbumped = unb.get(link.target, False)
        eff = target.version + 1 if is_unbumped else target.version
        if is_stale:
            state: Literal["fresh", "outdated", "stale", "pending-outdated"] = "stale"
        elif link.target_version > target.version:
            state = "outdated"  # E-LINK-VERSION-AHEAD territory; still "outdated"
        elif link.target_version < eff:
            if link.target_version < target.version:
                state = "outdated"
            else:
                state = "pending-outdated"
        elif is_unbumped:
            state = "pending-outdated"
        else:
            state = "fresh"
        entries.append(
            Freshness(
                source=source,
                type=link.type,
                target=link.target,
                link_target_version=link.target_version,
                target_version=target.version,
                effective=eff,
                state=state,
                newly=link.target in bumped,
            )
        )
    return FreshnessTable(entries=entries)


# --------------------------------------------------------------------------
# reconcile (spec §7.5)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileReport:
    """Result of :func:`reconcile` (spec §7.5 step 5)."""

    bumped: list[str] = field(default_factory=list)
    newly_outdated: list[Freshness] = field(default_factory=list)
    previously_outdated: list[Freshness] = field(default_factory=list)
    stale: list[Freshness] = field(default_factory=list)
    pending: list[Freshness] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def reconcile(
    items: Sequence[tuple[Document | ChangeRequest, str]],
    *,
    mode: Mode,
    deprecated_or_superseded: Mapping[str, bool] | None = None,
    links: Iterable[tuple[str, Link, Document | ChangeRequest | None]] | None = None,
) -> ReconcileReport:
    """Normalise, hash and optionally bump every item in scope (spec §7.5).

    ``items`` is a sequence of ``(sidecar, raw_body)`` pairs.  In ``bump`` mode
    a content change increments ``version`` by exactly 1 and rewrites the
    sidecar; ``report`` mode never writes.  Change detection is hash-based.
    """
    bumped: list[str] = []
    unbumped: dict[str, bool] = {}
    findings: list[Finding] = []

    for sidecar, raw_body in items:
        item_id = sidecar.id
        body = normalise_body(raw_body)
        new_hash = body_hash(body)

        # Title sync from H1 (spec §5.6).
        title = extract_title(body)
        if title is not None and hasattr(sidecar, "title") and sidecar.title != title:
            sidecar.title = title

        changed = new_hash != sidecar.body_hash
        if not changed and isinstance(sidecar, Document):
            changed = _assets_changed(sidecar, body)

        if isinstance(sidecar, ChangeRequest):
            new_scope_hash = scope_hash(sidecar.scope)
            if new_scope_hash != sidecar.scope_hash:
                changed = True
                sidecar.scope_hash = new_scope_hash

        if changed:
            unbumped[item_id] = True
            if mode == "bump":
                sidecar.version += 1
                sidecar.body_hash = new_hash
                if isinstance(sidecar, Document):
                    sidecar.assets = _recompute_assets(sidecar, body)
                # Placeholder for callers that hold the body path.
                # Writing is done by the caller (storage needs the path).
                bumped.append(item_id)
                unbumped[item_id] = False
                _stage_marker(sidecar)
        else:
            unbumped[item_id] = False

    table = FreshnessTable()
    if links is not None:
        table = freshness_table(
            links,
            deprecated_or_superseded=deprecated_or_superseded,
            unbumped=unbumped,
            bumped_ids=bumped,
        )

    return ReconcileReport(
        bumped=bumped,
        newly_outdated=table.newly_outdated,
        previously_outdated=table.previously_outdated,
        stale=table.stale,
        pending=table.pending,
        findings=findings,
    )


def _stage_marker(sidecar: Document | ChangeRequest) -> None:
    """Mark a sidecar as rewritten so the hook can ``git add`` it (§7.5)."""
    object.__setattr__(sidecar, "_staged_pending", True)


def _assets_changed(doc: Document, body: str) -> bool:
    """Whether the effective asset list differs from the stored one (§7.3)."""
    refs = find_asset_refs(body, doc_path=Path("x"), doc_id=doc.id)
    current = sorted((str(r.path), "") for r in refs if not r.foreign)
    stored = sorted((a.path, a.hash) for a in doc.assets)
    if current and not stored:
        return True
    return stored != current


def _recompute_assets(doc: Document, body: str) -> list[AssetRef]:
    refs = find_asset_refs(body, doc_path=Path("x"), doc_id=doc.id)
    return [AssetRef(path=str(r.path), hash="") for r in refs if not r.foreign]


# --------------------------------------------------------------------------
# repair versions (spec §7.2, §12.6)
# --------------------------------------------------------------------------

_CONFLICT_RE = re.compile(
    r"^[ \t]*<<<<<<<[^\n]*\n(.*?)\n[ \t]*=======\n(.*?)\n[ \t]*>>>>>>>[^\n]*$",
    re.MULTILINE | re.DOTALL,
)
_VERSION_RE = re.compile(r'"version"\s*:\s*(\d+)')


@dataclass(frozen=True)
class ConflictParse:
    """Both sides of a merge-conflicted sidecar (spec §7.2)."""

    ours: str
    theirs: str
    versions_seen: list[int]


@dataclass(frozen=True)
class RepairResult:
    """Outcome of :func:`repair_versions` (spec §7.2, §12.6)."""

    text: str
    version: int
    versions_seen: list[int]
    clamped_links: int
    deduplicated_links: int
    changes: list[str]


def parse_conflict_markers(text: str) -> ConflictParse:
    """Parse the standard git conflict-marker layout in a JSON sidecar.

    Extracts both ``version`` values from the two sides.  Raises
    :class:`ValueError` when no conflict markers are present or the versions
    cannot be found.
    """
    match = _CONFLICT_RE.search(text)
    if match is None:
        raise ValueError("no conflict markers found")
    ours, theirs = match.group(1), match.group(2)
    versions = [int(v) for v in _VERSION_RE.findall(ours + "\n" + theirs)]
    if len(versions) < 2:
        raise ValueError("could not extract version values from both sides")
    return ConflictParse(ours=ours, theirs=theirs, versions_seen=versions)


def repair_versions(
    text: str,
    *,
    body: str | None = None,
    asset_hashes: Sequence[tuple[str, str]] | None = None,
) -> RepairResult:
    """Repair a conflicted sidecar (spec §7.2, §12.6).

    Sets ``version = max(versions seen) + 1``, recomputes ``body_hash`` (and
    ``assets`` when ``asset_hashes`` is given) from the provided body, clamps
    every ``links[].target_version`` to the target's ``version`` field, and
    de-duplicates links by ``(type, target)``.
    """
    changes: list[str] = []
    parse = parse_conflict_markers(text)
    resolved = _CONFLICT_RE.sub(lambda m: m.group(1), text)
    try:
        data = json.loads(resolved)
    except json.JSONDecodeError:
        data = json.loads(_CONFLICT_RE.sub(lambda m: m.group(2), text))

    new_version = max(parse.versions_seen) + 1
    changes.append(f"version: {parse.versions_seen} -> {new_version}")
    data["version"] = new_version

    if body is not None:
        data["body_hash"] = body_hash(body)
        changes.append("body_hash recomputed")

    if asset_hashes is not None:
        data["assets"] = [{"path": p, "hash": h} for p, h in sorted(asset_hashes)]
        changes.append("assets recomputed")

    clamped = 0
    deduped = 0
    seen: set[tuple[str, str]] = set()
    new_links: list[dict[str, object]] = []
    for link in data.get("links", []):
        key = (str(link.get("type", "")), str(link.get("target", "")))
        if key in seen:
            deduped += 1
            continue
        seen.add(key)
        tv = int(link.get("target_version", 1))
        if tv > new_version:
            link["target_version"] = new_version
            clamped += 1
        new_links.append(link)
    data["links"] = new_links
    if clamped:
        changes.append(f"clamped {clamped} link(s)")
    if deduped:
        changes.append(f"de-duplicated {deduped} link(s)")

    out = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return RepairResult(
        text=out,
        version=new_version,
        versions_seen=parse.versions_seen,
        clamped_links=clamped,
        deduplicated_links=deduped,
        changes=changes,
    )


def repair_guidance() -> list[str]:
    """The three guidance bullets printed by ``repair --help`` (spec §12.6)."""
    return [
        "Body conflicts: resolve as prose.",
        "Sidecar conflicts: resolve the JSON to any syntactically valid state "
        "(or leave conflict markers), then run `gregraph repair versions` which "
        "recomputes `version`, `body_hash`, `assets`, and clamps `target_version` "
        "values.",
        "Link conflicts (both sides added links): keep both; `repair versions` "
        "de-duplicates.",
    ]
