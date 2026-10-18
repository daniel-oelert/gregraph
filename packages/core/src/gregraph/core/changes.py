"""Change requests: scope, base versions, drift, origin, status (spec §9, §16.1).

CR files and sidecar per §9.2; status/decisions/effective status per §9.3;
drift and implementation checks per §9.6. CRs are outside the graph (r0.2):
scope entries are not edges and never affect cycle detection, freshness or
export.

Content hashing contract (§9.2, D14): a CR's content is its normalised body
plus its scope. :func:`content_hashes` returns exactly the two inputs
``reconcile`` compares (``body_hash`` and ``versioning.scope_hash``); the
D14-excluded fields — ``status``, ``decisions``, ``introduces``, ``branch``,
``external_ref``, ``tags``, ``extra`` — are never hashed. Scope mutations
(:func:`scope_add`, :func:`scope_remove`, :func:`reanalyze`) record the
content change with one ``version`` bump; see docs/backlog.md for the
``scope_hash`` coverage note (S9 hashes the sorted id list only, so
``reanalyze`` bumps explicitly).

Baseline data (effective status, drift, base versions) comes from
:class:`BaselineView` — the ``files_at`` snapshot of the baseline branch,
loaded lazily and at most once per prefix (§9.6). ``core`` never prints.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import UUID

from gregraph.core.git import GitAdapter
from gregraph.core.hashing import asset_hash, body_hash, effective_content_changed
from gregraph.core.ids import CR_ABBREVIATION, generate_id, normalise_id
from gregraph.core.markdown import (
    extract_title,
    find_asset_refs,
    find_mentions,
    find_section,
    heading_matches,
    parse_sections,
    section_is_empty,
)
from gregraph.core.models import (
    ChangeRequest,
    CrStatus,
    Decision,
    Document,
    Finding,
    Identity,
    OperationRefused,
    ScopeEntry,
    ScopeIntent,
    TemplateRef,
    TemplateSection,
)
from gregraph.core.status import compute_status
from gregraph.core.storage import (
    change_paths,
    read_body,
    read_sidecar,
    templates_dir,
    write_body,
    write_sidecar,
)
from gregraph.core.templates import (
    LoadedTemplate,
    assemble_sections,
    check_required_sections,
    load_template_dir,
    render_template,
    resolve_section_inputs,
    resolve_template,
)
from gregraph.core.versioning import scope_hash as reconcile_scope_hash
from gregraph.core.workspace import Workspace

__all__ = [
    "ISSUE_CODES",
    "BaselineView",
    "CrDecisionResult",
    "CrListEntry",
    "CrListResult",
    "CrNewResult",
    "CrReanalyzeResult",
    "CrScopeResult",
    "CrScopeUpdate",
    "CrSetResult",
    "CrShowResult",
    "DriftEntry",
    "IntroducedState",
    "IntroductionResult",
    "ScopeState",
    "StatusIssue",
    "UnimplementedEntry",
    "content_changed",
    "content_hashes",
    "cr_findings",
    "decider_issues",
    "decide",
    "drift_entries",
    "effective_cr_version",
    "effective_status",
    "effective_version_from",
    "initial_decision",
    "list_changes",
    "modified_after_decision",
    "new_change_request",
    "origin_issues",
    "parse_scope_specs",
    "record_origin",
    "reaffirm",
    "reaffirm_cr",
    "reanalyze",
    "scope_add",
    "scope_remove",
    "set_cr_fields",
    "show_change",
    "status_issues",
    "transition_allowed",
    "unimplemented_entries",
]

SCOPE_INTENTS: Final[tuple[ScopeIntent, ...]] = ("modify", "supersede", "deprecate")
CR_STATUSES: Final[tuple[CrStatus, ...]] = (
    "open",
    "accepted",
    "rejected",
    "implemented",
)

#: §9.3 transition table; ``None`` is the ``(created)`` state. Same-status
#: appends (``reaffirm``) are not transitions and are handled separately.
ALLOWED_TRANSITIONS: Final[dict[str | None, tuple[str, ...]]] = {
    None: ("open",),
    "open": ("accepted", "rejected"),
    "accepted": ("implemented", "open"),
    "rejected": ("open",),
    "implemented": ("open",),
}

#: Every code :func:`cr_findings` can emit (spec §14). ``E-CR-DISABLED`` and
#: ``E-CR-CLOSED`` are refusal-only codes and are never emitted by ``validate``
#: (§9.1: existing CR files are still validated with CRs disabled).
ISSUE_CODES: Final[tuple[str, ...]] = (
    "E-CR-STATUS",
    "E-CR-SCOPE-TARGET",
    "E-CR-ORIGIN-MISSING",
    "E-CR-ORIGIN-MISMATCH",
    "E-MENTION-UNKNOWN",
    "W-CR-MODIFIED-AFTER-DECISION",
    "W-CR-DECIDER-UNKNOWN",
    "W-CR-BASE-DRIFT",
    "W-CR-IMPLEMENTED-UNCHANGED",
    "W-CR-MENTION-UNSCOPED",
    "E-TITLE-MISSING",
    "E-TEMPLATE-UNKNOWN",
    "W-TEMPLATE-DEPRECATED",
    "E-SECTION-REQUIRED-MISSING",
    "E-SECTION-REQUIRED-EMPTY",
    "W-SECTION-UNKNOWN",
    "W-SECTION-ORDER",
)

_TAG_PATTERN: Final = re.compile(r"[a-z0-9-]+")

#: ``cr set`` keys outside the allowed set map to the owning command (§13.6
#: pointer style). ``{id}`` is replaced with the CR id.
_CR_KEY_HINTS: Final[dict[str, tuple[str, str]]] = {
    "title": ("the title is the H1 of the Markdown body", "gregraph edit {id}"),
    "scope": ("scope is managed by cr scope add/remove", "gregraph cr scope add {id}"),
    "introduces": (
        "introduces is recorded by new --cr / supersede --cr",
        "gregraph cr list",
    ),
    "origin_cr": (
        "origin is recorded at creation with new --cr / supersede --cr",
        "gregraph cr list",
    ),
    "decisions": (
        "decisions are appended by cr set status and cr reaffirm",
        "gregraph cr set {id} status=STATUS",
    ),
    "version": ("versions are bumped by content changes", "gregraph sync --bump"),
    "body_hash": ("hashes are owned by the tool", "gregraph sync --bump"),
    "scope_hash": ("hashes are owned by the tool", "gregraph sync --bump"),
    "template": ("the pinned template changes with migrate", "gregraph template list"),
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _now() -> dt.datetime:
    """Current UTC time at second precision (spec §5.4 ``created``)."""
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _stamp(moment: dt.datetime) -> str:
    """ISO 8601 UTC with ``Z`` suffix (spec §5.4)."""
    return moment.isoformat().replace("+00:00", "Z")


def _refuse(
    code: str, subject: str, message: str, fix: str | None = None
) -> OperationRefused:
    return OperationRefused(
        Finding(code=code, severity="E", subject=subject, message=message, fix=fix)
    )


def require_enabled(workspace: Workspace, *, subject: str) -> None:
    """Refuse every ``cr`` command / ``--cr`` flag while disabled (§14)."""
    if not workspace.config.cr.enabled:
        raise _refuse(
            "E-CR-DISABLED",
            subject,
            "change requests are disabled in config.toml",
            "set cr.enabled = true in config.toml",
        )


def _resolve_cr(workspace: Workspace, raw: str) -> str:
    """Canonical change-request ID; refuses ``E-ID-UNKNOWN`` when absent."""
    resolved = normalise_id(
        raw, workspace.config.ids.prefix, known=workspace.index.changes
    )
    if resolved is None:
        raise _refuse(
            "E-ID-UNKNOWN",
            raw,
            f"no change request with id {raw!r}",
            "gregraph cr list",
        )
    return resolved


def _existing_ids(workspace: Workspace) -> set[str]:
    """Every ID in the shared document/CR ID space (spec §2, §4.2)."""
    return set(workspace.index.documents) | set(workspace.index.changes)


def _read_cr(workspace: Workspace, cr_id: str) -> ChangeRequest:
    """Read a CR sidecar fresh from disk (spec §9.2)."""
    return read_sidecar(
        workspace.root / workspace.index.changes[cr_id].sidecar, ChangeRequest
    )


def _write_cr(workspace: Workspace, cr: ChangeRequest) -> None:
    """Write a CR sidecar in canonical form (spec §9.2)."""
    write_sidecar(workspace.root / workspace.index.changes[cr.id].sidecar, cr)


def cr_body(workspace: Workspace, cr_id: str) -> str | None:
    """Current body text of a CR, or ``None`` when unreadable."""
    try:
        return read_body(workspace.root / workspace.index.changes[cr_id].body)
    except OSError:
        return None


def _document_unbumped(workspace: Workspace, document: Document, body: Path) -> bool:
    """Whether effective content differs from the stored hashes (§7.2, §7.3).

    Hash-based mirror of the operations layer's "modified, unbumped"
    computation; a missing body counts as modified.
    """
    try:
        text = read_body(workspace.root / body)
    except OSError:
        return True
    stored_assets = [(Path(asset.path), asset.hash) for asset in document.assets]
    current_assets: list[tuple[Path, str]] = []
    for ref in find_asset_refs(text, doc_path=body, doc_id=document.id):
        if ref.foreign:
            continue
        file = workspace.root / ref.path
        if file.is_file():
            current_assets.append(
                (Path(*ref.path.parts[2:]), asset_hash(file.read_bytes()))
            )
    return effective_content_changed(
        document.body_hash,
        stored_assets,
        body_hash(text),
        current_assets,
    )


def _doc_in_grace(workspace: Workspace, doc_id: str) -> bool:
    """Initial-grace state of a document (§3.3, AGENT-012).

    True while a ``v1`` document is absent from Git ``HEAD`` — untracked or
    staged-but-uncommitted: reconcile populates it in place and its effective
    version stays ``1`` (D-AGENT-3). Degraded mode has no commit step and
    therefore no grace period (AGENT-014).
    """
    if not workspace.git.is_repo():
        return False
    loaded = workspace.index.documents.get(doc_id)
    if loaded is None or loaded.model.version != 1:
        return False
    if not (workspace.root / loaded.body).is_file():
        return False
    return workspace.git.file_at("HEAD", loaded.body) is None


def document_effective_version(workspace: Workspace, doc_id: str) -> int:
    """Working-tree effective version of a document (spec §7.4, §3.3 rule 3)."""
    if _doc_in_grace(workspace, doc_id):
        return 1
    loaded = workspace.index.documents[doc_id]
    unbumped = _document_unbumped(workspace, loaded.model, loaded.body)
    return loaded.model.version + 1 if unbumped else loaded.model.version


# --------------------------------------------------------------------------
# content hashing contract (spec §9.2, D14)
# --------------------------------------------------------------------------


def scope_hash(entries: Sequence[ScopeEntry]) -> str:
    """Canonical scope hash — the exact input ``reconcile`` stores (§9.2).

    Delegates to :func:`gregraph.core.versioning.scope_hash` so the stored
    ``scope_hash`` field and the reconcile pass can never disagree.
    """
    return reconcile_scope_hash(entries)


def content_hashes(cr: ChangeRequest, body: str | bytes) -> tuple[str, str]:
    """The two stored hashes of a CR's content (§9.2): ``(body_hash, scope_hash)``.

    This is the hashing contract matching the ``reconcile`` inputs: a version
    bump is recorded when either differs from the stored pair. D14-excluded
    fields (``status``, ``decisions``, ``introduces``, ``branch``,
    ``external_ref``, ``tags``, ``extra``) are not hashed.
    """
    return body_hash(body), scope_hash(cr.scope)


def content_changed(cr: ChangeRequest, body: str | bytes) -> bool:
    """Whether the current body or scope differs from the stored hashes (§9.2)."""
    return content_hashes(cr, body) != (cr.body_hash, cr.scope_hash)


def _cr_in_grace(workspace: Workspace, cr: ChangeRequest, cr_id: str) -> bool:
    """Initial-grace state of a change request (§3.3 edge cases, AGENT-012).

    Same predicate as :func:`_doc_in_grace`: a ``v1`` CR whose body is absent
    from Git ``HEAD`` is being populated. Degraded mode has no grace period.
    """
    if not workspace.git.is_repo() or cr.version != 1:
        return False
    abs_body, _sidecar = change_paths(workspace.root, cr_id)
    rel_body = abs_body.relative_to(workspace.root)
    if not abs_body.is_file():
        return False
    return workspace.git.file_at("HEAD", rel_body) is None


def effective_version_from(
    cr: ChangeRequest, body: str | bytes | None, *, in_grace: bool = False
) -> int:
    """CR effective version (§7.4 rule): ``version + 1`` when content is pending.

    A missing body counts as modified, mirroring the document rule. A CR in
    the initial-grace state (uncommitted ``v1``, §3.3) stays at ``1`` while it
    is being populated; a missing body is not a grace case
    (``E-BODY-MISSING``, not a grace state).
    """
    if in_grace and cr.version == 1 and body is not None:
        return 1
    if body is None:
        return cr.version + 1
    return cr.version + 1 if content_changed(cr, body) else cr.version


def effective_cr_version(workspace: Workspace, cr_id: str) -> int:
    """Working-tree effective version of a CR (spec §7.4, §9.3 ``at_version``)."""
    cr = _read_cr(workspace, cr_id)
    return effective_version_from(
        cr, cr_body(workspace, cr_id), in_grace=_cr_in_grace(workspace, cr, cr_id)
    )


def _record_content_change(
    cr: ChangeRequest, body: str | None, *, force: bool = False
) -> bool:
    """Record one content change: ``version += 1`` and refresh the hashes.

    ``force`` records a change the id-list ``scope_hash`` cannot see (a
    ``reanalyze`` base-version update). Returns whether a change was recorded.
    """
    new_scope_hash = scope_hash(cr.scope)
    new_body_hash = body_hash(body) if body is not None else cr.body_hash
    changed = force or (new_body_hash, new_scope_hash) != (cr.body_hash, cr.scope_hash)
    if changed:
        cr.version += 1
        cr.body_hash = new_body_hash
        cr.scope_hash = new_scope_hash
    return changed


# --------------------------------------------------------------------------
# baseline view (spec §9.3, §9.6)
# --------------------------------------------------------------------------


class BaselineView:
    """Baseline-branch sidecar snapshot (spec §12.1 ``files_at``).

    Loaded lazily and at most once per prefix per instance; created per
    invocation by the CR checks and the ``cr`` operations. ``available`` is
    False without Git or without the baseline branch locally — degraded rules
    apply (effective status equals the proposed status, no drift).
    """

    def __init__(self, git: GitAdapter, branch: str) -> None:
        self._git = git
        self._branch = branch
        self._known: bool | None = None
        self._documents: dict[str, Document] | None = None
        self._changes: dict[str, ChangeRequest] | None = None

    @property
    def branch(self) -> str:
        return self._branch

    @property
    def available(self) -> bool:
        """Whether the baseline branch can be read (Git mode, branch present)."""
        if self._known is None:
            self._known = self._git.is_repo() and self._git.branch_exists(self._branch)
        return self._known

    def _parse[M: Any](self, prefix: Path, model: type[M]) -> dict[str, M]:
        if not self.available:
            return {}
        try:
            files = self._git.files_at(self._branch, prefix)
        except (OSError, subprocess.CalledProcessError):
            return {}
        parsed: dict[str, M] = {}
        for path, raw in files.items():
            if path.suffix != ".json":
                continue
            try:
                item = model.model_validate_json(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError):
                continue
            key = str(getattr(item, "id", path.stem))
            parsed[key] = item
        return parsed

    def documents(self) -> Mapping[str, Document]:
        """Baseline-branch document sidecars keyed by ID (loaded once)."""
        if self._documents is None:
            self._documents = self._parse(Path("documents"), Document)
        return self._documents

    def changes(self) -> Mapping[str, ChangeRequest]:
        """Baseline-branch CR sidecars keyed by ID (loaded once)."""
        if self._changes is None:
            self._changes = self._parse(Path("changes"), ChangeRequest)
        return self._changes

    def document_version(self, doc_id: str) -> int | None:
        """The target's version on the baseline branch, or ``None`` (§9.4)."""
        document = self.documents().get(doc_id)
        return document.version if document is not None else None


def effective_status(
    baseline: BaselineView, cr: ChangeRequest
) -> CrStatus | Literal["none"]:
    """Effective status of a CR (spec §9.3).

    The status in the CR's sidecar on the baseline branch, or ``none`` when the
    CR does not exist there. Without Git (or without the baseline branch) the
    effective status equals the proposed status.
    """
    if not baseline.available:
        return cr.status
    found = baseline.changes().get(cr.id)
    return found.status if found is not None else "none"


# --------------------------------------------------------------------------
# decisions and status (spec §9.3)
# --------------------------------------------------------------------------


def transition_allowed(current: CrStatus | None, new: CrStatus) -> bool:
    """Whether ``new`` follows ``current`` in the §9.3 state machine.

    ``current=None`` is the ``(created)`` state. Same-status appends
    (``reaffirm`` confirmations) are allowed: the table governs transitions.
    """
    if current is not None and new == current:
        return True
    return new in ALLOWED_TRANSITIONS.get(current, ())


def initial_decision(*, at: dt.datetime, by: Identity | None) -> Decision:
    """The decision recorded at creation (§9.3): ``open`` with ``at_version = 1``."""
    return Decision(status="open", at=at, by=by, at_version=1)


def decide(
    cr: ChangeRequest,
    status: CrStatus,
    *,
    at: dt.datetime,
    by: Identity | None,
    at_version: int,
) -> Decision:
    """Append a transition decision and set the proposed status (§9.3).

    Refuses ``E-CR-STATUS`` for an invalid transition; re-setting the current
    status is refused too — that is what ``reaffirm`` is for.
    """
    current = cr.status
    if status == current:
        raise _refuse(
            "E-CR-STATUS",
            cr.id,
            f"{cr.id} is already {status!r}; only transitions go through cr set",
            f"gregraph cr reaffirm {cr.id}",
        )
    if not transition_allowed(current, status):
        allowed = ", ".join(ALLOWED_TRANSITIONS.get(current, ())) or "none"
        raise _refuse(
            "E-CR-STATUS",
            cr.id,
            f"cannot transition {cr.id} from {current!r} to {status!r} "
            f"(allowed: {allowed})",
            f"gregraph cr set {cr.id} status=…",
        )
    decision = Decision(status=status, at=at, by=by, at_version=at_version)
    cr.decisions = [*cr.decisions, decision]
    cr.status = status
    return decision


def reaffirm(
    cr: ChangeRequest,
    *,
    at: dt.datetime,
    by: Identity | None,
    at_version: int,
) -> Decision:
    """Append a decision with the current status at the effective version (§9.3)."""
    decision = Decision(status=cr.status, at=at, by=by, at_version=at_version)
    cr.decisions = [*cr.decisions, decision]
    return decision


@dataclass(frozen=True, slots=True)
class StatusIssue:
    """One defect in a CR's decision history (spec §9.3 ``E-CR-STATUS``)."""

    message: str


def status_issues(cr: ChangeRequest) -> tuple[StatusIssue, ...]:
    """Decision-history defects behind ``E-CR-STATUS`` (spec §9.3).

    Reported when the history is empty (the initial ``open`` decision is
    mandatory at creation), when the first decision is not ``open``, when a
    transition outside the §9.3 table occurs, or when ``status`` differs from
    the last decision. Same-status repeats (``reaffirm``) are valid.
    """
    issues: list[StatusIssue] = []
    if not cr.decisions:
        issues.append(
            StatusIssue(
                "decision history is empty; creation records the initial open decision"
            )
        )
        return tuple(issues)
    first = cr.decisions[0]
    if first.status != "open":
        issues.append(
            StatusIssue(f"first decision is {first.status!r}, expected 'open'")
        )
    for previous, current in zip(cr.decisions, cr.decisions[1:], strict=False):
        if not transition_allowed(previous.status, current.status):
            issues.append(
                StatusIssue(
                    f"invalid transition {previous.status!r} → {current.status!r} "
                    f"in the decision history"
                )
            )
    last = cr.decisions[-1]
    if cr.status != last.status:
        issues.append(
            StatusIssue(
                f"status {cr.status!r} differs from the last decision {last.status!r}"
            )
        )
    return tuple(issues)


def modified_after_decision(cr: ChangeRequest, effective: int) -> bool:
    """Whether the CR changed after its last decision (spec §9.3).

    True when the last decision is not ``open`` and the CR's effective version
    exceeds that decision's ``at_version`` (scope is content, so scope changes
    count — §9.4).
    """
    if not cr.decisions:
        return False
    last = cr.decisions[-1]
    return last.status != "open" and effective > last.at_version


def decider_issues(cr: ChangeRequest, deciders: Sequence[str]) -> tuple[str, ...]:
    """``W-CR-DECIDER-UNKNOWN`` messages (spec §9.3; advisory).

    With ``cr.deciders`` non-empty, every decision other than the initial
    ``open`` must name a listed e-mail address.
    """
    if not deciders:
        return ()
    allowed = {address.lower() for address in deciders}
    issues: list[str] = []
    for index, decision in enumerate(cr.decisions):
        if index == 0 and decision.status == "open":
            continue
        author = decision.by.email if decision.by is not None else None
        if author is None or author.lower() not in allowed:
            shown = author if author is not None else "no author"
            issues.append(
                f"decision {decision.status!r} at {_stamp(decision.at)} by {shown} "
                f"is not one of cr.deciders"
            )
    return tuple(issues)


# --------------------------------------------------------------------------
# scope (spec §9.4)
# --------------------------------------------------------------------------


def parse_scope_specs(specs: Sequence[str]) -> tuple[tuple[str, ScopeIntent], ...]:
    """Parse ``TARGET[:INTENT]`` scope specs (spec §13.18 ``cr new --scope``)."""
    parsed: list[tuple[str, ScopeIntent]] = []
    for spec in specs:
        target, _, raw_intent = spec.partition(":")
        intent = raw_intent or "modify"
        if not target:
            raise ValueError(f"cannot parse scope spec {spec!r} (want TARGET[:INTENT])")
        if intent not in SCOPE_INTENTS:
            raise ValueError(
                f"unknown scope intent {intent!r} in {spec!r} "
                f"(want {', '.join(SCOPE_INTENTS)})"
            )
        parsed.append((target, intent))
    return tuple(parsed)


def _scope_target(workspace: Workspace, raw: str) -> str:
    """Resolve a scope target and enforce the §9.4 add-time liveness rules.

    The target must be an existing, live document — not a CR, not a glossary
    term, not superseded or deprecated. Violations refuse
    ``E-CR-SCOPE-TARGET``.
    """
    resolved = normalise_id(
        raw, workspace.config.ids.prefix, known=workspace.index.documents
    )
    if resolved is None:
        if raw.upper() in {key.upper() for key in workspace.index.changes}:
            detail = "names a change request, not a document"
        elif raw in workspace.index.terms:
            detail = "names a glossary term, not a document"
        else:
            detail = "is not an existing document"
        raise _refuse(
            "E-CR-SCOPE-TARGET",
            raw,
            f"scope target {raw!r} {detail}",
            "gregraph list",
        )
    document = workspace.index.documents[resolved].model
    if document.deprecated is not None:
        raise _refuse(
            "E-CR-SCOPE-TARGET",
            resolved,
            f"scope target {resolved} is deprecated in the working tree",
            "gregraph undeprecate " + resolved,
        )
    if workspace.graph.is_superseded(resolved):
        raise _refuse(
            "E-CR-SCOPE-TARGET",
            resolved,
            f"scope target {resolved} is superseded in the working tree",
            "gregraph list",
        )
    return resolved


def base_version_for(workspace: Workspace, baseline: BaselineView, doc_id: str) -> int:
    """``base_version`` of a new scope entry (spec §9.4).

    Git mode: the target's version on the baseline branch — the working-tree
    version may already contain this CR's own edits. A target absent from the
    baseline is new work and belongs in ``introduces``; the add refuses.
    Degraded mode: the target's effective working-tree version.
    """
    if baseline.available:
        version = baseline.document_version(doc_id)
        if version is None:
            raise _refuse(
                "E-CR-SCOPE-TARGET",
                doc_id,
                f"{doc_id} does not exist on baseline branch {baseline.branch!r}; "
                "new work is not scope — introduce it with `--cr` instead",
                "gregraph new … --cr CR",
            )
        return version
    return document_effective_version(workspace, doc_id)


def scope_target_issues(workspace: Workspace, cr: ChangeRequest) -> tuple[str, ...]:
    """``E-CR-SCOPE-TARGET`` messages as found in files (spec §9.4).

    Non-existent IDs, non-documents and duplicates. Liveness is not
    re-checked — ``supersede``/``deprecate`` intents legitimately make the
    target non-live.
    """
    documents = workspace.index.documents
    changes = workspace.index.changes
    terms = workspace.index.terms
    issues: list[str] = []
    seen: set[str] = set()
    for entry in cr.scope:
        if entry.id in seen:
            issues.append(f"scope lists {entry.id} more than once")
            continue
        seen.add(entry.id)
        if entry.id in documents:
            continue
        if entry.id in changes:
            issues.append(
                f"scope entry {entry.id} names a change request, not a document"
            )
        elif entry.id in terms:
            issues.append(
                f"scope entry {entry.id} names a glossary term, not a document"
            )
        else:
            issues.append(f"scope entry {entry.id} names no existing document")
    return tuple(issues)


# --------------------------------------------------------------------------
# drift and implementation checks (spec §9.6)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriftEntry:
    """One drifted scope entry (spec §9.6 ``W-CR-BASE-DRIFT``)."""

    id: str
    base_version: int
    baseline_version: int
    deprecated: bool
    superseded: bool

    @property
    def version_exceeds(self) -> bool:
        return self.baseline_version > self.base_version


def _superseded_ids(documents: Mapping[str, Document]) -> set[str]:
    """IDs with an inbound ``supersedes`` edge in the baseline snapshot."""
    superseded: set[str] = set()
    for document in documents.values():
        for link in document.links:
            if link.type == "supersedes":
                superseded.add(link.target)
    return superseded


def drift_entries(baseline: BaselineView, cr: ChangeRequest) -> tuple[DriftEntry, ...]:
    """Drifted scope entries (spec §9.6).

    Git mode only, and only while the CR's **effective** status is ``open`` or
    ``accepted``: the target's baseline version exceeds ``base_version``, or
    the target is superseded or deprecated on the baseline branch (those do
    not bump the target's version).
    """
    if not baseline.available:
        return ()
    if effective_status(baseline, cr) not in ("open", "accepted"):
        return ()
    documents = baseline.documents()
    superseded = _superseded_ids(documents)
    drifted: list[DriftEntry] = []
    for entry in cr.scope:
        document = documents.get(entry.id)
        if document is None:
            continue
        deprecated = document.deprecated is not None
        is_superseded = entry.id in superseded
        if document.version > entry.base_version or deprecated or is_superseded:
            drifted.append(
                DriftEntry(
                    id=entry.id,
                    base_version=entry.base_version,
                    baseline_version=document.version,
                    deprecated=deprecated,
                    superseded=is_superseded,
                )
            )
    return tuple(drifted)


@dataclass(frozen=True, slots=True)
class UnimplementedEntry:
    """One unmet scope entry of an implemented CR (spec §9.6)."""

    id: str
    intent: ScopeIntent
    message: str


def unimplemented_entries(
    workspace: Workspace, cr: ChangeRequest
) -> tuple[UnimplementedEntry, ...]:
    """Unmet scope entries against the working tree (spec §9.6).

    Evaluated when the proposed status is ``implemented``: ``modify`` needs a
    working-tree effective version above ``base_version``, ``supersede`` an
    inbound ``supersedes`` edge, ``deprecate`` the deprecation flag. Missing
    targets are the scope check's finding and are skipped here.
    """
    if cr.status != "implemented":
        return ()
    documents = workspace.index.documents
    graph = workspace.graph
    unmet: list[UnimplementedEntry] = []
    for entry in cr.scope:
        loaded = documents.get(entry.id)
        if loaded is None:
            continue
        document = loaded.model
        if entry.intent == "modify":
            met = document_effective_version(workspace, entry.id) > entry.base_version
            detail = (
                f"{entry.id} is still at effective version "
                f"{document_effective_version(workspace, entry.id)} "
                f"(base version {entry.base_version})"
            )
        elif entry.intent == "supersede":
            met = graph.is_superseded(entry.id)
            detail = f"{entry.id} has no inbound supersedes edge"
        else:
            met = document.deprecated is not None
            detail = f"{entry.id} is not deprecated"
        if not met:
            unmet.append(
                UnimplementedEntry(id=entry.id, intent=entry.intent, message=detail)
            )
    return tuple(unmet)


# --------------------------------------------------------------------------
# origin tracking (spec §9.5)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OriginIssue:
    """One origin-tracking defect (spec §9.5)."""

    code: str
    subject: str
    message: str


def origin_issues(workspace: Workspace) -> tuple[OriginIssue, ...]:
    """``origin_cr`` ↔ ``introduces`` disagreements (spec §9.5).

    ``E-CR-ORIGIN-MISSING`` when ``origin_cr`` names no CR; ``E-CR-ORIGIN-
    MISMATCH`` when the two sides disagree in either direction.
    """
    documents = workspace.index.documents
    changes = workspace.index.changes
    issues: list[OriginIssue] = []
    for doc_id, loaded in sorted(documents.items()):
        origin = loaded.model.origin_cr
        if origin is None:
            continue
        found = changes.get(origin)
        if found is None:
            issues.append(
                OriginIssue(
                    "E-CR-ORIGIN-MISSING",
                    doc_id,
                    f"origin_cr {origin!r} names no change request",
                )
            )
        elif doc_id not in found.model.introduces:
            issues.append(
                OriginIssue(
                    "E-CR-ORIGIN-MISMATCH",
                    origin,
                    f"{doc_id} has origin_cr {origin!r} but the change request "
                    f"does not list it in introduces",
                )
            )
    for cr_id, cr_loaded in sorted(changes.items()):
        for doc_id in cr_loaded.model.introduces:
            document = documents.get(doc_id)
            if document is None:
                issues.append(
                    OriginIssue(
                        "E-CR-ORIGIN-MISMATCH",
                        cr_id,
                        f"introduces lists {doc_id}, which is not a document",
                    )
                )
            elif document.model.origin_cr != cr_id:
                shown = document.model.origin_cr or "null"
                issues.append(
                    OriginIssue(
                        "E-CR-ORIGIN-MISMATCH",
                        cr_id,
                        f"introduces lists {doc_id} but its origin_cr is {shown}",
                    )
                )
    return tuple(issues)


# --------------------------------------------------------------------------
# CR-body findings (spec §9.2, §9.7)
# --------------------------------------------------------------------------


def _is_unfilled(content: str, placeholder: str) -> bool:
    """Whether ``content`` is empty or only the section placeholder (§5.5)."""
    if section_is_empty(content, placeholder):
        return True
    stripped = placeholder.strip()
    if not stripped:
        return False
    return section_is_empty(content, f"*{stripped}*") or section_is_empty(
        content, f"**{stripped}**"
    )


def _body_issues(
    cr: ChangeRequest,
    body: str | None,
    templates: Mapping[str, Sequence[LoadedTemplate]],
) -> list[tuple[str, str, str, str | None]]:
    """§9.2 body conventions for a CR: H1 (5.6) and the pinned template (5.5)."""
    if body is None:
        return []
    issues: list[tuple[str, str, str, str | None]] = []
    if extract_title(body) is None:
        issues.append(
            (
                "E-TITLE-MISSING",
                cr.id,
                "no H1 title as the first non-blank line",
                f"gregraph edit {cr.id}",
            )
        )
    target: LoadedTemplate | None = None
    for candidate in templates.get(cr.template.name, ()):
        if candidate.version == cr.template.version:
            target = candidate
            break
    if target is None:
        issues.append(
            (
                "E-TEMPLATE-UNKNOWN",
                cr.id,
                f"template {cr.template.name!r} v{cr.template.version} "
                "is not in the repository",
                "gregraph template list",
            )
        )
        return issues
    if target.descriptor.deprecated:
        issues.append(
            (
                "W-TEMPLATE-DEPRECATED",
                cr.id,
                f"template {cr.template.name!r} v{cr.template.version} is deprecated",
                "gregraph template list",
            )
        )
    label = f"template {cr.template.name!r} v{cr.template.version}"
    sections = parse_sections(body)
    for section in target.descriptor.sections:
        found = find_section(sections, section.heading, section.renamed_from)
        if found is None:
            if section.required:
                issues.append(
                    (
                        "E-SECTION-REQUIRED-MISSING",
                        cr.id,
                        f"required section {section.heading!r} is missing ({label})",
                        f"gregraph edit {cr.id}",
                    )
                )
        elif section.required and _is_unfilled(found.content, section.placeholder):
            issues.append(
                (
                    "E-SECTION-REQUIRED-EMPTY",
                    cr.id,
                    f"required section {section.heading!r} is empty or "
                    f"placeholder only ({label})",
                    f"gregraph edit {cr.id}",
                )
            )
    matched: list[tuple[str, int]] = []
    for body_section in sections:
        for index, section in enumerate(target.descriptor.sections):
            if heading_matches(
                body_section.heading, section.heading, section.renamed_from
            ):
                matched.append((body_section.heading, index))
                break
        else:
            issues.append(
                (
                    "W-SECTION-UNKNOWN",
                    cr.id,
                    f"section {body_section.heading!r} is not in {label}",
                    None,
                )
            )
    for previous, current in zip(matched, matched[1:], strict=False):
        if current[1] < previous[1]:
            issues.append(
                (
                    "W-SECTION-ORDER",
                    cr.id,
                    f"section {current[0]!r} is out of template order ({label})",
                    None,
                )
            )
            break
    return issues


@dataclass(frozen=True, slots=True)
class CrIssue:
    """One validation finding of the CR subsystem (spec §14)."""

    code: str
    subject: str
    message: str
    fix: str | None = None


def cr_findings(
    workspace: Workspace,
    *,
    baseline: BaselineView | None = None,
    templates: Mapping[str, Sequence[LoadedTemplate]] | None = None,
) -> list[CrIssue]:
    """Every §9 validation finding over the CR subsystem (spec §14).

    Codes: :data:`ISSUE_CODES`. ``E-CR-DISABLED`` and ``E-CR-CLOSED`` are
    refusal codes and are never reported here (§9.1). The baseline snapshot is
    created lazily on first need and shared by every CR in the run (§9.6).
    """
    view = baseline
    if view is None:
        view = BaselineView(workspace.git, workspace.config.git.baseline_branch)
    if templates is None:
        templates = load_template_dir(templates_dir(workspace.root))
    index = workspace.index
    issues: list[CrIssue] = []
    for cr_id, loaded in sorted(index.changes.items()):
        cr = loaded.model
        body = cr_body(workspace, cr_id)
        for code, subject, message, fix in _body_issues(cr, body, templates):
            issues.append(CrIssue(code=code, subject=subject, message=message, fix=fix))
        effective = effective_version_from(
            cr, body, in_grace=_cr_in_grace(workspace, cr, cr_id)
        )
        for problem in status_issues(cr):
            issues.append(
                CrIssue(
                    code="E-CR-STATUS",
                    subject=cr_id,
                    message=problem.message,
                    fix=f"gregraph cr set {cr_id} status=…",
                )
            )
        if modified_after_decision(cr, effective):
            issues.append(
                CrIssue(
                    code="W-CR-MODIFIED-AFTER-DECISION",
                    subject=cr_id,
                    message=(
                        f"{cr_id} has content changes after its last decision "
                        f"(effective version {effective} > "
                        f"{cr.decisions[-1].at_version}); reopen or reaffirm"
                    ),
                    fix=f"gregraph cr reaffirm {cr_id}",
                )
            )
        for message in decider_issues(cr, workspace.config.cr.deciders):
            issues.append(
                CrIssue(
                    code="W-CR-DECIDER-UNKNOWN",
                    subject=cr_id,
                    message=message,
                    fix="git config user.email …",
                )
            )
        for message in scope_target_issues(workspace, cr):
            issues.append(
                CrIssue(
                    code="E-CR-SCOPE-TARGET",
                    subject=cr_id,
                    message=message,
                    fix=f"gregraph cr scope remove {cr_id} …",
                )
            )
        for entry in drift_entries(view, cr):
            parts: list[str] = []
            if entry.version_exceeds:
                parts.append(
                    f"version {entry.baseline_version} > "
                    f"base version {entry.base_version}"
                )
            if entry.superseded:
                parts.append("superseded on the baseline branch")
            if entry.deprecated:
                parts.append("deprecated on the baseline branch")
            issues.append(
                CrIssue(
                    code="W-CR-BASE-DRIFT",
                    subject=cr_id,
                    message=(
                        f"scope target {entry.id} drifted on baseline branch "
                        f"{view.branch!r} ({'; '.join(parts)}); if this is the "
                        f"CR's own implementation merged early, run "
                        f"`gregraph cr set {cr_id} status=implemented`, else "
                        f"re-read the target and reanalyze"
                    ),
                    fix=f"gregraph cr reanalyze {cr_id}",
                )
            )
        for unmet in unimplemented_entries(workspace, cr):
            issues.append(
                CrIssue(
                    code="W-CR-IMPLEMENTED-UNCHANGED",
                    subject=cr_id,
                    message=(
                        f"scope entry {unmet.id} ({unmet.intent}) is unmet in the "
                        f"working tree: {unmet.message}"
                    ),
                    fix=f"gregraph cr reanalyze {cr_id}",
                )
            )
        if body is not None:
            issues.extend(_mention_issues(workspace, cr, body))
    for issue in origin_issues(workspace):
        issues.append(
            CrIssue(code=issue.code, subject=issue.subject, message=issue.message)
        )
    return issues


def _mention_issues(
    workspace: Workspace, cr: ChangeRequest, body: str
) -> list[CrIssue]:
    """ID mentions in a CR body (spec §9.7).

    Unknown IDs are ``E-MENTION-UNKNOWN``; a mentioned document in neither the
    scope nor ``introduces`` is ``W-CR-MENTION-UNSCOPED``. Mentions of other
    CRs are not checked. Only explicit mention syntax counts (``[[ID]]`` or
    Markdown links, spec §5.2 D-AGENT-6) — bare ID-shaped prose is not a
    mention.
    """
    documents = workspace.index.documents
    changes = workspace.index.changes
    in_scope = {entry.id for entry in cr.scope}
    introduces = set(cr.introduces)
    issues: list[CrIssue] = []
    seen: set[str] = set()
    loaded = workspace.index.changes[cr.id]
    for mention in find_mentions(body, doc_path=loaded.body):
        other = mention.id
        if other in seen:
            continue
        seen.add(other)
        if other in changes:
            continue
        if other in documents:
            if other not in in_scope and other not in introduces:
                issues.append(
                    CrIssue(
                        code="W-CR-MENTION-UNSCOPED",
                        subject=cr.id,
                        message=(
                            f"mentions {other}, which is in neither the scope "
                            f"nor introduces"
                        ),
                        fix=f"gregraph cr scope add {cr.id} {other}",
                    )
                )
        else:
            issues.append(
                CrIssue(
                    code="E-MENTION-UNKNOWN",
                    subject=cr.id,
                    message=(
                        f"mentions {other}, which is neither a document nor a "
                        f"change request"
                    ),
                    fix=f"gregraph edit {cr.id}",
                )
            )
    return issues


# --------------------------------------------------------------------------
# operations (spec §13.18) — used by ``gregraph.core.operations``
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CrNewResult:
    """Result of :func:`new_change_request` (spec §13.18 ``cr new``)."""

    id: str
    uuid: UUID
    body: Path
    sidecar: Path
    title: str
    template: TemplateRef
    status: CrStatus
    decisions: tuple[Decision, ...]
    scope: tuple[ScopeEntry, ...]
    external_ref: str | None
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()
    sections: tuple[TemplateSection, ...] = ()
    body_text: str = ""
    sidecar_model: ChangeRequest | None = None


@dataclass(frozen=True, slots=True)
class CrScopeResult:
    """Result of :func:`scope_add` / :func:`scope_remove`."""

    id: str
    scope: tuple[ScopeEntry, ...]
    version: int
    changed: bool
    added: ScopeEntry | None = None
    removed: str | None = None
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrScopeUpdate:
    """One base-version change recorded by :func:`reanalyze` (§2.4.4)."""

    id: str
    intent: ScopeIntent
    old_base_version: int
    new_base_version: int


@dataclass(frozen=True, slots=True)
class CrSetResult:
    """Result of :func:`set_cr_fields` (spec §13.18 ``cr set``)."""

    id: str
    status: CrStatus
    branch: str | None
    external_ref: str | None
    tags: tuple[str, ...]
    extra: dict[str, str]
    decision: Decision | None
    changed: bool
    applied: dict[str, Any] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrDecisionResult:
    """Result of :func:`reaffirm` (spec §13.18 ``cr reaffirm``)."""

    id: str
    status: CrStatus
    decision: Decision | None
    changed: bool
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrReanalyzeResult:
    """Result of :func:`reanalyze` (spec §13.18 ``cr reanalyze``)."""

    id: str
    scope: tuple[ScopeEntry, ...]
    version: int
    changed: bool
    updated: tuple[CrScopeUpdate, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrListEntry:
    """One ``cr list`` row (spec §13.18)."""

    id: str
    title: str
    status: CrStatus
    effective: CrStatus | Literal["none"]
    pending: bool
    drift: bool


@dataclass(frozen=True, slots=True)
class CrListResult:
    """Result of :func:`list_changes` (spec §13.18 ``cr list``)."""

    entries: tuple[CrListEntry, ...]


@dataclass(frozen=True, slots=True)
class ScopeState:
    """One ``cr show`` scope row (spec §9.8)."""

    id: str
    intent: ScopeIntent
    base_version: int
    baseline_version: int | None
    working_version: int | None
    live: Literal["live", "deprecated", "superseded", "missing"]
    drift: bool


@dataclass(frozen=True, slots=True)
class IntroducedState:
    """One ``cr show`` introduces row (spec §9.8)."""

    doc_id: str
    status: str


@dataclass(frozen=True, slots=True)
class CrShowResult:
    """Result of :func:`show_change` (spec §9.8 impact view)."""

    id: str
    title: str
    status: CrStatus
    effective: CrStatus | Literal["none"]
    decisions: tuple[Decision, ...]
    scope: tuple[ScopeState, ...]
    introduces: tuple[IntroducedState, ...]
    impact: tuple[str, ...]
    branch: str | None
    external_ref: str | None
    tags: tuple[str, ...]
    extra: dict[str, str]
    body: str = ""


@dataclass(frozen=True, slots=True)
class IntroductionResult:
    """Result of :func:`record_origin` (spec §9.5)."""

    cr_id: str
    doc_id: str
    introduces: tuple[str, ...]
    changed: bool


def _identity_findings(workspace: Workspace, subject: str) -> tuple[Finding, ...]:
    """``W-NO-GIT-IDENTITY`` when ``created_by`` cannot be filled (spec §5.4)."""
    if workspace.git.identity() is not None:
        return ()
    return (
        Finding(
            code="W-NO-GIT-IDENTITY",
            severity="W",
            subject=subject,
            message="git identity unavailable; created_by is null",
            fix='git config user.name "…" && git config user.email "…"',
        ),
    )


def _pick_cr_template(workspace: Workspace) -> LoadedTemplate:
    """Resolve the ``cr.template`` pin; refuses ``E-TEMPLATE-UNKNOWN``."""
    name = workspace.config.cr.template
    versions = load_template_dir(templates_dir(workspace.root)).get(name)
    if not versions:
        raise _refuse(
            "E-TEMPLATE-UNKNOWN",
            name,
            f"template {name!r} not found in the repository",
            "gregraph template list",
        )
    try:
        picked = resolve_template(versions, version=None)
    except ValueError as exc:
        raise _refuse(
            "E-TEMPLATE-UNKNOWN", name, str(exc), "gregraph template list"
        ) from exc
    return picked


def new_change_request(
    workspace: Workspace,
    *,
    title: str | None,
    scope_specs: Sequence[str] = (),
    external_ref: str | None = None,
    sections: Sequence[tuple[str, str]] = (),
    strict: bool = False,
) -> CrNewResult:
    """Create a change request (spec §13.18 ``cr new``, §9.2, §3.4).

    Renders the ``cr.template`` body, records the initial ``open`` decision
    with ``at_version = 1`` and the given scope entries with their baseline
    base versions (§9.4). ``sections`` assembles the body from per-section
    input in template order; ``strict`` requires every template-required
    section to be filled at write time (§3.4 rules 5–6). Refusals write
    nothing.
    """
    require_enabled(workspace, subject="cr new")
    if title is None or not title.strip():
        raise ValueError("cr new needs a title")
    parsed = parse_scope_specs(scope_specs)
    picked = _pick_cr_template(workspace)
    generated = generate_id(
        _existing_ids(workspace),
        workspace.config.ids.prefix,
        CR_ABBREVIATION,
    )
    created = _now()
    identity = workspace.git.identity()
    author = identity.name if identity is not None else ""
    body_text = render_template(
        picked,
        title=title,
        id=generated.id,
        type=workspace.config.cr.template,
        kind="change",
        created=_stamp(created),
        author=author,
    )
    if sections:
        resolved_sections = resolve_section_inputs(picked.descriptor, sections)
        body_text = assemble_sections(
            picked.descriptor,
            title=title,
            content=resolved_sections,
            base_body=body_text,
            preserve_existing=False,
        )
        check_required_sections(
            picked.descriptor,
            body_text,
            provided_headings=set(resolved_sections),
            require_provided=True,
        )
    elif strict:
        check_required_sections(picked.descriptor, body_text)
    baseline = BaselineView(workspace.git, workspace.config.git.baseline_branch)
    entries: list[ScopeEntry] = []
    for raw_target, intent in parsed:
        target = _scope_target(workspace, raw_target)
        if any(entry.id == target for entry in entries):
            raise _refuse(
                "E-CR-SCOPE-TARGET",
                target,
                f"scope target {target} appears more than once",
                f"gregraph cr scope add {generated.id} …",
            )
        entries.append(
            ScopeEntry(
                id=target,
                intent=intent,
                base_version=base_version_for(workspace, baseline, target),
            )
        )
    entries.sort(key=lambda entry: entry.id)
    cr = ChangeRequest(
        schema=1,
        uuid=generated.uuid,
        id=generated.id,
        title=title,
        created=created,
        created_by=identity,
        template=TemplateRef(name=picked.name, version=picked.version),
        version=1,
        body_hash=body_hash(body_text),
        scope_hash=scope_hash(entries),
        scope=entries,
        introduces=[],
        status="open",
        decisions=[initial_decision(at=created, by=identity)],
        branch=None,
        external_ref=external_ref,
        tags=[],
        extra={},
    )
    abs_body, abs_sidecar = change_paths(workspace.root, generated.id)
    write_body(abs_body, body_text)
    write_sidecar(abs_sidecar, cr)
    workspace.reload()
    return CrNewResult(
        id=generated.id,
        uuid=generated.uuid,
        body=abs_body.relative_to(workspace.root),
        sidecar=abs_sidecar.relative_to(workspace.root),
        title=title,
        template=cr.template,
        status=cr.status,
        decisions=tuple(cr.decisions),
        scope=tuple(cr.scope),
        external_ref=external_ref,
        findings=_identity_findings(workspace, generated.id),
        sections=tuple(picked.descriptor.sections),
        body_text=body_text,
        sidecar_model=cr,
    )


def scope_add(
    workspace: Workspace, *, cr_id: str, target: str, intent: str = "modify"
) -> CrScopeResult:
    """Add one scope entry (spec §13.18 ``cr scope add``, §9.4)."""
    require_enabled(workspace, subject=cr_id)
    resolved_cr = _resolve_cr(workspace, cr_id)
    if intent not in SCOPE_INTENTS:
        raise ValueError(
            f"unknown scope intent {intent!r} (want {', '.join(SCOPE_INTENTS)})"
        )
    cr = _read_cr(workspace, resolved_cr)
    doc_id = _scope_target(workspace, target)
    if any(entry.id == doc_id for entry in cr.scope):
        raise _refuse(
            "E-CR-SCOPE-TARGET",
            doc_id,
            f"{doc_id} is already in the scope of {resolved_cr}",
            f"gregraph cr show {resolved_cr}",
        )
    baseline = BaselineView(workspace.git, workspace.config.git.baseline_branch)
    entry = ScopeEntry(
        id=doc_id,
        intent=intent,
        base_version=base_version_for(workspace, baseline, doc_id),
    )
    cr.scope = sorted([*cr.scope, entry], key=lambda item: item.id)
    _record_content_change(cr, cr_body(workspace, resolved_cr))
    _write_cr(workspace, cr)
    workspace.reload()
    return CrScopeResult(
        id=resolved_cr,
        scope=tuple(cr.scope),
        version=cr.version,
        changed=True,
        added=entry,
    )


def scope_remove(workspace: Workspace, *, cr_id: str, target: str) -> CrScopeResult:
    """Remove one scope entry (spec §13.18 ``cr scope remove``, §9.4)."""
    require_enabled(workspace, subject=cr_id)
    resolved_cr = _resolve_cr(workspace, cr_id)
    cr = _read_cr(workspace, resolved_cr)
    known = {entry.id for entry in cr.scope} | set(workspace.index.documents)
    resolved = normalise_id(target, workspace.config.ids.prefix, known=known)
    if resolved is None:
        raise _refuse(
            "E-ID-UNKNOWN", target, f"no document with id {target!r}", "gregraph list"
        )
    remaining = [entry for entry in cr.scope if entry.id != resolved]
    if len(remaining) == len(cr.scope):
        return CrScopeResult(
            id=resolved_cr,
            scope=tuple(cr.scope),
            version=cr.version,
            changed=False,
            removed=resolved,
            notices=(f"{resolved} is not in the scope of {resolved_cr}",),
        )
    cr.scope = sorted(remaining, key=lambda item: item.id)
    _record_content_change(cr, cr_body(workspace, resolved_cr))
    _write_cr(workspace, cr)
    workspace.reload()
    return CrScopeResult(
        id=resolved_cr,
        scope=tuple(cr.scope),
        version=cr.version,
        changed=True,
        removed=resolved,
    )


def set_cr_fields(
    workspace: Workspace, *, cr_id: str, assignments: Sequence[str]
) -> CrSetResult:
    """Apply ``key=value`` assignments to a CR (spec §13.18 ``cr set``).

    Keys: ``status`` (§9.3 transitions), ``branch``, ``external_ref``,
    ``tags`` (``set`` syntax), ``extra.<name>``. Nothing here is content
    (D14): no version bump. All assignments are validated before anything is
    written; the transition itself refuses ``E-CR-STATUS``.
    """
    require_enabled(workspace, subject=cr_id)
    resolved_cr = _resolve_cr(workspace, cr_id)
    cr = _read_cr(workspace, resolved_cr)
    before = cr.model_dump(mode="json")
    notices: list[str] = []
    decision: Decision | None = None
    new_status: CrStatus | None = None

    def refuse_key(text: str, key: str) -> OperationRefused:
        hint, fix = _CR_KEY_HINTS.get(
            key, (f"{key!r} is owned by the tool", "gregraph cr show {id}")
        )
        return _refuse(
            "E-SET-KEY",
            text,
            f"cannot set {key!r} with `gregraph cr set`: {hint}",
            fix.format(id=resolved_cr),
        )

    def refuse_value(text: str, message: str) -> OperationRefused:
        return _refuse("E-SET-VALUE", text, message)

    plans: list[tuple[str, str, str]] = []
    for text in assignments:
        key: str | None = None
        op: str | None = None
        value: str | None = None
        for candidate in ("+=", "-=", "="):
            index = text.find(candidate)
            if index != -1:
                key, op, value = text[:index], candidate, text[index + len(candidate) :]
                break
        if key is None or op is None or value is None or not key:
            raise refuse_value(
                text, f"cannot parse assignment {text!r} (want key=value)"
            )
        if key == "status":
            if op != "=":
                raise refuse_value(
                    text, f"{op} is only allowed for tags; set status with ="
                )
            if value not in CR_STATUSES:
                raise refuse_value(
                    text,
                    f"unknown status {value!r} (want {', '.join(CR_STATUSES)})",
                )
        elif key in {"branch", "external_ref"}:
            if op != "=":
                raise refuse_value(
                    text, f"{op} is only allowed for tags; set {key} with ="
                )
        elif key == "tags":
            pass
        elif key.startswith("extra.") and len(key) > len("extra."):
            if op != "=":
                raise refuse_value(
                    text, f"{op} is only allowed for tags; set {key} with ="
                )
        else:
            raise refuse_key(text, key)
        plans.append((key, op, value))

    for key, op, value in plans:
        if key == "status":
            new_status = cast(CrStatus, value)
        elif key == "branch":
            cr.branch = value or None
        elif key == "external_ref":
            cr.external_ref = value or None
        elif key == "tags":
            if op == "=":
                new_tags = [item.strip() for item in value.split(",") if item.strip()]
                _check_tags(new_tags)
                cr.tags = list(dict.fromkeys(new_tags))
            elif op == "+=":
                tag = value.strip()
                _check_tags([tag])
                if tag not in cr.tags:
                    cr.tags = [*cr.tags, tag]
            else:
                tag = value.strip()
                _check_tags([tag])
                if tag not in cr.tags:
                    notices.append(f"tag {tag!r} was not present")
                cr.tags = [item for item in cr.tags if item != tag]
        else:
            name = key[len("extra.") :]
            if value == "":
                if name not in cr.extra:
                    notices.append(f"{key} was not present")
                cr.extra.pop(name, None)
            else:
                cr.extra[name] = value

    if new_status is not None:
        decision = decide(
            cr,
            new_status,
            at=_now(),
            by=workspace.git.identity(),
            at_version=effective_version_from(
                cr,
                cr_body(workspace, resolved_cr),
                in_grace=_cr_in_grace(workspace, cr, resolved_cr),
            ),
        )
    applied: dict[str, Any] = {}
    for key, _op, _value in plans:
        if key == "status":
            applied["status"] = cr.status
        elif key == "branch":
            applied["branch"] = cr.branch
        elif key == "external_ref":
            applied["external_ref"] = cr.external_ref
        elif key == "tags":
            applied["tags"] = list(cr.tags)
        else:
            applied[key] = cr.extra.get(key[len("extra.") :])
    changed = cr.model_dump(mode="json") != before
    if changed:
        _write_cr(workspace, cr)
        workspace.reload()
    return CrSetResult(
        id=resolved_cr,
        status=cr.status,
        branch=cr.branch,
        external_ref=cr.external_ref,
        tags=tuple(cr.tags),
        extra=dict(cr.extra),
        decision=decision,
        changed=changed,
        applied=applied,
        notices=tuple(notices),
    )


def _check_tags(tags: Sequence[str]) -> None:
    """Refuse tags outside the §5.4 format with ``E-TAG-INVALID``."""
    for tag in tags:
        if _TAG_PATTERN.fullmatch(tag) is None:
            raise _refuse(
                "E-TAG-INVALID",
                tag,
                f"invalid tag {tag!r}: tags are lowercase [a-z0-9-]+",
                "gregraph cr set CR tags=a,b",
            )


def reaffirm_cr(workspace: Workspace, *, cr_id: str) -> CrDecisionResult:
    """Append a decision with the current status (spec §13.18 ``cr reaffirm``)."""
    require_enabled(workspace, subject=cr_id)
    resolved_cr = _resolve_cr(workspace, cr_id)
    cr = _read_cr(workspace, resolved_cr)
    decision = reaffirm(
        cr,
        at=_now(),
        by=workspace.git.identity(),
        at_version=effective_version_from(
            cr,
            cr_body(workspace, resolved_cr),
            in_grace=_cr_in_grace(workspace, cr, resolved_cr),
        ),
    )
    _write_cr(workspace, cr)
    workspace.reload()
    return CrDecisionResult(
        id=resolved_cr, status=cr.status, decision=decision, changed=True
    )


def reanalyze(
    workspace: Workspace, *, cr_id: str, targets: Sequence[str] = ()
) -> CrReanalyzeResult:
    """Refresh ``base_version`` values against the baseline (spec §9.4).

    Sets the entries' base version to the current baseline version (effective
    working-tree version in degraded mode) for the given targets, or all
    entries. Reanalysis changes the scope and therefore the CR's content: it
    records one version bump so a decided CR trips
    ``W-CR-MODIFIED-AFTER-DECISION`` until reaffirmed.
    """
    require_enabled(workspace, subject=cr_id)
    resolved_cr = _resolve_cr(workspace, cr_id)
    cr = _read_cr(workspace, resolved_cr)
    by_id = {entry.id: entry for entry in cr.scope}
    if targets:
        selected: set[str] = set()
        for raw in targets:
            resolved = normalise_id(raw, workspace.config.ids.prefix, known=by_id)
            if resolved is None:
                raise _refuse(
                    "E-CR-SCOPE-TARGET",
                    raw,
                    f"{raw!r} is not in the scope of {resolved_cr}",
                    f"gregraph cr scope add {resolved_cr} {raw}",
                )
            selected.add(resolved)
    else:
        selected = set(by_id)
    baseline = BaselineView(workspace.git, workspace.config.git.baseline_branch)
    notices: list[str] = []
    changed_ids: list[str] = []
    updated: list[ScopeEntry] = []
    updates: list[CrScopeUpdate] = []
    for entry in cr.scope:
        if entry.id not in selected:
            updated.append(entry)
            continue
        if baseline.available:
            current = baseline.document_version(entry.id)
            if current is None:
                notices.append(
                    f"{entry.id} is not on baseline branch {baseline.branch!r}; "
                    f"base version left at {entry.base_version}"
                )
                updated.append(entry)
                continue
        else:
            if entry.id not in workspace.index.documents:
                notices.append(
                    f"{entry.id} is missing from the working tree; "
                    f"base version left at {entry.base_version}"
                )
                updated.append(entry)
                continue
            current = document_effective_version(workspace, entry.id)
        if current == entry.base_version:
            updated.append(entry)
            continue
        updates.append(
            CrScopeUpdate(
                id=entry.id,
                intent=entry.intent,
                old_base_version=entry.base_version,
                new_base_version=current,
            )
        )
        updated.append(
            ScopeEntry(id=entry.id, intent=entry.intent, base_version=current)
        )
        changed_ids.append(entry.id)
    changed = bool(changed_ids)
    if changed:
        cr.scope = sorted(updated, key=lambda item: item.id)
        _record_content_change(cr, cr_body(workspace, resolved_cr), force=True)
        _write_cr(workspace, cr)
        workspace.reload()
    return CrReanalyzeResult(
        id=resolved_cr,
        scope=tuple(cr.scope),
        version=cr.version,
        changed=changed,
        updated=tuple(updates),
        notices=tuple(notices),
    )


def list_changes(
    workspace: Workspace,
    *,
    statuses: Sequence[str] = (),
    effective: bool = False,
    pending: bool = False,
    drift: bool = False,
) -> CrListResult:
    """List change requests with the §13.18 filters."""
    require_enabled(workspace, subject="cr list")
    baseline = BaselineView(workspace.git, workspace.config.git.baseline_branch)
    rows: list[CrListEntry] = []
    for cr_id, loaded in sorted(workspace.index.changes.items()):
        cr = loaded.model
        status = effective_status(baseline, cr)
        is_pending = status != cr.status
        has_drift = bool(drift_entries(baseline, cr))
        if statuses:
            wanted = status if effective else cr.status
            if wanted not in statuses:
                continue
        if pending and not is_pending:
            continue
        if drift and not has_drift:
            continue
        rows.append(
            CrListEntry(
                id=cr_id,
                title=cr.title,
                status=cr.status,
                effective=status,
                pending=is_pending,
                drift=has_drift,
            )
        )
    return CrListResult(entries=tuple(rows))


def show_change(workspace: Workspace, cr_id: str) -> CrShowResult:
    """Full CR view (spec §9.8): status, decisions, scope rows, impact set."""
    require_enabled(workspace, subject=cr_id)
    resolved_cr = _resolve_cr(workspace, cr_id)
    cr = _read_cr(workspace, resolved_cr)
    baseline = BaselineView(workspace.git, workspace.config.git.baseline_branch)
    drifted = {entry.id for entry in drift_entries(baseline, cr)}
    rows: list[ScopeState] = []
    for entry in cr.scope:
        loaded = workspace.index.documents.get(entry.id)
        if loaded is None:
            live: Literal["live", "deprecated", "superseded", "missing"] = "missing"
            working: int | None = None
        else:
            document = loaded.model
            working = document_effective_version(workspace, entry.id)
            if document.deprecated is not None:
                live = "deprecated"
            elif workspace.graph.is_superseded(entry.id):
                live = "superseded"
            else:
                live = "live"
        rows.append(
            ScopeState(
                id=entry.id,
                intent=entry.intent,
                base_version=entry.base_version,
                baseline_version=baseline.document_version(entry.id),
                working_version=working,
                live=live,
                drift=entry.id in drifted,
            )
        )
    report = compute_status(workspace)
    introduced = tuple(
        IntroducedState(
            doc_id=doc_id,
            status=(
                report.documents[doc_id].status
                if doc_id in report.documents
                else "unknown"
            ),
        )
        for doc_id in cr.introduces
    )
    return CrShowResult(
        id=resolved_cr,
        title=cr.title,
        status=cr.status,
        effective=effective_status(baseline, cr),
        decisions=tuple(cr.decisions),
        scope=tuple(rows),
        introduces=introduced,
        impact=impact_set(workspace, (entry.id for entry in cr.scope)),
        branch=cr.branch,
        external_ref=cr.external_ref,
        tags=tuple(cr.tags),
        extra=dict(cr.extra),
        body=cr_body(workspace, resolved_cr) or "",
    )


def impact_set(workspace: Workspace, targets: Iterable[str]) -> tuple[str, ...]:
    """Impact set of the scope (spec §9.8): 1-up + unlimited-down per target.

    De-duplicated across targets; the scope targets themselves are the
    declared change and are not repeated here.
    """
    graph = workspace.graph
    seeds = tuple(targets)
    impact: set[str] = set()
    for target in seeds:
        if target not in graph.nodes:
            continue
        impact.update(graph.upstream(target))
        impact.update(graph.downstream(target, depth=None))
    impact.difference_update(seeds)
    return tuple(sorted(impact))


def record_origin(
    workspace: Workspace, *, cr_id: str, doc_id: str
) -> IntroductionResult:
    """Record that ``cr_id`` introduced ``doc_id`` (spec §9.5).

    Validates the CR (``E-CR-DISABLED``, ``E-CR-CLOSED``, unknown CR) and
    appends ``doc_id`` to its ``introduces`` list. The caller (``new``/
    ``supersede``) writes ``origin_cr`` on the new document's sidecar and calls
    this *before* any file is written, so a refusal leaves nothing behind.
    """
    require_enabled(workspace, subject=cr_id)
    resolved_cr = _resolve_cr(workspace, cr_id)
    cr = _read_cr(workspace, resolved_cr)
    if cr.status not in ("open", "accepted"):
        raise _refuse(
            "E-CR-CLOSED",
            resolved_cr,
            f"{resolved_cr} is {cr.status!r}; only open or accepted change "
            f"requests may introduce documents",
            f"gregraph cr set {resolved_cr} status=open",
        )
    if doc_id in cr.introduces:
        return IntroductionResult(
            cr_id=resolved_cr,
            doc_id=doc_id,
            introduces=tuple(cr.introduces),
            changed=False,
        )
    cr.introduces = sorted([*cr.introduces, doc_id])
    _write_cr(workspace, cr)
    workspace.reload()
    return IntroductionResult(
        cr_id=resolved_cr,
        doc_id=doc_id,
        introduces=tuple(cr.introduces),
        changed=True,
    )
