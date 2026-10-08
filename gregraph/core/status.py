"""Derived status and WIP (spec §8, §11.1, §16.1).

Status is **derived**, never stored, except for one flag (``deprecated``, spec
§8). Precedence: ``deprecated`` > ``superseded`` > ``draft`` > ``active``.
``draft`` is Git-derived: the document's body or sidecar is untracked
(``ls-files --error-unmatch``) or differs from the configured baseline branch
(``git.baseline_branch``, default ``main``; adapter methods of §12.1).
``superseded`` is an inbound ``supersedes`` edge (§7.6) and ``deprecated`` is
the stored flag (§5.4). Without Git, or when the baseline branch is missing
locally, the draft/active axis degrades to ``unknown``; the missing branch
raises warning ``W-BASELINE-MISSING`` (§8 — the code is not in the §14
catalogue, see docs/backlog.md), while degraded mode is the §12.1 note channel
and produces no finding. ``deprecated`` and ``superseded`` still resolve in
both cases. These statuses apply to documents and glossary terms (§8).

WIP aggregate (spec §8): the repository is in WIP state if any status subject
is ``draft``, any has unbumped modifications (effective content differs from
the stored hashes, §7.1 r1/§7.3 — hash-based, works without Git), or any file
under the managed directories (``documents/``, ``changes/``, ``glossary/``,
``assets/``) is uncommitted. :class:`WipState` carries the counts of the
``gregraph status`` header ``WIP: yes (3 drafts, 1 modified)`` (§13.12).
Open ``conflicts-with`` edges between two live nodes are counted for ``status``
(§11.1, §14 ``W-CONFLICT-OPEN``). Pure data only — no printing, no ``cli``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from gregraph.core.graph import Graph
from gregraph.core.hashing import asset_hash, body_hash, effective_content_changed
from gregraph.core.markdown import find_asset_refs
from gregraph.core.models import Document, Finding, Term
from gregraph.core.storage import (
    ASSETS_DIR,
    CHANGES_DIR,
    CONFIG_RELPATH,
    DOCUMENTS_DIR,
    GLOSSARY_DIR,
    read_body,
)
from gregraph.core.workspace import Workspace

Status = Literal["draft", "active", "superseded", "deprecated", "unknown"]

_MANAGED_TOP: Final = frozenset(
    directory.as_posix()
    for directory in (DOCUMENTS_DIR, CHANGES_DIR, GLOSSARY_DIR, ASSETS_DIR)
)
_BASELINE_MISSING_CODE: Final = "W-BASELINE-MISSING"


@dataclass(frozen=True, slots=True)
class ItemStatus:
    """Derived status of one document or glossary term (spec §8).

    ``key`` is the document ID or the term slug; ``body``/``sidecar`` are
    repository-relative (spec §16.2). ``draft`` is the pre-precedence
    draft/active fact — ``None`` when the Git/baseline comparison is
    unavailable.
    """

    key: str
    status: Status
    body: Path
    sidecar: Path
    deprecated: bool
    superseded: bool
    draft: bool | None


@dataclass(frozen=True, slots=True)
class WipState:
    """WIP aggregate and the counts of the ``status`` header (spec §8, §13.12).

    ``drafts`` are the status subjects whose status is ``draft``; ``modified``
    are those with unbumped modifications ("modified, unbumped", §7.2);
    ``uncommitted`` are the uncommitted (staged, unstaged or untracked) files
    under the managed directories.
    """

    drafts: tuple[ItemStatus, ...] = ()
    modified: tuple[ItemStatus, ...] = ()
    uncommitted: tuple[Path, ...] = ()

    @property
    def is_wip(self) -> bool:
        """Whether the repository is in WIP state (spec §8)."""
        return bool(self.drafts or self.modified or self.uncommitted)

    @property
    def draft_count(self) -> int:
        """Number of drafts (the ``(N drafts, …)`` header count, §13.12)."""
        return len(self.drafts)

    @property
    def modified_count(self) -> int:
        """Number of unbumped modifications (the ``(…, N modified)`` count)."""
        return len(self.modified)

    @property
    def uncommitted_count(self) -> int:
        """Number of uncommitted files under the managed directories."""
        return len(self.uncommitted)


@dataclass(frozen=True, slots=True)
class StatusReport:
    """Everything the §8 status model and WIP aggregate derive for a workspace.

    ``documents`` is keyed by document ID, ``terms`` by term slug;
    ``open_conflicts`` holds the sorted live ``conflicts-with`` pairs whose
    count ``status`` prints (§11.1); ``findings`` are the derivation warnings
    (``W-BASELINE-MISSING`` today).
    """

    documents: dict[str, ItemStatus]
    terms: dict[str, ItemStatus]
    wip: WipState
    open_conflicts: tuple[tuple[str, str], ...]
    findings: tuple[Finding, ...] = ()

    @property
    def open_conflict_count(self) -> int:
        """Number of open conflicts (spec §11.1: ``status`` counts them)."""
        return len(self.open_conflicts)


def derive_status(*, deprecated: bool, superseded: bool, draft: bool | None) -> Status:
    """Apply the §8 precedence ``deprecated`` > ``superseded`` > ``draft`` > ``active``.

    ``draft`` is ``None`` when the draft/active axis is unknown (no Git or the
    baseline branch is missing locally): that slot reports ``unknown``, while
    ``deprecated`` and ``superseded`` still resolve without Git (spec §8).
    """
    if deprecated:
        return "deprecated"
    if superseded:
        return "superseded"
    if draft is None:
        return "unknown"
    return "draft" if draft else "active"


def open_conflicts(graph: Graph) -> tuple[tuple[str, str], ...]:
    """Live ``conflicts-with`` pairs, sorted (spec §11.1, §14 ``W-CONFLICT-OPEN``).

    Open = both endpoints exist and are neither deprecated nor superseded
    ("between two live nodes", §14). Symmetric pairs collapse to one
    ``(low, high)`` pair. ``status`` counts these.
    """
    pairs: set[tuple[str, str]] = set()
    for edge in graph.edges:
        if edge.type != "conflicts-with":
            continue
        if edge.source not in graph.nodes or edge.target not in graph.nodes:
            continue
        if (
            graph.is_deprecated(edge.source)
            or graph.is_superseded(edge.source)
            or graph.is_deprecated(edge.target)
            or graph.is_superseded(edge.target)
        ):
            continue
        low, high = sorted((edge.source, edge.target))
        pairs.add((low, high))
    return tuple(sorted(pairs))


def compute_status(workspace: Workspace) -> StatusReport:
    """Derive the §8 status model and WIP aggregate for ``workspace``.

    Document and term statuses, the WIP aggregate with the counts of the
    ``status`` header (§13.12), the open-conflict count (§11.1) and the
    derivation warnings. Never prints.
    """
    baseline = workspace.config.git.baseline_branch
    git = workspace.git
    findings: list[Finding] = []
    draft_known = False
    if git.is_repo():
        if git.branch_exists(baseline):
            draft_known = True
        else:
            findings.append(
                Finding(
                    code=_BASELINE_MISSING_CODE,
                    severity="W",
                    subject=CONFIG_RELPATH,
                    message=(
                        f"baseline branch {baseline!r} not found locally; "
                        "draft/active status degrades to unknown"
                    ),
                )
            )

    def draft_flag(body: Path, sidecar: Path) -> bool | None:
        if not draft_known:
            return None
        if not git.is_tracked(body) or not git.is_tracked(sidecar):
            return True
        return git.differs_from_ref(body, baseline) or git.differs_from_ref(
            sidecar, baseline
        )

    index = workspace.index
    graph = workspace.graph
    documents: dict[str, ItemStatus] = {}
    for key in sorted(index.documents):
        loaded = index.documents[key]
        deprecated = loaded.model.deprecated is not None
        superseded = graph.is_superseded(key)
        draft = draft_flag(loaded.body, loaded.sidecar)
        documents[key] = ItemStatus(
            key=key,
            status=derive_status(
                deprecated=deprecated, superseded=superseded, draft=draft
            ),
            body=loaded.body,
            sidecar=loaded.sidecar,
            deprecated=deprecated,
            superseded=superseded,
            draft=draft,
        )

    terms: dict[str, ItemStatus] = {}
    for key in sorted(index.terms):
        term_loaded = index.terms[key]
        deprecated = term_loaded.model.deprecated is not None
        draft = draft_flag(term_loaded.body, term_loaded.sidecar)
        terms[key] = ItemStatus(
            key=key,
            status=derive_status(deprecated=deprecated, superseded=False, draft=draft),
            body=term_loaded.body,
            sidecar=term_loaded.sidecar,
            deprecated=deprecated,
            superseded=False,
            draft=draft,
        )

    drafts = tuple(
        sorted(
            (
                item
                for item in (*documents.values(), *terms.values())
                if item.status == "draft"
            ),
            key=lambda item: item.key,
        )
    )
    modified: list[ItemStatus] = []
    for key, doc_loaded in sorted(index.documents.items()):
        if _unbumped_modifications(
            workspace.root, key, doc_loaded.model, doc_loaded.body
        ):
            modified.append(documents[key])
    for key, term_loaded in sorted(index.terms.items()):
        if _unbumped_modifications(
            workspace.root, key, term_loaded.model, term_loaded.body
        ):
            modified.append(terms[key])
    uncommitted: tuple[Path, ...] = ()
    if git.is_repo():
        paths = set(git.changed_paths()) | set(git.untracked_paths())
        uncommitted = tuple(
            sorted(
                path for path in paths if path.parts and path.parts[0] in _MANAGED_TOP
            )
        )

    return StatusReport(
        documents=documents,
        terms=terms,
        wip=WipState(
            drafts=drafts,
            modified=tuple(sorted(modified, key=lambda item: item.key)),
            uncommitted=uncommitted,
        ),
        open_conflicts=open_conflicts(graph),
        findings=tuple(findings),
    )


def _unbumped_modifications(
    root: Path, key: str, model: Document | Term, body: Path
) -> bool:
    """Whether effective content differs from the stored hashes (spec §7.2, §7.3).

    "Modified, unbumped": the working-tree body/assets no longer match the
    hashes stored at the last version bump. Hash-based (§7.1 refinement 1), so
    it works with and without Git. A missing body counts as modified; assets of
    documents are recomputed from the body's references that exist (§5.7).
    """
    try:
        text = read_body(root / body)
    except OSError:
        return True
    current_assets: list[tuple[Path, str]] = []
    stored_assets: list[tuple[Path, str]] = []
    if isinstance(model, Document):
        stored_assets = [(Path(asset.path), asset.hash) for asset in model.assets]
        for ref in find_asset_refs(text, doc_path=body, doc_id=key):
            if ref.foreign:
                continue
            file = root / ref.path
            if file.is_file():
                relative = Path(*ref.path.parts[2:])
                current_assets.append((relative, asset_hash(file.read_bytes())))
    return effective_content_changed(
        model.body_hash,
        stored_assets,
        body_hash(text),
        current_assets,
    )
