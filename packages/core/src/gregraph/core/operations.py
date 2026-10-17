"""Use-cases: the API surface for the CLI and a future web UI (spec §13, §16.1–16.2).

Every CLI command maps to one function here taking plain arguments and
returning a result dataclass; interactive selection happens in ``cli`` before
the call. Implemented in S12 (document lifecycle, spec §4.2, §5.4, §5.6, §7.4,
§7.6, §11.2, §13.2–13.6, §13.14–13.15): :func:`create_document`, :func:`link`,
:func:`unlink`, :func:`link_refresh`, :func:`set_fields`, :func:`supersede`,
:func:`deprecate`, :func:`undeprecate` (plus the pure query
:func:`supersession_chain`) and in S13 the change requests (spec §9, §13.18:
``cr_*``, :func:`record_introduction`, delegating to :mod:`gregraph.core.changes`)
and in S14 the glossary (spec §10, §13.20: ``term_*``, :func:`derive_term_slug`)
and in S15 templates, migration, baselines and repair (spec §7.7, §12.4,
§12.6, §4.4, §16.5, §13.16–13.17, §13.19, §13.21: ``template_*``,
:func:`migrate`, ``baseline_*``, ``repair_*``).
The remaining §13 operations are stubs raising ``NotImplementedError`` and are
implemented by later subtasks (``init``,
``sync``/``check``/``validate``, ``list``/``show``/``status``/``graph``,
``edit``, ``hooks_*``, ``hook pre-commit``).

Refusals raise ``OperationRefused(finding)`` (spec §16.2, defined next to
``Finding`` — docs/decisions.md ``D-OPREFUSED-HOME``); everything else is data
in the result dataclasses. ``core`` never imports ``cli`` and never prints.
Behavioural corner cases of §7.6/§13.5 are recorded in docs/decisions.md
``D-S12-OPERATIONS``; refusal codes outside the §14 catalogue are listed in
docs/backlog.md.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import unicodedata
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from importlib.resources import files as resource_files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import UUID

from gregraph import __version__
from gregraph.core import agents, changes, hooks, versioning
from gregraph.core.config import Config, GitSection, IdsSection, write_config
from gregraph.core.git import GitAdapter
from gregraph.core.graph import Edge, Graph, LinkCheck, Node
from gregraph.core.hashing import (
    asset_hash,
    body_hash,
    effective_content_changed,
    normalise_body,
)
from gregraph.core.ids import generate_id, is_valid_prefix, normalise_id
from gregraph.core.markdown import (
    Section,
    extract_title,
    find_asset_refs,
    find_mentions,
    has_front_matter,
    parse_sections,
)
from gregraph.core.mermaid import export_mermaid
from gregraph.core.models import (
    AssetRef,
    ChangeRequest,
    Deprecation,
    Document,
    Finding,
    Identity,
    Link,
    LinkType,
    OperationRefused,
    TemplateDescriptor,
    TemplateRef,
    TemplateSection,
    Term,
)
from gregraph.core.rules import (
    EDGE_RULES,
    MUTUALLY_EXCLUSIVE_OPPOSITE,
    MUTUALLY_EXCLUSIVE_SAME_PAIR,
    SYMMETRIC_EDGE_TYPES,
    Kind,
    edge_kind_allowed,
)
from gregraph.core.status import Status, StatusReport, WipState, compute_status
from gregraph.core.storage import (
    ASSETS_DIR,
    CHANGES_DIR,
    DOCUMENTS_DIR,
    GLOSSARY_DIR,
    TEMPLATES_RELPATH,
    CacheFileEntry,
    CacheIndex,
    ManagedFiles,
    UnsafePathError,
    assets_dir,
    canonical_json_bytes,
    config_path,
    document_paths,
    iter_changes,
    iter_documents,
    iter_terms,
    managed_path,
    read_body,
    read_sidecar,
    stat_cache_entry,
    templates_dir,
    term_paths,
    write_body,
    write_body_atomic,
    write_cache,
    write_sidecar,
)
from gregraph.core.templates import (
    LoadedTemplate,
    MigrationPlan,
    assemble_sections,
    check_deprecated,
    check_required_sections,
    load_template_dir,
    plan_migration,
    prepare_whole_body,
    render_template,
    resolve_section_inputs,
    resolve_template,
)
from gregraph.core.validation import has_errors, refresh_cache, validate_workspace
from gregraph.core.versioning import effective_version
from gregraph.core.workspace import Workspace

__all__ = [
    "BaselineCreateResult",
    "BaselineListResult",
    "BodyState",
    "BodyUpdateResult",
    "CheckResult",
    "ContextEdge",
    "ContextNeighbor",
    "ContextResult",
    "ContextTarget",
    "ContextTerm",
    "CreateResult",
    "DeprecateResult",
    "DeprecatedTemplateUse",
    "EditResult",
    "ExportGraphResult",
    "InitResult",
    "LinkCandidate",
    "LinkCandidatesResult",
    "LinkResult",
    "LinkView",
    "ListResult",
    "ListRow",
    "MigrateResult",
    "MigrationItem",
    "RefreshResult",
    "RefreshedLink",
    "RepairAgentsResult",
    "RepairCacheResult",
    "RepairIdResult",
    "RepairVersionsResult",
    "RepairedSidecar",
    "RewrittenLink",
    "SchemaCrLifecycle",
    "SchemaEdgeRule",
    "SchemaInfo",
    "SchemaTemplateInfo",
    "SchemaTypeInfo",
    "SetResult",
    "ShowResult",
    "StaleInbound",
    "StaleLink",
    "StatusResult",
    "SupersedeResult",
    "SupersessionChain",
    "SyncResult",
    "TemplateAddResult",
    "TemplateBumpResult",
    "TemplateInfo",
    "TemplateListResult",
    "TemplateShowResult",
    "TemplateVersionInfo",
    "TermAddResult",
    "TermDeprecateResult",
    "TermInfo",
    "TermListResult",
    "TermMention",
    "TermRenameResult",
    "TermUsageResult",
    "UnlinkResult",
    "ValidateResult",
    "baseline_create",
    "baseline_list",
    "body_state",
    "build_context",
    "check",
    "create_document",
    "cr_list",
    "cr_new",
    "cr_reaffirm",
    "cr_reanalyze",
    "cr_scope_add",
    "cr_scope_remove",
    "cr_set",
    "cr_show",
    "deprecate",
    "describe_schema",
    "derive_term_slug",
    "edit_document",
    "export_graph",
    "hook_pre_commit",
    "hooks_install",
    "hooks_status",
    "hooks_uninstall",
    "init_repository",
    "link",
    "link_candidates",
    "link_refresh",
    "list_documents",
    "migrate",
    "record_introduction",
    "repair_agents",
    "repair_cache",
    "repair_regenerate_id",
    "repair_versions",
    "set_fields",
    "show_document",
    "status",
    "supersede",
    "supersession_chain",
    "sync",
    "template_add",
    "template_bump",
    "template_list",
    "template_sections",
    "template_show",
    "term_add",
    "term_deprecate",
    "term_list",
    "term_rename",
    "term_show",
    "term_usage",
    "undeprecate",
    "unlink",
    "update_body",
    "update_sections",
    "validate",
]

#: Tag format of spec §5.4 (``[a-z0-9-]+``, lowercase).
TAG_PATTERN: Final = re.compile(r"[a-z0-9-]+")

#: One ``set`` assignment (spec §13.6): ``tags=…``/``tags+=…``/``tags-=…`` or
#: ``extra.<name>=…`` (empty value removes).
_ASSIGNMENT_PATTERN: Final = re.compile(
    r"^(?P<key>tags|extra\.[^=]+?)(?P<op>\+=|-=|=)(?P<value>.*)$",
    re.DOTALL,
)

#: ``set`` keys outside the allowed set map to the command that owns the field
#: (spec §13.6: "refused with a pointer to the right command"). ``{id}`` in the
#: fix template is replaced with the document ID.
_SET_KEY_HINTS: Final[dict[str, tuple[str, str]]] = {
    "title": ("the title is the H1 of the Markdown body", "gregraph edit {id}"),
    "type": (
        "a document's type is immutable; supersede with a document of the new type",
        "gregraph supersede {id}",
    ),
    "status": (
        "document status is derived; change-request status goes through cr set",
        "gregraph cr set CR status=STATUS",
    ),
    "deprecated": (
        "use the deprecation commands",
        "gregraph deprecate {id} --reason …",
    ),
    "links": ("edges are managed with link and unlink", "gregraph link"),
    "version": ("versions are bumped by the hook or sync", "gregraph sync --bump"),
    "body_hash": ("hashes are owned by the tool", "gregraph sync --bump"),
    "assets": ("assets are recomputed from the body", "gregraph sync"),
    "template": ("the pinned template changes with migrate", "gregraph migrate {id}"),
    "origin_cr": (
        "origin is recorded at creation with new --cr / supersede --cr",
        "gregraph cr list",
    ),
}

#: Types exempt from re-pointing by ``link refresh --follow``: ``supersedes``
#: chains stay quiet (docs/backlog.md S11) and ``conflicts-with`` history edges
#: "remain on the superseded/deprecated documents" (spec §11.2). ``supersedes``
#: is additionally exempt from the target-state refusals.
_FOLLOW_EXEMPT: Final[frozenset[LinkType]] = frozenset({"supersedes", "conflicts-with"})
_STATE_EXEMPT: Final[frozenset[LinkType]] = frozenset({"supersedes"})


# --------------------------------------------------------------------------
# result dataclasses
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateResult:
    """Result of :func:`create_document` (spec §13.2, §2.4.1). Paths are
    repository-relative; ``sections``/``body_text``/``sidecar_document``
    carry the rich authoring payload of AGENT_READINESS §3.2."""

    id: str
    uuid: UUID
    body: Path
    sidecar: Path
    type: str
    template: TemplateRef
    links: tuple[Link, ...]
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()
    kind: str = ""
    version: int = 1
    body_hash: str = ""
    sections: tuple[TemplateSection, ...] = ()
    body_text: str = ""
    sidecar_document: Document | None = None


@dataclass(frozen=True, slots=True)
class LinkResult:
    """Result of :func:`link` (spec §13.3). ``created=False`` is the duplicate
    no-op notice (exit 0, nothing written)."""

    source: str
    type: LinkType
    target: str
    created: bool
    link: Link | None = None
    notice: str | None = None
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnlinkResult:
    """Result of :func:`unlink` (spec §13.4). ``removed_from`` is the endpoint
    whose sidecar held the edge (symmetric edges may sit on either one)."""

    source: str
    type: LinkType
    target: str
    removed: bool
    removed_from: str | None = None
    notice: str | None = None
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SupersessionChain:
    """``supersedes`` successors of one document (spec §7.6, §13.5).

    ``successors`` are the immediate successors of ``start`` (the interactive
    choices); ``end`` is the chain end when every step is unambiguous and
    ``path`` is ``start → … → end``. On a fork (``end`` is ``None``) the split
    is at ``fork_at`` between ``fork_successors``. ``looped`` marks the
    pathological supersession cycle (an already-invalid graph).
    """

    start: str
    successors: tuple[str, ...]
    end: str | None
    path: tuple[str, ...] = ()
    fork_at: str | None = None
    fork_successors: tuple[str, ...] = ()
    looped: bool = False


@dataclass(frozen=True, slots=True)
class RefreshedLink:
    """One link changed by :func:`link_refresh` (spec §13.5)."""

    source: str
    type: LinkType
    old_target: str
    new_target: str
    old_target_version: int
    new_target_version: int

    @property
    def repointed(self) -> bool:
        """Whether the link was re-pointed to a successor (``--follow``)."""
        return self.old_target != self.new_target


@dataclass(frozen=True, slots=True)
class StaleLink:
    """A stale link left untouched by :func:`link_refresh` (spec §13.5).

    The "interactive otherwise" branch: the target is superseded and ``--follow``
    was not given (or the type is re-point exempt), so the link needs a human
    decision; ``chain`` carries the successor information.
    """

    source: str
    type: LinkType
    target: str
    chain: SupersessionChain
    fork_at: str | None = None
    fork_successors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Result of :func:`link_refresh` (spec §13.5)."""

    refreshed: tuple[RefreshedLink, ...] = ()
    stale: tuple[StaleLink, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class BodyUpdateResult:
    """Result of :func:`update_body` (browser editing; spec §5.2, §5.6, §7.3).

    ``body`` is repository-relative; ``body_hash`` is the hash of the normalised
    body now on disk; ``title`` is the H1 read from it (``None`` when missing).
    ``changed`` is ``True`` when the body or the sidecar title was written.
    ``version`` and the other lifecycle fields are never changed here (§7.2).
    """

    id: str
    body: Path
    body_hash: str
    title: str | None
    changed: bool
    findings: tuple[Finding, ...] = ()
    md_path: Path = Path()
    json_path: Path = Path()
    sections: tuple[TemplateSection, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SetResult:
    """Result of :func:`set_fields` (spec §13.6): the document's new state."""

    id: str
    tags: tuple[str, ...]
    extra: dict[str, str]
    changed: bool
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StaleInbound:
    """One inbound link that became stale for a dead target (spec §7.6 step 5)."""

    source: str
    type: LinkType
    target: str
    target_version: int


@dataclass(frozen=True, slots=True)
class SupersedeResult:
    """Result of :func:`supersede` (spec §7.6, §11.2 pattern 1)."""

    id: str
    uuid: UUID
    body: Path
    sidecar: Path
    type: str
    template: TemplateRef
    supersedes: tuple[str, ...]
    copied_links: tuple[Link, ...]
    new: CreateResult | None = None
    skipped_links: tuple[Finding, ...] = ()
    stale_inbound: tuple[StaleInbound, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeprecateResult:
    """Result of :func:`deprecate` / :func:`undeprecate` (spec §13.15)."""

    id: str
    changed: bool
    deprecated: Deprecation | None
    stale_inbound: tuple[StaleInbound, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def _now() -> dt.datetime:
    """Current UTC time at second precision (spec §5.4 ``created``)."""
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _stamp(moment: dt.datetime) -> str:
    """ISO 8601 UTC with ``Z`` suffix (spec §5.4)."""
    return moment.isoformat().replace("+00:00", "Z")


def _unknown_id(raw: str, what: str = "document") -> OperationRefused:
    return OperationRefused(
        Finding(
            code="E-ID-UNKNOWN",
            severity="E",
            subject=raw,
            message=f"no {what} with id {raw!r}",
            fix="gregraph list",
        )
    )


def _resolve_doc_id(workspace: Workspace, raw: str) -> str:
    """Canonical document ID for user input (spec §4.5); refuses ``E-ID-UNKNOWN``."""
    resolved = normalise_id(
        raw, workspace.config.ids.prefix, known=workspace.index.documents
    )
    if resolved is None:
        raise _unknown_id(raw)
    return resolved


def _resolve_cr_id(workspace: Workspace, raw: str) -> str:
    """Canonical change-request ID; refuses ``E-ID-UNKNOWN`` when absent."""
    resolved = normalise_id(
        raw, workspace.config.ids.prefix, known=workspace.index.changes
    )
    if resolved is None:
        raise _unknown_id(raw, what="change request")
    return resolved


def _target_id(workspace: Workspace, raw: str) -> str:
    """Canonical form of a link-target argument, or ``raw`` when unknown.

    A missing target is the link layer's ``E-LINK-TARGET-MISSING`` (spec §13.3),
    not ``E-ID-UNKNOWN`` — :func:`unlink` must still be able to remove broken
    edges (spec §14 fix suggestions).
    """
    resolved = normalise_id(
        raw, workspace.config.ids.prefix, known=workspace.index.documents
    )
    return raw if resolved is None else resolved


def _has_unbumped_modifications(
    workspace: Workspace, document: Document, body: Path
) -> bool:
    """Whether effective content differs from the stored hashes (spec §7.2, §7.3).

    Hash-based mirror of the status layer's "modified, unbumped" computation:
    a missing body counts as modified; assets are recomputed from the body's
    references that exist (spec §5.7).
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


def _item_in_grace(workspace: Workspace, model: _ItemModel, body_rel: Path) -> bool:
    """Initial-grace state of a managed item (spec §3.3, AGENT-012).

    A ``v1`` item whose body is absent from Git ``HEAD`` (untracked or
    staged-but-uncommitted) is being populated: reconcile updates its hashes
    in place and its effective version stays ``1``. Degraded mode has no
    commit step and therefore no grace period (AGENT-014).
    """
    if not workspace.git.is_repo() or model.version != 1:
        return False
    if not (workspace.root / body_rel).is_file():
        return False
    return workspace.git.file_at("HEAD", body_rel) is None


def _effective_version(workspace: Workspace, doc_id: str) -> int:
    """Target's effective version (spec §7.4): ``version + 1`` when the target
    has unbumped modifications, else ``version`` — but ``1`` while a ``v1``
    target is in the initial-grace state (§3.3 rule 3, D-AGENT-3).

    The workspace layer supplies the pre-computed flags of
    :class:`gregraph.core.versioning.UnbumpedMixin`.
    """
    loaded = workspace.index.documents[doc_id]
    unbumped = _has_unbumped_modifications(workspace, loaded.model, loaded.body)
    object.__setattr__(loaded.model, "_unbumped", unbumped)
    object.__setattr__(
        loaded.model, "_in_grace", _item_in_grace(workspace, loaded.model, loaded.body)
    )
    return effective_version(loaded.model)


def _compute_assets(
    workspace: Workspace, body_rel: Path, body: str, doc_id: str
) -> list[AssetRef]:
    """Stored asset references of a fresh body (spec §5.7): existing, owned."""
    assets: list[AssetRef] = []
    for ref in find_asset_refs(body, doc_path=body_rel, doc_id=doc_id):
        if ref.foreign:
            continue
        file = workspace.root / ref.path
        if file.is_file():
            assets.append(
                AssetRef(
                    path=str(Path(*ref.path.parts[2:])),
                    hash=asset_hash(file.read_bytes()),
                )
            )
    return assets


def _check_tags(tags: Sequence[str]) -> None:
    """Refuse tags outside the §5.4 format with ``E-TAG-INVALID``."""
    for tag in tags:
        if TAG_PATTERN.fullmatch(tag) is None:
            raise OperationRefused(
                Finding(
                    code="E-TAG-INVALID",
                    severity="E",
                    subject=tag,
                    message=f"invalid tag {tag!r}: tags are lowercase [a-z0-9-]+",
                    fix="gregraph set ID tags=a,b",
                )
            )


def _check_link_type(link_type: str) -> LinkType:
    """Refuse an edge type outside the §6.1 fixed set (``E-LINK-TYPE-UNKNOWN``)."""
    if link_type not in EDGE_RULES:
        raise OperationRefused(
            Finding(
                code="E-LINK-TYPE-UNKNOWN",
                severity="E",
                subject=link_type,
                message=f"unknown edge type {link_type!r}",
                fix="gregraph link --help",
            )
        )
    return link_type


def _read_doc(workspace: Workspace, doc_id: str) -> Document:
    """Read a document sidecar fresh from disk (spec §5.4)."""
    return read_sidecar(
        workspace.root / workspace.index.documents[doc_id].sidecar, Document
    )


def _write_doc(workspace: Workspace, doc_id: str, document: Document) -> None:
    """Write a document sidecar in canonical form (spec §5.4)."""
    write_sidecar(workspace.root / workspace.index.documents[doc_id].sidecar, document)


def _replace_title(body: str, title: str) -> str:
    """Return ``body`` with its H1 line replaced by ``# {title}`` (spec §5.6)."""
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# ") and not line.startswith("## "):
            lines[index] = f"# {title}"
        else:
            lines.insert(index, f"# {title}")
        break
    else:
        lines.append(f"# {title}")
    return "\n".join(lines)


def _pick_template(
    workspace: Workspace,
    name: str,
    *,
    version: int | None,
    allow_deprecated: bool = False,
) -> LoadedTemplate:
    """Resolve one template version; refuses ``E-TEMPLATE-UNKNOWN`` /
    ``W-TEMPLATE-DEPRECATED`` (spec §5.5)."""
    versions = load_template_dir(templates_dir(workspace.root)).get(name)
    if not versions:
        raise OperationRefused(
            Finding(
                code="E-TEMPLATE-UNKNOWN",
                severity="E",
                subject=name,
                message=f"template {name!r} not found in the repository",
                fix="gregraph template list",
            )
        )
    try:
        picked = resolve_template(versions, version=version)
    except ValueError as exc:
        if version is not None:
            raise OperationRefused(
                Finding(
                    code="E-TEMPLATE-UNKNOWN",
                    severity="E",
                    subject=name,
                    message=str(exc),
                    fix="gregraph template list",
                )
            ) from exc
        # every version is deprecated: fall through to check_deprecated so the
        # refusal explains --template-version/--allow-deprecated (spec §5.5)
        picked = versions[-1]
    refusal = check_deprecated(
        picked,
        version_pinned=version is not None,
        allow_deprecated=allow_deprecated,
    )
    if refusal is not None:
        raise OperationRefused(refusal)
    return picked


def _render_body(
    template: LoadedTemplate,
    *,
    title: str,
    doc_id: str,
    type_name: str,
    kind: str,
    created: dt.datetime,
    author: str,
) -> str:
    """Render ``template.md`` for a new document (spec §5.5, §5.6)."""
    return render_template(
        template,
        title=title,
        id=doc_id,
        type=type_name,
        kind=kind,
        created=_stamp(created),
        author=author,
        sections=[section.heading for section in template.descriptor.sections],
    )


def _identity_findings(workspace: Workspace, doc_id: str) -> tuple[Finding, ...]:
    """``W-NO-GIT-IDENTITY`` when ``created_by`` cannot be filled (spec §5.4:
    ``new`` warns)."""
    if workspace.git.identity() is not None:
        return ()
    return (
        Finding(
            code="W-NO-GIT-IDENTITY",
            severity="W",
            subject=doc_id,
            message="git identity unavailable; created_by is null",
            fix='git config user.name "…" && git config user.email "…"',
        ),
    )


def _check_cr_enabled(workspace: Workspace, cr_id: str) -> None:
    """Refuse ``--cr`` while ``cr.enabled = false`` (spec §14 ``E-CR-DISABLED``)."""
    if not workspace.config.cr.enabled:
        raise OperationRefused(
            Finding(
                code="E-CR-DISABLED",
                severity="E",
                subject=cr_id,
                message="change requests are disabled in config.toml",
                fix="set cr.enabled = true in config.toml",
            )
        )


def _existing_ids(workspace: Workspace) -> set[str]:
    """Every ID in the shared document/CR ID space (spec §2, §4.2)."""
    return set(workspace.index.documents) | set(workspace.index.changes)


def _extended_graph(workspace: Workspace, node: Node, edges: Sequence[Link]) -> Graph:
    """``workspace.graph`` plus ``node`` and source edges from ``node`` (spec §6)."""
    extra = tuple(
        Edge(source=node.id, type=edge.type, target=edge.target) for edge in edges
    )
    return Graph(
        [*workspace.graph.nodes.values(), node], (*workspace.graph.edges, *extra)
    )


def _raise_if_refused(check: LinkCheck) -> None:
    """Raise the refusal of a ``LinkCheck``, if any (spec §13.3)."""
    if check.refusal is not None:
        raise OperationRefused(check.refusal)


def _stale_inbound(workspace: Workspace, doc_id: str) -> tuple[StaleInbound, ...]:
    """Inbound links of ``doc_id`` that become stale when it dies (spec §7.6.5).

    ``supersedes`` edges are exempt (they are the supersession; docs/backlog.md).
    """
    graph = workspace.graph
    result: list[StaleInbound] = []
    for edge in graph.inbound_edges(doc_id):
        if edge.type == "supersedes" or edge.type not in EDGE_RULES:
            continue
        source_loaded = workspace.index.documents.get(edge.source)
        if source_loaded is None:
            continue
        for link in source_loaded.model.links:
            if link.type == edge.type and link.target == edge.target:
                result.append(
                    StaleInbound(
                        source=edge.source,
                        type=link.type,
                        target=link.target,
                        target_version=link.target_version,
                    )
                )
    return tuple(sorted(result, key=lambda item: (item.source, item.type, item.target)))


def supersession_chain(workspace: Workspace, doc_id: str) -> SupersessionChain:
    """Follow the ``supersedes`` successors of ``doc_id`` to the chain end (spec §7.6).

    Pure query used by ``link refresh --follow`` and the interactive picker
    branch of §13.5. A fork (``OLD`` superseded by two documents) yields
    ``end=None`` with ``fork_at``/``fork_successors``.
    """
    graph = workspace.graph

    def successors_of(current: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    edge.source
                    for edge in graph.inbound_edges(current)
                    if edge.type == "supersedes" and edge.source in graph.nodes
                }
            )
        )

    first = successors_of(doc_id)
    path = [doc_id]
    seen = {doc_id}
    current = doc_id
    while True:
        successors = successors_of(current)
        if not successors:
            return SupersessionChain(
                start=doc_id, successors=first, end=current, path=tuple(path)
            )
        if len(successors) > 1:
            return SupersessionChain(
                start=doc_id,
                successors=first,
                end=None,
                fork_at=current,
                fork_successors=successors,
            )
        nxt = successors[0]
        if nxt in seen:
            return SupersessionChain(
                start=doc_id,
                successors=first,
                end=None,
                fork_at=current,
                fork_successors=successors,
                looped=True,
            )
        seen.add(nxt)
        path.append(nxt)
        current = nxt


# --------------------------------------------------------------------------
# document lifecycle (S12, spec §13.2–13.6, §13.14–13.15)
# --------------------------------------------------------------------------


def create_document(
    workspace: Workspace,
    *,
    type: str,
    title: str,
    template: str | None = None,
    template_version: int | None = None,
    allow_deprecated: bool = False,
    tags: Sequence[str] = (),
    links: Sequence[tuple[LinkType, str]] = (),
    cr: str | None = None,
    sections: Sequence[tuple[str, str]] = (),
    body_text: str | None = None,
    strict: bool = False,
) -> CreateResult:
    """Create a document (spec §13.2 `new`, §3.4).

    Generates the ID (§4.2), renders the resolved template (§5.5), writes the
    body and sidecar pair (§5.4) and creates the initial links, each checked
    like :func:`link` (§13.3) against the graph plus the already-accepted
    initial links. ``body_text`` (whole-body ``--body``) replaces the skeleton
    with the tool-owned ``# <title>`` H1 (§3.4 rule 4); ``sections``
    assembles the body from per-section input in template order; ``strict``
    requires every required section to be filled at write time (§3.4 rules
    5–6). ``--edit`` is the CLI's job; ``cr`` wires S13's
    :func:`record_introduction` (origin tracking, §9.5) before any file is
    written. Refusals (unknown type/template, deprecated template, a refused
    initial link, template-section refusals) write nothing.
    """
    if sections and body_text is not None:
        raise ValueError("cannot combine --body and --section")
    spec = workspace.config.types.get(type)
    if spec is None:
        raise OperationRefused(
            Finding(
                code="E-TYPE-UNKNOWN",
                severity="E",
                subject=type,
                message=f"unknown document type {type!r}",
            )
        )
    _check_tags(tags)
    picked = _pick_template(
        workspace,
        template if template is not None else spec.template,
        version=template_version,
        allow_deprecated=allow_deprecated,
    )
    generated = generate_id(_existing_ids(workspace), workspace.config.ids.prefix)
    created = _now()
    identity = workspace.git.identity()
    author = identity.name if identity is not None else ""
    rendered_body = _render_body(
        picked,
        title=title,
        doc_id=generated.id,
        type_name=type,
        kind=spec.kind,
        created=created,
        author=author,
    )
    body_notices: list[str] = []
    if body_text is not None:
        rendered_body, body_notices = prepare_whole_body(body_text, title=title)
        if strict:
            check_required_sections(picked.descriptor, rendered_body)
    elif sections:
        resolved_sections = resolve_section_inputs(picked.descriptor, sections)
        rendered_body = assemble_sections(
            picked.descriptor,
            title=title,
            content=resolved_sections,
            base_body=rendered_body,
            preserve_existing=False,
        )
        check_required_sections(
            picked.descriptor,
            rendered_body,
            provided_headings=set(resolved_sections),
            require_provided=True,
        )
    elif strict:
        check_required_sections(picked.descriptor, rendered_body)
    abs_body, abs_sidecar = document_paths(workspace.root, spec.folder, generated.id)
    body_rel = abs_body.relative_to(workspace.root)
    sidecar_rel = abs_sidecar.relative_to(workspace.root)

    node = Node(id=generated.id, kind=spec.kind, title=title, deprecated=False)
    graph = _extended_graph(workspace, node, ())
    written: list[Link] = []
    notices: list[str] = []
    for raw_type, raw_target in links:
        edge_type = _check_link_type(raw_type)
        target = _target_id(workspace, raw_target)
        check = graph.check_link(generated.id, edge_type, target)
        _raise_if_refused(check)
        if check.outcome == "duplicate":
            notices.append(
                f"duplicate initial link {generated.id} {edge_type} {target} ignored"
            )
            continue
        entry = Link(
            type=edge_type,
            target=target,
            target_version=_effective_version(workspace, target),
        )
        graph, _ = graph.with_link(generated.id, edge_type, target)
        written.append(entry)

    cr_id: str | None = None
    if cr is not None:
        _check_cr_enabled(workspace, cr)
        cr_id = _resolve_cr_id(workspace, cr)
        record_introduction(workspace, cr_id=cr_id, doc_id=generated.id)

    document = Document(
        schema=1,
        uuid=generated.uuid,
        id=generated.id,
        type=type,
        title=title,
        created=created,
        created_by=identity,
        template=TemplateRef(name=picked.name, version=picked.version),
        version=1,
        body_hash=body_hash(rendered_body),
        assets=_compute_assets(workspace, body_rel, rendered_body, generated.id),
        links=written,
        deprecated=None,
        tags=list(dict.fromkeys(tags)),
        extra={},
        origin_cr=cr_id,
    )
    write_body(abs_body, rendered_body)
    write_sidecar(abs_sidecar, document)
    workspace.reload()
    return CreateResult(
        id=generated.id,
        uuid=generated.uuid,
        body=body_rel,
        sidecar=sidecar_rel,
        type=type,
        template=document.template,
        links=tuple(written),
        findings=_identity_findings(workspace, generated.id),
        notices=tuple([*notices, *body_notices]),
        kind=spec.kind,
        version=document.version,
        body_hash=document.body_hash,
        sections=tuple(picked.descriptor.sections),
        body_text=rendered_body,
        sidecar_document=document,
    )


def link(
    workspace: Workspace,
    *,
    source: str,
    link_type: LinkType,
    target: str,
) -> LinkResult:
    """Add one edge (spec §13.3).

    Rules, mutual exclusion, duplicates and target state are classified by
    :meth:`gregraph.core.graph.Graph.check_link` (§6.4, §13.3): a refusal raises
    ``OperationRefused`` (``E-EDGE-RULE``, ``E-EDGE-EXCLUSIVE``, ``E-CYCLE``
    with the reconstructed path, ``E-TARGET-SUPERSEDED``/``E-TARGET-DEPRECATED``
    except for ``supersedes``, ``E-LINK-TARGET-MISSING``); a duplicate is a no-op
    notice (exit 0). ``target_version`` is the target's *effective* version
    (§7.4).
    """
    edge_type = _check_link_type(link_type)
    source_id = _resolve_doc_id(workspace, source)
    target_id = _target_id(workspace, target)
    check = workspace.graph.check_link(source_id, edge_type, target_id)
    _raise_if_refused(check)
    if check.outcome == "duplicate":
        notice = f"edge {source_id} {edge_type} {target_id} already exists"
        return LinkResult(
            source=source_id,
            type=edge_type,
            target=target_id,
            created=False,
            notice=notice,
            notices=(notice,),
        )
    entry = Link(
        type=edge_type,
        target=target_id,
        target_version=_effective_version(workspace, target_id),
    )
    document = _read_doc(workspace, source_id)
    document.links = [*document.links, entry]
    _write_doc(workspace, source_id, document)
    workspace.reload()
    return LinkResult(
        source=source_id,
        type=edge_type,
        target=target_id,
        created=True,
        link=entry,
    )


def unlink(
    workspace: Workspace,
    *,
    source: str,
    link_type: LinkType,
    target: str,
) -> UnlinkResult:
    """Remove one edge (spec §13.4).

    Symmetric edges (§6.1) are found on either endpoint. Removing an edge that
    does not exist is a no-op notice; a broken edge (missing target) can still
    be removed — that is how validate's ``E-LINK-TARGET-MISSING`` fix works.
    """
    edge_type = _check_link_type(link_type)
    source_id = _resolve_doc_id(workspace, source)
    target_id = _target_id(workspace, target)

    holder: str | None = None
    drop: tuple[str, str] | None = None
    for doc_id, other in ((source_id, target_id), (target_id, source_id)):
        if doc_id not in workspace.index.documents:
            continue
        for entry in _read_doc(workspace, doc_id).links:
            if entry.type == edge_type and entry.target == other:
                holder = doc_id
                drop = (edge_type, other)
                break
        if holder is not None:
            break
        if edge_type not in SYMMETRIC_EDGE_TYPES:
            break

    if holder is None or drop is None:
        notice = f"no edge {source_id} {edge_type} {target_id}"
        return UnlinkResult(
            source=source_id,
            type=edge_type,
            target=target_id,
            removed=False,
            notice=notice,
            notices=(notice,),
        )
    document = _read_doc(workspace, holder)
    document.links = [
        entry
        for entry in document.links
        if not (entry.type == drop[0] and entry.target == drop[1])
    ]
    _write_doc(workspace, holder, document)
    workspace.reload()
    return UnlinkResult(
        source=source_id,
        type=edge_type,
        target=target_id,
        removed=True,
        removed_from=holder,
    )


def link_refresh(
    workspace: Workspace,
    *,
    source: str | None = None,
    link_type: LinkType | None = None,
    target: str | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
    select_all: bool = False,
    follow: bool = False,
    dry_run: bool = False,
) -> RefreshResult:
    """Refresh ``target_version`` of the selected links (spec §13.5).

    Selection: one edge (``source``/``link_type``/``target``), ``--from``
    (outbound of one document), ``--to`` (inbound of one document) or
    ``--all``. Fresh/outdated links get the target's *effective* version (§7.4).
    Stale links (target superseded): with ``--follow`` the edge is re-pointed to
    the end of the ``supersedes`` chain (a fork refuses ``E-SUPERSEDE-FORK``);
    without it the edge is left untouched and reported with its chain for the
    interactive branch — core never prompts. Deprecated targets refuse
    ``E-TARGET-DEPRECATED``. ``supersedes`` (chains stay quiet) and
    ``conflicts-with`` (§11.2 history) edges are never re-pointed. Refusals are
    atomic: nothing is written when any selected link refuses.
    """
    modes = (
        source is not None,
        from_id is not None,
        to_id is not None,
        select_all,
    )
    if sum(modes) != 1:
        raise ValueError(
            "link_refresh needs exactly one of: source+link_type+target, "
            "from_id, to_id, select_all"
        )

    selected: list[tuple[str, Link]] = []
    notices: list[str] = []
    if source is not None:
        if link_type is None or target is None:
            raise ValueError("link_refresh by edge needs source, link_type and target")
        source_id = _resolve_doc_id(workspace, source)
        edge_type = _check_link_type(link_type)
        target_id = _target_id(workspace, target)
        selected = [
            (source_id, entry)
            for entry in workspace.index.documents[source_id].model.links
            if entry.type == edge_type and entry.target == target_id
        ]
        if not selected:
            notices.append(f"no link {source_id} {edge_type} {target_id}")
    elif from_id is not None:
        from_doc = _resolve_doc_id(workspace, from_id)
        selected = [
            (from_doc, entry)
            for entry in workspace.index.documents[from_doc].model.links
        ]
    elif to_id is not None:
        to_doc = _resolve_doc_id(workspace, to_id)
        selected = [
            (doc_id, entry)
            for doc_id in sorted(workspace.index.documents)
            for entry in workspace.index.documents[doc_id].model.links
            if entry.target == to_doc
        ]
    else:
        selected = [
            (doc_id, entry)
            for doc_id in sorted(workspace.index.documents)
            for entry in workspace.index.documents[doc_id].model.links
        ]
    if not selected and not notices:
        notices.append("no matching links")

    graph = workspace.graph
    changes: dict[str, dict[tuple[str, str], Link | None]] = {}
    planned: list[RefreshedLink] = []
    stale: list[StaleLink] = []
    findings: list[Finding] = []

    for source_id, entry in selected:
        edge_type = entry.type
        target_id = entry.target
        if target_id not in workspace.index.documents:
            raise OperationRefused(
                Finding(
                    code="E-LINK-TARGET-MISSING",
                    severity="E",
                    subject=source_id,
                    message=(f"edge {edge_type} → {target_id}: target does not exist"),
                    fix=f"gregraph unlink {source_id} {edge_type} {target_id}",
                )
            )
        if edge_type in _STATE_EXEMPT:
            planned_version = _effective_version(workspace, target_id)
            if planned_version != entry.target_version:
                changes.setdefault(source_id, {})[(edge_type, target_id)] = Link(
                    type=edge_type, target=target_id, target_version=planned_version
                )
                planned.append(
                    RefreshedLink(
                        source_id,
                        edge_type,
                        target_id,
                        target_id,
                        entry.target_version,
                        planned_version,
                    )
                )
            continue
        if graph.is_deprecated(target_id):
            raise OperationRefused(
                Finding(
                    code="E-TARGET-DEPRECATED",
                    severity="E",
                    subject=source_id,
                    message=(
                        f"target {target_id} is deprecated; unlink or link elsewhere"
                    ),
                    fix=f"gregraph unlink {source_id} {edge_type} {target_id}",
                )
            )
        if graph.is_superseded(target_id):
            chain = supersession_chain(workspace, target_id)
            if chain.looped:
                raise OperationRefused(
                    Finding(
                        code="E-CYCLE",
                        severity="E",
                        subject=source_id,
                        message=(
                            "supersession chain from "
                            f"{target_id} loops: {' → '.join(chain.path)}"
                        ),
                    )
                )
            follow_here = follow and edge_type not in _FOLLOW_EXEMPT
            if chain.end is not None and follow_here:
                new_target = chain.end
                check = graph.check_link(source_id, edge_type, new_target)
                _raise_if_refused(check)
                if check.outcome == "duplicate":
                    existing = next(
                        item
                        for item in workspace.index.documents[source_id].model.links
                        if item.type == edge_type and item.target == new_target
                    )
                    changes.setdefault(source_id, {})[(edge_type, target_id)] = None
                    planned.append(
                        RefreshedLink(
                            source_id,
                            edge_type,
                            target_id,
                            new_target,
                            entry.target_version,
                            existing.target_version,
                        )
                    )
                    notices.append(
                        f"{source_id} already has {edge_type} → {new_target}; "
                        f"removed the stale edge to {target_id}"
                    )
                    continue
                new_version = _effective_version(workspace, new_target)
                changes.setdefault(source_id, {})[(edge_type, target_id)] = Link(
                    type=edge_type, target=new_target, target_version=new_version
                )
                planned.append(
                    RefreshedLink(
                        source_id,
                        edge_type,
                        target_id,
                        new_target,
                        entry.target_version,
                        new_version,
                    )
                )
                continue
            if chain.end is None and follow_here:
                raise OperationRefused(
                    Finding(
                        code="E-SUPERSEDE-FORK",
                        severity="E",
                        subject=source_id,
                        message=(
                            f"supersession chain from {target_id} forks at "
                            f"{chain.fork_at}: {', '.join(chain.fork_successors)}; "
                            "choose the successor interactively"
                        ),
                        fix=(
                            f"gregraph link refresh {source_id} {edge_type} "
                            f"{target_id} --follow"
                        ),
                    )
                )
            stale.append(
                StaleLink(
                    source=source_id,
                    type=edge_type,
                    target=target_id,
                    chain=chain,
                    fork_at=chain.fork_at,
                    fork_successors=chain.fork_successors,
                )
            )
            findings.append(
                Finding(
                    code="W-LINK-STALE",
                    severity="W",
                    subject=source_id,
                    message=f"link {edge_type} → {target_id}: target is superseded",
                    fix=(
                        f"gregraph link refresh {source_id} {edge_type} "
                        f"{target_id} --follow"
                    ),
                )
            )
            continue
        planned_version = _effective_version(workspace, target_id)
        if planned_version != entry.target_version:
            changes.setdefault(source_id, {})[(edge_type, target_id)] = Link(
                type=edge_type, target=target_id, target_version=planned_version
            )
            planned.append(
                RefreshedLink(
                    source_id,
                    edge_type,
                    target_id,
                    target_id,
                    entry.target_version,
                    planned_version,
                )
            )

    if not dry_run:
        for doc_id, replacements in sorted(changes.items()):
            document = _read_doc(workspace, doc_id)
            new_links: list[Link] = []
            for entry in document.links:
                key = (entry.type, entry.target)
                if key in replacements:
                    replacement = replacements[key]
                    if replacement is not None:
                        new_links.append(replacement)
                else:
                    new_links.append(entry)
            document.links = new_links
            _write_doc(workspace, doc_id, document)
        if changes:
            workspace.reload()
    return RefreshResult(
        refreshed=tuple(planned),
        stale=tuple(stale),
        findings=tuple(findings),
        notices=tuple(notices),
        dry_run=dry_run,
    )


def set_fields(
    workspace: Workspace,
    *,
    doc_id: str,
    assignments: Sequence[str],
) -> SetResult:
    """Apply ``key=value`` assignments to a document (spec §13.6 `set`).

    Allowed: ``tags=a,b`` (replace), ``tags+=x`` / ``tags-=x`` (add/remove),
    ``extra.<name>=value`` and ``extra.<name>=`` (remove). Everything else is
    refused with a pointer to the command that owns the field
    (``E-SET-KEY``); malformed assignments are ``E-SET-VALUE`` and invalid tags
    ``E-TAG-INVALID`` (§5.4). All assignments are validated before anything is
    written.
    """
    doc_id = _resolve_doc_id(workspace, doc_id)
    document = _read_doc(workspace, doc_id)
    before_tags = tuple(document.tags)
    before_extra = dict(document.extra)
    notices: list[str] = []

    def refuse_key(text: str, key: str) -> OperationRefused:
        hint, fix = _SET_KEY_HINTS.get(
            key,
            (f"{key!r} is owned by the tool", "gregraph show {id}"),
        )
        return OperationRefused(
            Finding(
                code="E-SET-KEY",
                severity="E",
                subject=text,
                message=f"cannot set {key!r} with `gregraph set`: {hint}",
                fix=fix.format(id=doc_id),
            )
        )

    def refuse_value(text: str, message: str) -> OperationRefused:
        return OperationRefused(
            Finding(code="E-SET-VALUE", severity="E", subject=text, message=message)
        )

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
        if key == "tags":
            if op == "=":
                new_tags = [item.strip() for item in value.split(",") if item.strip()]
                _check_tags(new_tags)
                document.tags = list(dict.fromkeys(new_tags))
            elif op == "+=":
                tag = value.strip()
                _check_tags([tag])
                if tag not in document.tags:
                    document.tags = [*document.tags, tag]
            else:
                tag = value.strip()
                _check_tags([tag])
                if tag not in document.tags:
                    notices.append(f"tag {tag!r} was not present")
                document.tags = [item for item in document.tags if item != tag]
        elif key.startswith("extra.") and len(key) > len("extra."):
            if op != "=":
                raise refuse_value(
                    text, f"{op} is only allowed for tags; set {key} with ="
                )
            if value == "":
                if key[len("extra.") :] not in document.extra:
                    notices.append(f"{key} was not present")
                document.extra.pop(key[len("extra.") :], None)
            else:
                document.extra[key[len("extra.") :]] = value
        else:
            raise refuse_key(text, key)

    changed = (
        tuple(document.tags) != before_tags or dict(document.extra) != before_extra
    )
    if changed:
        _write_doc(workspace, doc_id, document)
        workspace.reload()
    return SetResult(
        id=doc_id,
        tags=tuple(document.tags),
        extra=dict(document.extra),
        changed=changed,
        notices=tuple(notices),
    )


def _body_findings(doc_id: str, body: str) -> tuple[Finding, ...]:
    """H1 and front-matter findings of a normalised body (spec §5.2, §5.6, §14).

    Same codes and messages as :func:`gregraph.core.validation.check_document_bodies`.
    """
    findings: list[Finding] = []
    if extract_title(body) is None:
        findings.append(
            Finding(
                code="E-TITLE-MISSING",
                severity="E",
                subject=doc_id,
                message="no H1 title as the first non-blank line",
                fix=f"gregraph edit {doc_id}",
            )
        )
    if has_front_matter(body):
        findings.append(
            Finding(
                code="E-FRONTMATTER-FORBIDDEN",
                severity="E",
                subject=doc_id,
                message="body starts with '---'; YAML front matter is forbidden",
                fix=f"gregraph edit {doc_id}",
            )
        )
    return tuple(findings)


def _managed_document_files(workspace: Workspace, loaded: Any) -> tuple[Path, Path]:
    """Absolute ``(body, sidecar)`` paths that are safe to read and write.

    Both targets are checked before anything is read or written (spec §3,
    ``E-PATH-UNSAFE``): a link at either path, or in a folder above it, refuses the
    save even when the other file is a plain file.
    """
    try:
        return (
            managed_path(workspace.root, loaded.body),
            managed_path(workspace.root, loaded.sidecar),
        )
    except UnsafePathError as exc:
        raise OperationRefused(
            Finding(
                code="E-PATH-UNSAFE",
                severity="E",
                subject=exc.relative,
                message=f"refusing to write through an unsafe path: {exc.reason}",
            )
        ) from exc


def _pinned_descriptor(workspace: Workspace, ref: TemplateRef) -> TemplateDescriptor:
    """Descriptor of the pinned template version; refuses ``E-TEMPLATE-UNKNOWN``."""
    versions = load_template_dir(templates_dir(workspace.root)).get(ref.name)
    if versions is not None:
        for candidate in versions:
            if candidate.version == ref.version:
                return candidate.descriptor
    raise OperationRefused(
        Finding(
            code="E-TEMPLATE-UNKNOWN",
            severity="E",
            subject=f"{ref.name}/v{ref.version}",
            message=f"template {ref.name!r} v{ref.version} is not in the repository",
            fix="gregraph template list",
        )
    )


def _optional_template_sections(
    workspace: Workspace, ref: TemplateRef
) -> tuple[TemplateSection, ...]:
    """Sections of the pinned template, or ``()`` when it cannot be resolved.

    Metadata for result payloads (§2.4): a document pinned to a template
    version that is no longer in the repository is a validation finding
    (``E-TEMPLATE-UNKNOWN``), not a reason to refuse an otherwise valid save.
    """
    versions = load_template_dir(templates_dir(workspace.root)).get(ref.name)
    if versions is not None:
        for candidate in versions:
            if candidate.version == ref.version:
                return tuple(candidate.descriptor.sections)
    return ()


def template_sections(
    workspace: Workspace, *, template: TemplateRef
) -> tuple[TemplateSection, ...]:
    """Sections of one pinned template version (AGENT_READINESS §3.5).

    Refuses ``E-TEMPLATE-UNKNOWN`` when the pinned version is not in the
    repository. Used by ``new``/``edit``/``schema`` and the CLI section
    assembly; callers that only decorate a payload use
    :func:`_optional_template_sections`.
    """
    return tuple(_pinned_descriptor(workspace, template).sections)


@dataclass(frozen=True, slots=True)
class BodyState:
    """Current on-disk body of a document: text, hash, parsed sections.

    ``body_hash`` doubles as the ``base_hash`` of a subsequent
    :func:`update_body`/`func`:update_sections`` call (spec §21.5, §3.5);
    ``sections`` are the level-2 sections of ``text``.
    """

    id: str
    body: Path
    text: str
    body_hash: str
    sections: tuple[Section, ...]


def body_state(workspace: Workspace, *, doc_id: str) -> BodyState:
    """Read a document's body for editing workflows (AGENT_READINESS §3.5).

    ``E-BODY-MISSING`` when the body file is gone; unknown, malformed,
    change-request and glossary IDs are refused ``E-ID-UNKNOWN`` (§4.5).
    """
    resolved = _resolve_doc_id(workspace, doc_id)
    loaded = workspace.index.documents[resolved]
    try:
        text = read_body(workspace.root / loaded.body)
    except OSError as exc:
        raise OperationRefused(
            Finding(
                code="E-BODY-MISSING",
                severity="E",
                subject=resolved,
                message="the body file is missing; nothing was written",
            )
        ) from exc
    return BodyState(
        id=resolved,
        body=loaded.body,
        text=text,
        body_hash=body_hash(text),
        sections=tuple(parse_sections(text)),
    )


def update_sections(
    workspace: Workspace,
    *,
    doc_id: str,
    content: Mapping[str, str] | Sequence[tuple[str, str]],
    base_hash: str,
    strict: bool = False,
) -> BodyUpdateResult:
    """Assemble the body from per-section content and write it (§3.4, §21.5).

    ``content`` maps template-canonical headings to section content; unknown
    headings refuse ``E-SECTION-UNKNOWN`` with the template's section
    specification in ``details`` (AGENT-017). Unmentioned sections keep their
    existing content verbatim, extra level-2 sections are kept at the end
    (AGENT-016). The staleness guard (``E-BODY-STALE``) runs before assembly
    so a lost update never merges; required sections must be filled in the
    assembled body (AGENT-018). The write goes through :func:`update_body`,
    which syncs the sidecar title from the H1.
    """
    resolved = _resolve_doc_id(workspace, doc_id)
    loaded = workspace.index.documents[resolved]
    descriptor = _pinned_descriptor(workspace, loaded.model.template)
    body_path = workspace.root / loaded.body
    if not body_path.is_file():
        raise OperationRefused(
            Finding(
                code="E-BODY-MISSING",
                severity="E",
                subject=resolved,
                message="the body file is missing; nothing was written",
            )
        )
    current_text = read_body(body_path)
    current_hash = body_hash(current_text)
    if current_hash != base_hash:
        raise OperationRefused(
            Finding(
                code="E-BODY-STALE",
                severity="E",
                subject=resolved,
                message=(
                    f"body changed since it was read (base {base_hash!r}, "
                    f"current {current_hash!r}); reload and retry"
                ),
                fix=f"gregraph edit {resolved}",
            )
        )
    entries: list[tuple[str, str]] = (
        list(content.items()) if isinstance(content, Mapping) else list(content)
    )
    resolved_content = resolve_section_inputs(descriptor, entries)
    new_body = assemble_sections(
        descriptor,
        title=loaded.model.title,
        content=resolved_content,
        base_body=current_text,
        preserve_existing=True,
    )
    check_required_sections(descriptor, new_body, subject=resolved)
    return update_body(
        workspace, doc_id=resolved, text=new_body, base_hash=base_hash, strict=strict
    )


def update_body(
    workspace: Workspace,
    *,
    doc_id: str,
    text: str,
    base_hash: str,
    strict: bool = False,
    notices: Sequence[str] = (),
) -> BodyUpdateResult:
    """Replace a document's Markdown body from a browser editor (spec §21.5).

    ``base_hash`` is the body hash the editor read (``sha256:`` of the normalised
    working-tree body, §7.3). When it no longer matches, the save is refused with
    ``E-BODY-STALE`` and nothing is written. Both target files are checked for
    unsafe links first (``E-PATH-UNSAFE``). The Markdown is saved exactly as given,
    except that CRLF and CR become LF (spec §5.2). Trailing spaces (Markdown hard
    breaks), blank lines and the final newline are kept as typed. The §7.3
    normalisation applies to the hash only. The existing sync command normalises
    whole files under its own workflow (§7.5). This operation does not, so a save
    never rewrites Markdown the user did not change.

    ``strict`` (``edit --strict``, §3.4 rule 6) refuses
    ``E-SECTION-REQUIRED-EMPTY`` when a required section of the pinned template
    is empty-or-placeholder in the saved text — checked before anything is
    written. ``notices`` are carried through to the result (§2.4: the payload's
    ``notices`` array).

    Only the body and, when its H1 differs, the sidecar ``title`` are written.
    ``version``, ``body_hash``, ``assets``, ``links`` and every other field are left
    to the commit-time reconcile pass (§7.2, §7.5). A missing H1 or front matter is
    saved and reported as a finding, not refused. Unknown, malformed, change-request
    and glossary IDs are refused ``E-ID-UNKNOWN`` (§4.5). The body and the sidecar
    are two writes, so a crash between them can leave the title stale; the next
    sync corrects it.
    """
    resolved = _resolve_doc_id(workspace, doc_id)
    loaded = workspace.index.documents[resolved]
    body_path, sidecar_path = _managed_document_files(workspace, loaded)
    if not body_path.is_file():
        raise OperationRefused(
            Finding(
                code="E-BODY-MISSING",
                severity="E",
                subject=resolved,
                message="the body file is missing; nothing was written",
            )
        )
    current_text = read_body(body_path)
    current_hash = body_hash(current_text)
    if current_hash != base_hash:
        raise OperationRefused(
            Finding(
                code="E-BODY-STALE",
                severity="E",
                subject=resolved,
                message=(
                    f"body changed since it was read (base {base_hash!r}, "
                    f"current {current_hash!r}); reload and retry"
                ),
                fix=f"gregraph edit {resolved}",
            )
        )
    # Line endings only (spec §5.2). Whitespace and blank lines are not normalised.
    lf_text = text.replace("\r\n", "\n").replace("\r", "\n")
    if strict:
        descriptor = _pinned_descriptor(workspace, loaded.model.template)
        check_required_sections(descriptor, lf_text, subject=resolved)
    # Read and validate the sidecar before anything is written, so a sidecar that
    # was removed or corrupted after the index was loaded fails the save with no
    # side effects (the read raises FileNotFoundError or ValidationError).
    document = read_sidecar(sidecar_path, Document)
    title = extract_title(lf_text)
    title_changed = title is not None and document.title != title
    body_changed = lf_text != current_text
    if body_changed:
        write_body_atomic(body_path, lf_text)
    if title is not None and title_changed:
        document.title = title
        write_sidecar(sidecar_path, document)
    if body_changed or title_changed:
        workspace.reload()
    return BodyUpdateResult(
        id=resolved,
        body=loaded.body,
        body_hash=body_hash(lf_text),
        title=title,
        changed=body_changed or title_changed,
        findings=_body_findings(resolved, lf_text),
        md_path=loaded.body,
        json_path=loaded.sidecar,
        sections=_optional_template_sections(workspace, loaded.model.template),
        notices=tuple(notices),
    )


def supersede(
    workspace: Workspace,
    *,
    targets: Sequence[str],
    title: str | None = None,
    type: str | None = None,
    copy_body: bool | None = None,
    copy_links: bool = True,
    cr: str | None = None,
    sections: Sequence[tuple[str, str]] = (),
    body_text: str | None = None,
    strict: bool = False,
) -> SupersedeResult:
    """Create one document superseding ``targets`` (spec §7.6, §11.2 pattern 1).

    ``NEW supersedes OLD`` for every target (multiple targets = conflict
    compromise, §11.2). ``copy_body`` defaults on when every target pins
    exactly the new document's resolved template; the copied body is the first
    target's with the H1 replaced (§5.6). ``body_text`` (whole-body
    ``--body``, §3.4 rule 4) replaces the copied/rendered body with the
    tool-owned ``# <title>`` H1; ``sections`` assembles the body from
    per-section input over the copied/rendered base; ``strict`` requires every
    required section to be filled at write time (§3.4 rules 5–6).
    ``copy_links`` (default on) copies the targets' outbound edges except
    ``supersedes`` with their stored ``target_version`` values — each
    candidate runs the §13.3 checks and failing ones are skipped and listed
    (``skipped_links``), duplicates collapse. OLD's inbound edges are untouched
    and listed as stale (``stale_inbound``). ``cr`` records the origin (§9.5)
    via S13's :func:`record_introduction` and, when OLD is outside the CR's
    scope, only *suggests* the scope add — scope is part of what was decided
    (§7.6 step 7).
    """
    if not targets:
        raise ValueError("supersede needs at least one target")
    if sections and body_text is not None:
        raise ValueError("cannot combine --body and --section")
    old_ids: list[str] = []
    notices: list[str] = []
    for raw in targets:
        resolved = _resolve_doc_id(workspace, raw)
        if resolved in old_ids:
            notices.append(f"duplicate target {resolved} collapsed")
            continue
        old_ids.append(resolved)

    if type is not None:
        type_name = type
    else:
        first_type = workspace.index.documents[old_ids[0]].model.type
        type_set = {workspace.index.documents[old].model.type for old in old_ids}
        if len(type_set) > 1:
            notices.append(
                f"targets have different types ({', '.join(sorted(type_set))}); "
                f"using the type of {old_ids[0]}: {first_type}"
            )
        type_name = first_type
    spec = workspace.config.types.get(type_name)
    if spec is None:
        raise OperationRefused(
            Finding(
                code="E-TYPE-UNKNOWN",
                severity="E",
                subject=type_name,
                message=f"unknown document type {type_name!r}",
            )
        )
    picked = _pick_template(workspace, spec.template, version=None)
    generated = generate_id(_existing_ids(workspace), workspace.config.ids.prefix)
    created = _now()
    identity = workspace.git.identity()
    author = identity.name if identity is not None else ""
    final_title = (
        title
        if title is not None
        else workspace.index.documents[old_ids[0]].model.title
    )

    template_same = all(
        workspace.index.documents[old].model.template.name == picked.name
        and workspace.index.documents[old].model.template.version == picked.version
        for old in old_ids
    )
    do_copy_body = template_same if copy_body is None else copy_body
    abs_body, abs_sidecar = document_paths(workspace.root, spec.folder, generated.id)
    body_rel = abs_body.relative_to(workspace.root)
    sidecar_rel = abs_sidecar.relative_to(workspace.root)
    if do_copy_body:
        base_body = _replace_title(
            read_body(workspace.root / workspace.index.documents[old_ids[0]].body),
            final_title,
        )
    else:
        base_body = _render_body(
            picked,
            title=final_title,
            doc_id=generated.id,
            type_name=type_name,
            kind=spec.kind,
            created=created,
            author=author,
        )
    body_notices: list[str] = []
    if body_text is not None:
        final_body, body_notices = prepare_whole_body(body_text, title=final_title)
        if strict:
            check_required_sections(picked.descriptor, final_body)
    elif sections:
        resolved_sections = resolve_section_inputs(picked.descriptor, sections)
        final_body = assemble_sections(
            picked.descriptor,
            title=final_title,
            content=resolved_sections,
            base_body=base_body,
            preserve_existing=do_copy_body,
        )
        check_required_sections(
            picked.descriptor,
            final_body,
            provided_headings=None if do_copy_body else set(resolved_sections),
            require_provided=not do_copy_body,
        )
    else:
        final_body = base_body
        if strict:
            check_required_sections(picked.descriptor, final_body)
    if do_copy_body and body_text is None:
        for ref in find_asset_refs(final_body, doc_path=body_rel, doc_id=generated.id):
            if ref.foreign and ref.owner.lower() == old_ids[0].lower():
                notices.append(
                    f"copied body references assets/{ref.owner}/; copy those files "
                    f"into assets/{generated.id}/ (assets are single-owner, §5.7)"
                )
                break

    node = Node(id=generated.id, kind=spec.kind, title=final_title, deprecated=False)
    graph = _extended_graph(workspace, node, ())
    written: list[Link] = []
    copied: list[Link] = []
    skipped: list[Finding] = []
    for old in old_ids:
        entry = Link(
            type="supersedes",
            target=old,
            target_version=_effective_version(workspace, old),
        )
        check = graph.check_link(generated.id, "supersedes", old)
        _raise_if_refused(check)
        graph, _ = graph.with_link(generated.id, "supersedes", old)
        written.append(entry)
    if copy_links:
        seen: set[tuple[str, str]] = {("supersedes", old) for old in old_ids}
        for old in old_ids:
            for link_entry in workspace.index.documents[old].model.links:
                if link_entry.type == "supersedes":
                    continue
                key = (link_entry.type, link_entry.target)
                if key in seen:
                    notices.append(
                        f"duplicate link {link_entry.type} → "
                        f"{link_entry.target} collapsed"
                    )
                    continue
                seen.add(key)
                check = graph.check_link(
                    generated.id, link_entry.type, link_entry.target
                )
                if check.refusal is not None:
                    skipped.append(check.refusal)
                    continue
                graph, _ = graph.with_link(
                    generated.id, link_entry.type, link_entry.target
                )
                entry = Link(
                    type=link_entry.type,
                    target=link_entry.target,
                    target_version=link_entry.target_version,
                )
                written.append(entry)
                copied.append(entry)

    cr_id: str | None = None
    if cr is not None:
        _check_cr_enabled(workspace, cr)
        cr_id = _resolve_cr_id(workspace, cr)
        scoped = {entry.id for entry in workspace.index.changes[cr_id].model.scope}
        for old in old_ids:
            if old not in scoped:
                notices.append(
                    f"{old} is not in the scope of {cr_id}; suggest: "
                    f"gregraph cr scope add {cr_id} {old} --intent supersede"
                )
        record_introduction(workspace, cr_id=cr_id, doc_id=generated.id)

    document = Document(
        schema=1,
        uuid=generated.uuid,
        id=generated.id,
        type=type_name,
        title=final_title,
        created=created,
        created_by=identity,
        template=TemplateRef(name=picked.name, version=picked.version),
        version=1,
        body_hash=body_hash(final_body),
        assets=_compute_assets(workspace, body_rel, final_body, generated.id),
        links=written,
        deprecated=None,
        tags=[],
        extra={},
        origin_cr=cr_id,
    )
    write_body(abs_body, final_body)
    write_sidecar(abs_sidecar, document)
    workspace.reload()
    stale = tuple(item for old in old_ids for item in _stale_inbound(workspace, old))
    new_result = CreateResult(
        id=generated.id,
        uuid=generated.uuid,
        body=body_rel,
        sidecar=sidecar_rel,
        type=type_name,
        template=document.template,
        links=tuple(written),
        kind=spec.kind,
        version=document.version,
        body_hash=document.body_hash,
        sections=tuple(picked.descriptor.sections),
        body_text=final_body,
        sidecar_document=document,
    )
    return SupersedeResult(
        id=generated.id,
        uuid=generated.uuid,
        body=body_rel,
        sidecar=sidecar_rel,
        type=type_name,
        template=document.template,
        supersedes=tuple(old_ids),
        copied_links=tuple(copied),
        new=new_result,
        skipped_links=tuple(skipped),
        stale_inbound=stale,
        findings=_identity_findings(workspace, generated.id),
        notices=tuple([*notices, *body_notices]),
    )


def deprecate(
    workspace: Workspace,
    *,
    doc_id: str,
    reason: str,
) -> DeprecateResult:
    """Mark a document deprecated (spec §13.15, §11.2 pattern 2).

    Inbound links become stale and are listed (the reviewer decides whether to
    re-point or remove them). Deprecating an already-deprecated document is a
    no-op notice.
    """
    doc_id = _resolve_doc_id(workspace, doc_id)
    document = _read_doc(workspace, doc_id)
    if document.deprecated is not None:
        return DeprecateResult(
            id=doc_id,
            changed=False,
            deprecated=document.deprecated,
            notices=(f"{doc_id} is already deprecated",),
        )
    marker = Deprecation(at=_now(), by=workspace.git.identity(), reason=reason)
    document.deprecated = marker
    _write_doc(workspace, doc_id, document)
    workspace.reload()
    return DeprecateResult(
        id=doc_id,
        changed=True,
        deprecated=marker,
        stale_inbound=_stale_inbound(workspace, doc_id),
    )


def undeprecate(workspace: Workspace, *, doc_id: str) -> DeprecateResult:
    """Clear a document's deprecation (spec §13.15). No-op notice when the
    document is not deprecated."""
    doc_id = _resolve_doc_id(workspace, doc_id)
    document = _read_doc(workspace, doc_id)
    if document.deprecated is None:
        return DeprecateResult(
            id=doc_id,
            changed=False,
            deprecated=None,
            notices=(f"{doc_id} is not deprecated",),
        )
    document.deprecated = None
    _write_doc(workspace, doc_id, document)
    workspace.reload()
    return DeprecateResult(id=doc_id, changed=True, deprecated=None)


# --------------------------------------------------------------------------
# stubs — owned by later subtasks (partition by function name)
# --------------------------------------------------------------------------


# --- S17: init, list, show, edit (spec §13.1, §13.10–13.11, §13.23) --------

_GITIGNORE_ENTRY: Final = ".gregraph/cache/"

_INIT_README: Final = """\
# Requirements repository

This directory is a GREGraph requirements repository (layout: spec §3).

## Layout

- `documents/` — requirements, designs, tests, and more (one folder per
  type; placement is organisational only)
- `changes/` — change requests (CRs) that record intent, decisions, and scope
- `glossary/` — knowledge-base terms with aliases
- `assets/` — attachments, one folder per owning document
- `.gregraph/` — `config.toml`, shared templates, and the rebuildable cache

Every document is a Markdown body plus a JSON sidecar (`<ID>.md` and
`<ID>.json`). Edit the Markdown; the tool maintains the sidecar.

## Commands

- `gregraph new <type> --title "…"` — create a document
- `gregraph list` / `gregraph show <ID>` — browse the repository
- `gregraph validate` — run every check
- `gregraph --help` — the full command set
"""


@dataclass(frozen=True, slots=True)
class InitResult:
    """Result of :func:`init_repository` (spec §13.1). Paths are repo-relative."""

    root: Path
    created: tuple[Path, ...]
    templates: tuple[str, ...]
    git_initialised: bool
    hooks_installed: bool
    agents_files: tuple[Path, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ListRow:
    """One ``list`` row (spec §13.10): sidecar fields plus derived fields."""

    id: str
    type: str
    kind: str
    status: str
    version: int
    title: str
    created: dt.datetime
    tags: tuple[str, ...]
    document: Document
    body: str | None = None


@dataclass(frozen=True, slots=True)
class ListResult:
    """Result of :func:`list_documents` (spec §13.10)."""

    rows: tuple[ListRow, ...]
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LinkView:
    """One edge with its freshness (spec §7.4) for ``show`` (spec §13.11).

    ``effective`` is the target's effective version, or ``None`` when the
    target does not exist (``state`` is then ``missing``).
    """

    source: str
    type: str
    target: str
    target_version: int
    effective: int | None
    state: str


@dataclass(frozen=True, slots=True)
class ShowResult:
    """Result of :func:`show_document` (spec §13.11).

    ``change_request`` is set when the ID refers to a CR (``show`` then
    delegates to ``cr show``, spec §13.11) and the document fields are empty.
    ``downstream`` holds ``(id, depth)`` over directed edges at unlimited
    depth (the CLI applies ``--depth``); ``upstream`` is the one-level
    hierarchical view as ``(link type, target)`` pairs.
    """

    id: str
    document: Document | None = None
    status: str | None = None
    kind: str | None = None
    outbound: tuple[LinkView, ...] = ()
    inbound: tuple[LinkView, ...] = ()
    upstream: tuple[tuple[str, str], ...] = ()
    downstream: tuple[tuple[str, int], ...] = ()
    body_text: str | None = None
    template_description: str | None = None
    template_deprecated: bool | None = None
    change_request: changes.CrShowResult | None = None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EditResult:
    """Result of :func:`edit_document` (spec §13.23)."""

    id: str
    body: Path
    editor: str


def _link_freshness(workspace: Workspace) -> versioning.FreshnessTable:
    """Freshness of every stored link (spec §7.4) over the document index."""
    graph = workspace.graph
    index = workspace.index
    stale_targets: dict[str, bool] = {}
    unbumped_targets: dict[str, bool] = {}
    links: list[tuple[str, Link, Document | None]] = []
    for source, loaded in index.documents.items():
        for link in loaded.model.links:
            target_loaded = index.documents.get(link.target)
            if target_loaded is None:
                links.append((source, link, None))
                continue
            if link.target not in stale_targets:
                stale_targets[link.target] = (
                    target_loaded.model.deprecated is not None
                    or graph.is_superseded(link.target)
                )
                unbumped_targets[link.target] = _has_unbumped_modifications(
                    workspace, target_loaded.model, target_loaded.body
                )
            links.append((source, link, target_loaded.model))
    return versioning.freshness_table(
        links,
        deprecated_or_superseded=stale_targets,
        unbumped=unbumped_targets,
        in_grace={
            doc_id: True
            for doc_id, loaded in index.documents.items()
            if _item_in_grace(workspace, loaded.model, loaded.body)
        },
    )


def _init_template_names(config: Config) -> set[str]:
    """Template names the default configuration needs (``--templates minimal``)."""
    names = {spec.template for spec in config.types.values()}
    names.add(config.cr.template)
    names.add("term")
    return names


def _git_run(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env={**os.environ, "LC_ALL": "C"},
        capture_output=True,
        timeout=30,
        check=False,
    )


def _body_text_or_none(root: Path, body_rel: Path) -> str | None:
    """Body text of a managed document, or ``None`` when unreadable (§6.3)."""
    try:
        return read_body(root / body_rel)
    except OSError:
        return None


def init_repository(
    path: Path,
    *,
    prefix: str = "RE",
    baseline_branch: str = "main",
    templates: str = "all",
    no_git: bool = False,
) -> InitResult:
    """§13.1 ``init``: create the repository layout (spec §3).

    Writes ``.gregraph/config.toml`` with the default types and the given ID
    prefix and baseline branch, copies the built-in templates (§5.5) into
    ``.gregraph/templates/<name>/v<N>/`` (``--templates all`` = every
    built-in; ``minimal`` = those the default configuration references), the
    ``.gitignore`` cache entry and a human ``README.md``. Runs ``git init``
    and installs the pre-commit hook (§12.3) unless ``--no-git``. Refuses
    when ``.gregraph/`` exists (``E-INIT-EXISTS``).
    """
    root = path.resolve()
    marker = root / ".gregraph"
    if marker.exists():
        raise OperationRefused(
            Finding(
                code="E-INIT-EXISTS",
                severity="E",
                subject=Path(".gregraph"),
                message=f"{root} already contains a gregraph repository",
                fix="gregraph status",
            )
        )
    if not is_valid_prefix(prefix):
        raise ValueError(f"invalid ID prefix {prefix!r}: expected [A-Z][A-Z0-9]{{0,7}}")
    if templates not in ("all", "minimal"):
        raise ValueError(f"invalid template selection {templates!r}: use all|minimal")
    config = Config(
        ids=IdsSection(prefix=prefix),
        git=GitSection(baseline_branch=baseline_branch),
    )

    created: list[Path] = []
    notices: list[str] = []
    for directory in (
        marker,
        root / DOCUMENTS_DIR,
        root / CHANGES_DIR,
        root / GLOSSARY_DIR,
        root / ASSETS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    wanted = (
        sorted(_builtin_names())
        if templates == "all"
        else sorted(_init_template_names(config))
    )
    copied: list[str] = []
    for name in wanted:
        source = _builtin_template(name)
        if source is None:
            continue
        target_root = templates_dir(root) / name
        for entry in sorted(source.iterdir(), key=lambda item: item.name):
            number = _version_dir_number(entry.name)
            if number is None or not entry.is_dir():
                continue
            files = [
                (child.name, child.read_bytes())
                for child in entry.iterdir()
                if child.is_file()
            ]
            _write_version_dir(target_root / f"v{number}", number, files)
        copied.append(name)

    write_config(config_path(root), config)
    created.append(config_path(root).relative_to(root))

    gitignore = root / ".gitignore"
    cache_entry = _GITIGNORE_ENTRY.rstrip("/")
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE_ENTRY + "\n", encoding="utf-8")
        created.append(Path(".gitignore"))
    else:
        existing = gitignore.read_text(encoding="utf-8")
        if cache_entry not in (
            line.strip().rstrip("/") for line in existing.splitlines()
        ):
            if existing and not existing.endswith("\n"):
                existing += "\n"
            gitignore.write_text(existing + _GITIGNORE_ENTRY + "\n", encoding="utf-8")
            notices.append("appended .gregraph/cache/ to the existing .gitignore")

    readme = root / "README.md"
    if readme.exists():
        notices.append("README.md already present; left untouched")
    else:
        readme.write_text(_INIT_README, encoding="utf-8")
        created.append(Path("README.md"))

    git_initialised = False
    hooks_installed = False
    if no_git:
        notices.append("git initialisation and hook installation skipped (--no-git)")
    elif shutil.which("git") is None:
        notices.append("git not found on PATH; skipping git init and hook installation")
    else:
        adapter = GitAdapter(root)
        owns_repo = adapter.is_repo() and adapter.root() == root
        if not owns_repo:
            started = _git_run(root, "init", "-b", baseline_branch)
            if started.returncode != 0:
                started = _git_run(root, "init")
                if started.returncode == 0:
                    notices.append(
                        f"git init -b {baseline_branch} failed; ran plain git init"
                    )
            git_initialised = started.returncode == 0
            if not git_initialised:
                notices.append("git init failed; continuing without a repository")
        if git_initialised or (
            GitAdapter(root).is_repo() and GitAdapter(root).root() == root
        ):
            hooks.install(root)
            hooks_installed = True
        else:
            notices.append("not a git repository; pre-commit hook not installed")

    # Agent scaffolding (AGENT_READINESS §7.1, AGENT-031): AGENTS.md with the
    # managed block and the wholly owned SKILL.md — written on every init.
    agents.refresh(root)
    return InitResult(
        root=root,
        created=tuple(created),
        templates=tuple(copied),
        git_initialised=git_initialised,
        hooks_installed=hooks_installed,
        agents_files=agents.AGENTS_FILES,
        notices=tuple(notices),
    )


def list_documents(
    workspace: Workspace,
    *,
    type_names: Sequence[str] = (),
    kinds: Sequence[str] = (),
    statuses: Sequence[str] = (),
    tags: Sequence[str] = (),
    roots: bool = False,
    orphans: bool = False,
    outdated: bool = False,
    stale: bool = False,
    deprecated_templates: bool = False,
    sort: str = "id",
    include_body: bool = False,
) -> ListResult:
    """§13.10 ``list``: filtered tabular document listing.

    Repeated filter flags are alternatives within their category (OR);
    categories combine with AND. ``--roots``/``--orphans`` are the §6.3
    queries; ``--outdated``/``--stale`` select documents with at least one
    outbound link that validate would report as ``W-LINK-OUTDATED``/
    ``W-LINK-STALE`` (spec §7.4, §14); ``--deprecated-templates`` selects
    documents pinned to a deprecated template version (spec §5.5).
    ``include_body`` (``list --body``, AGENT_READINESS §6.3) fills each row's
    ``body`` with the full Markdown text (AGENT-030).
    """
    report = compute_status(workspace)
    graph = workspace.graph
    freshness = _link_freshness(workspace)
    outdated_ids = {
        entry.source
        for entry in freshness.entries
        if entry.state == "outdated"
        and not entry.link_target_version > entry.target_version
    }
    stale_ids = {
        entry.source
        for entry in freshness.entries
        if entry.state == "stale" and entry.type != "supersedes"
    }
    deprecated_pins = {
        (name, loaded.version)
        for name, versions in load_template_dir(templates_dir(workspace.root)).items()
        for loaded in versions
        if loaded.descriptor.deprecated
    }
    root_set = set(graph.roots())
    orphan_set = set(graph.orphans())

    rows: list[ListRow] = []
    for doc_id in sorted(workspace.index.documents):
        loaded = workspace.index.documents[doc_id]
        document = loaded.model
        spec = workspace.config.types.get(document.type)
        kind = spec.kind if spec is not None else ""
        item = report.documents.get(doc_id)
        status_value = item.status if item is not None else "unknown"
        if type_names and document.type not in type_names:
            continue
        if kinds and kind not in kinds:
            continue
        if statuses and status_value not in statuses:
            continue
        if tags and not set(tags) & set(document.tags):
            continue
        if roots and doc_id not in root_set:
            continue
        if orphans and doc_id not in orphan_set:
            continue
        if outdated and doc_id not in outdated_ids:
            continue
        if stale and doc_id not in stale_ids:
            continue
        if (
            deprecated_templates
            and (
                document.template.name,
                document.template.version,
            )
            not in deprecated_pins
        ):
            continue
        rows.append(
            ListRow(
                id=doc_id,
                type=document.type,
                kind=kind,
                status=status_value,
                version=document.version,
                title=document.title,
                created=document.created,
                tags=tuple(document.tags),
                document=document,
                body=(
                    _body_text_or_none(workspace.root, loaded.body)
                    if include_body
                    else None
                ),
            )
        )

    def sort_key(row: ListRow) -> tuple[object, ...]:
        if sort == "title":
            return (row.title, row.id)
        if sort == "created":
            return (row.created, row.id)
        if sort == "version":
            return (row.version, row.id)
        return (row.id,)

    if sort not in ("id", "title", "created", "version"):
        raise ValueError(f"invalid sort key {sort!r}: use id|title|created|version")
    rows.sort(key=sort_key)
    return ListResult(rows=tuple(rows))


def show_document(
    workspace: Workspace, doc_id: str, *, body: bool = False
) -> ShowResult:
    """§13.11 ``show``: one document in full.

    Sidecar fields, derived status (spec §8), outbound and inbound edges with
    freshness (spec §7.4), one level upstream over hierarchical edges,
    unlimited-depth downstream over directed edges, assets and template info;
    ``body`` includes the Markdown text. When ``doc_id`` refers to a change
    request, delegates to ``cr show`` (spec §13.11) via ``change_request``.
    """
    cr_resolved = normalise_id(
        doc_id, workspace.config.ids.prefix, known=workspace.index.changes
    )
    if cr_resolved is not None:
        return ShowResult(
            id=cr_resolved,
            change_request=changes.show_change(workspace, cr_resolved),
        )
    resolved = _resolve_doc_id(workspace, doc_id)
    loaded = workspace.index.documents[resolved]
    document = loaded.model
    spec = workspace.config.types.get(document.type)
    report = compute_status(workspace)
    item = report.documents.get(resolved)
    status_value = item.status if item is not None else "unknown"
    freshness = _link_freshness(workspace)
    by_key = {entry.key: entry for entry in freshness.entries}

    outbound: list[LinkView] = []
    for link in document.links:
        entry = by_key.get((resolved, link.type, link.target))
        if entry is None:
            outbound.append(
                LinkView(
                    source=resolved,
                    type=link.type,
                    target=link.target,
                    target_version=link.target_version,
                    effective=None,
                    state="missing",
                )
            )
        else:
            outbound.append(
                LinkView(
                    source=entry.source,
                    type=entry.type,
                    target=entry.target,
                    target_version=entry.link_target_version,
                    effective=entry.effective,
                    state=entry.state,
                )
            )
    inbound = tuple(
        LinkView(
            source=entry.source,
            type=entry.type,
            target=entry.target,
            target_version=entry.link_target_version,
            effective=entry.effective,
            state=entry.state,
        )
        for entry in sorted(freshness.entries, key=lambda item: item.key)
        if entry.target == resolved and entry.source != resolved
    )
    graph = workspace.graph
    upstream = tuple(
        sorted(
            (link.type, link.target)
            for link in document.links
            if link.type in EDGE_RULES
            and EDGE_RULES[link.type].hierarchical
            and link.target in graph.nodes
        )
    )
    downstream = tuple(
        sorted(graph.downstream(resolved).items(), key=lambda item: (item[1], item[0]))
    )

    template_description: str | None = None
    template_deprecated: bool | None = None
    for candidate in load_template_dir(templates_dir(workspace.root)).get(
        document.template.name, ()
    ):
        if candidate.version == document.template.version:
            template_description = candidate.descriptor.description
            template_deprecated = candidate.descriptor.deprecated

    return ShowResult(
        id=resolved,
        document=document,
        status=status_value,
        kind=spec.kind if spec is not None else None,
        outbound=tuple(outbound),
        inbound=inbound,
        upstream=upstream,
        downstream=downstream,
        body_text=read_body(workspace.root / loaded.body) if body else None,
        template_description=template_description,
        template_deprecated=template_deprecated,
    )


def edit_document(workspace: Workspace, doc_id: str) -> EditResult:
    """§13.23 ``edit``: open the Markdown body in ``$VISUAL``/``$EDITOR``.

    Unknown IDs are refused ``E-ID-UNKNOWN``; a missing or failing editor is
    an environment error (``OSError``, CLI exit code 3). Convenience only.
    """
    resolved = _resolve_doc_id(workspace, doc_id)
    body_rel = workspace.index.documents[resolved].body
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise OSError("no $VISUAL or $EDITOR configured; cannot edit")
    command = shlex.split(editor)
    if not command:
        raise OSError("$VISUAL/$EDITOR is empty; cannot edit")
    completed = subprocess.run(
        [*command, str(workspace.root / body_rel)],
        cwd=workspace.root,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError(f"editor {editor!r} exited with status {completed.returncode}")
    return EditResult(id=resolved, body=body_rel, editor=editor)


# --- S18: sync, check, validate, status, graph (spec §13.7–13.9, 13.12–13.13)


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Result of :func:`sync` (spec §13.7, §7.5).

    ``mode`` is the reconcile mode used (``bump`` in degraded mode or with
    ``--bump``; ``report`` otherwise). ``changed`` lists every item whose
    effective content (§7.3 body and asset hashes; CR ``scope_hash``, §9.2)
    differs from the stored hashes — equal to ``bumped`` in bump mode, the
    ``--bump`` candidates otherwise. ``normalised``/``rewritten`` are the
    repository-relative bodies and sidecars the run wrote.
    """

    mode: Literal["bump", "report"]
    bumped: tuple[str, ...] = ()
    initialised: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    normalised: tuple[Path, ...] = ()
    rewritten: tuple[Path, ...] = ()
    newly_outdated: tuple[versioning.Freshness, ...] = ()
    previously_outdated: tuple[versioning.Freshness, ...] = ()
    stale: tuple[versioning.Freshness, ...] = ()
    pending: tuple[versioning.Freshness, ...] = ()
    findings: tuple[Finding, ...] = ()
    agents_files_changed: tuple[Path, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Result of :func:`check` (spec §13.8): the hook simulation (§7.5).

    ``blocked`` is the exit-code-1 condition of the hook policy (§7.5: any
    validation error, or newly outdated links when
    ``versioning.on_outdated_links = "block"``; also §11.1 open conflicts under
    ``graph.open_conflicts = "block"`` on the baseline branch, and §9.3
    ``W-CR-MODIFIED-AFTER-DECISION`` under ``versioning.on_cr_modified =
    "block"``). ``would_bump`` are the in-scope items whose content change
    would bump on the next commit; ``newly_outdated`` are the links that commit
    would newly outdate (not outdated before it — D2 refinement 2).
    """

    blocked: bool
    would_bump: tuple[str, ...] = ()
    initialised: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    newly_outdated: tuple[versioning.Freshness, ...] = ()
    previously_outdated: tuple[versioning.Freshness, ...] = ()
    stale: tuple[versioning.Freshness, ...] = ()
    pending: tuple[versioning.Freshness, ...] = ()
    refresh_commands: tuple[str, ...] = ()
    block_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidateResult:
    """Result of :func:`validate` (spec §13.9).

    ``findings`` is the display report (``--only-errors`` keeps errors only);
    ``failed`` is the exit decision over the *full* report — any error, or with
    ``strict`` any warning (§13.9).
    """

    findings: tuple[Finding, ...]
    failed: bool
    errors: int
    warnings: int


@dataclass(frozen=True, slots=True)
class DeprecatedTemplateUse:
    """One document pinned to a deprecated template version (spec §13.12)."""

    id: str
    template: str
    version: int


@dataclass(frozen=True, slots=True)
class StatusResult:
    """Result of :func:`status` (spec §13.12): one field per report section.

    ``outdated``/``stale``/``pending`` are the §7.4 link buckets (supersession
    edges excluded from ``stale`` as in validation); ``cr_counts`` counts
    change requests by *effective* status (§9.3); ``wip`` carries the header
    counts of §8. ``pending_initial_version`` (AGENT_READINESS §3.3) lists the
    uncommitted, modified ``v1`` documents that have inbound links — the
    *pending initial version* note; no new status is invented for them.
    """

    wip: WipState
    document_counts: dict[str, int]
    cr_counts: dict[str, int]
    outdated: tuple[versioning.Freshness, ...] = ()
    stale: tuple[versioning.Freshness, ...] = ()
    pending: tuple[versioning.Freshness, ...] = ()
    open_conflicts: tuple[tuple[str, str], ...] = ()
    deprecated_templates: tuple[DeprecatedTemplateUse, ...] = ()
    cr_pending: tuple[str, ...] = ()
    cr_drift: tuple[str, ...] = ()
    pending_initial_version: tuple[str, ...] = ()
    hook_installed: bool = False
    hook_up_to_date: bool = False
    degraded: bool = False
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportGraphResult:
    """Result of :func:`export_graph` (spec §13.13, §15).

    ``diagram`` is the complete fenced `` ```mermaid `` block; ``findings``
    carries the §15 size warning.
    """

    diagram: str
    findings: tuple[Finding, ...] = ()


_ItemModel = Document | ChangeRequest | Term


@dataclass(frozen=True, slots=True)
class _ReconcileItem:
    """One managed entity (document, change request or term) with its body."""

    key: str
    model: _ItemModel
    body_rel: Path
    sidecar_rel: Path
    text: str


def _scan_items(workspace: Workspace) -> tuple[_ReconcileItem, ...]:
    """Every managed entity with a readable body (spec §7.5 scope).

    Documents, change requests and glossary terms (the hook scope of §7.5
    covers ``documents/``, ``changes/`` and ``glossary/``). A missing body is
    left to validation (``E-BODY-MISSING``) and never reconciled.
    """
    items: list[_ReconcileItem] = []
    sources: list[tuple[str, Path, Path, _ItemModel]] = []
    for key, doc_loaded in workspace.index.documents.items():
        sources.append((key, doc_loaded.body, doc_loaded.sidecar, doc_loaded.model))
    for key, cr_loaded in workspace.index.changes.items():
        sources.append((key, cr_loaded.body, cr_loaded.sidecar, cr_loaded.model))
    for key, term_loaded in workspace.index.terms.items():
        sources.append((key, term_loaded.body, term_loaded.sidecar, term_loaded.model))
    for key, body_rel, sidecar_rel, model in sources:
        try:
            text = read_body(workspace.root / body_rel)
        except OSError:
            continue
        items.append(
            _ReconcileItem(
                key=key,
                model=model,
                body_rel=body_rel,
                sidecar_rel=sidecar_rel,
                text=text,
            )
        )
    return tuple(items)


def _item_change(
    workspace: Workspace, item: _ReconcileItem
) -> tuple[bool, str, list[AssetRef] | None, str | None]:
    """Whether effective content changed, plus the fresh hashes (§7.3, §9.2).

    Documents: ``body_hash`` and the sorted ``(path, hash)`` asset list
    (paths relative to ``assets/<ID>/``, raw-byte hashes — §7.3); change
    requests: body hash and ``scope_hash``; terms: body hash.
    """
    body = normalise_body(item.text)
    model = item.model
    if isinstance(model, Document):
        new_hash = body_hash(body)
        new_assets = _compute_assets(workspace, item.body_rel, body, item.key)
        stored = sorted((asset.path, asset.hash) for asset in model.assets)
        current = sorted((asset.path, asset.hash) for asset in new_assets)
        return (
            new_hash != model.body_hash or stored != current,
            new_hash,
            new_assets,
            None,
        )
    if isinstance(model, Term):
        new_hash = body_hash(body)
        return new_hash != model.body_hash, new_hash, None, None
    new_hash, new_scope = changes.content_hashes(model, body)
    changed = (new_hash, new_scope) != (model.body_hash, model.scope_hash)
    return changed, new_hash, None, new_scope


def _item_title_sync(item: _ReconcileItem) -> None:
    """Sync ``title`` from the H1 (spec §5.6, §7.5 step 1); terms have none."""
    model = item.model
    if isinstance(model, Term):
        return
    title = extract_title(normalise_body(item.text))
    if title is not None and model.title != title:
        model.title = title


def _item_bump(
    item: _ReconcileItem,
    new_hash: str,
    new_assets: list[AssetRef] | None,
    new_scope: str | None,
) -> None:
    """Record one content change: ``version += 1`` and store the hashes (§7.2)."""
    model = item.model
    model.version += 1
    model.body_hash = new_hash
    if isinstance(model, Document):
        model.assets = list(new_assets or ())
    elif not isinstance(model, Term):
        model.scope_hash = new_scope or model.scope_hash


def _item_populate_grace(
    item: _ReconcileItem,
    new_hash: str,
    new_assets: list[AssetRef] | None,
    new_scope: str | None,
) -> None:
    """Populate the initial version in place (spec §3.3 rule 1, AGENT-011).

    The recomputed ``body_hash`` (and ``assets``/``scope_hash``) are stored
    while ``version`` stays ``1`` — the first commit is the first real version.
    """
    model = item.model
    model.body_hash = new_hash
    if isinstance(model, Document):
        model.assets = list(new_assets or ())
    elif not isinstance(model, Term):
        model.scope_hash = new_scope or model.scope_hash


def _fresh_entry(
    link: Link,
    target: Document,
    source: str,
    *,
    state: Literal["fresh", "outdated", "stale", "pending-outdated"],
    newly: bool,
    effective: int,
) -> versioning.Freshness:
    return versioning.Freshness(
        source=source,
        type=link.type,
        target=link.target,
        link_target_version=link.target_version,
        target_version=target.version,
        effective=effective,
        state=state,
        newly=newly,
    )


def _freshness_report(
    workspace: Workspace,
    *,
    bumped_ids: Set[str],
    unbumped_ids: Set[str],
) -> tuple[
    list[versioning.Freshness],
    list[versioning.Freshness],
    list[versioning.Freshness],
    list[versioning.Freshness],
]:
    """§7.5 step 5 buckets: newly outdated, previously outdated, stale, pending.

    ``bumped_ids`` are the targets whose version this run increments (for
    :func:`check`, the would-be bumped set); ``unbumped_ids`` are targets with
    content changes that stay unbumped. "Newly outdated" are the links that
    end up outdated and were not outdated before the run (D2 refinement 2) —
    the blocking set of ``hook_pre_commit``. Stale targets (deprecated or
    superseded) bucket separately and never block; ``supersedes`` edges are
    exempt from ``stale`` as in validation (§7.6).
    """
    graph = workspace.graph
    index = workspace.index
    newly: list[versioning.Freshness] = []
    previously: list[versioning.Freshness] = []
    stale: list[versioning.Freshness] = []
    pending: list[versioning.Freshness] = []
    for source in sorted(index.documents):
        for link in index.documents[source].model.links:
            target_loaded = index.documents.get(link.target)
            if target_loaded is None:
                continue
            target = target_loaded.model
            if target.deprecated is not None or graph.is_superseded(link.target):
                if link.type != "supersedes":
                    stale.append(
                        _fresh_entry(
                            link,
                            target,
                            source,
                            state="stale",
                            newly=False,
                            effective=target.version,
                        )
                    )
                continue
            before = link.target_version < target.version
            after_version = target.version + (1 if link.target in bumped_ids else 0)
            effective = target.version + (1 if link.target in unbumped_ids else 0)
            after = link.target_version < after_version
            if before:
                previously.append(
                    _fresh_entry(
                        link,
                        target,
                        source,
                        state="outdated",
                        newly=False,
                        effective=effective,
                    )
                )
            elif after:
                newly.append(
                    _fresh_entry(
                        link,
                        target,
                        source,
                        state="outdated",
                        newly=True,
                        effective=after_version,
                    )
                )
            elif link.target in unbumped_ids and link.target_version in (
                target.version,
                effective,
            ):
                pending.append(
                    _fresh_entry(
                        link,
                        target,
                        source,
                        state="pending-outdated",
                        newly=False,
                        effective=effective,
                    )
                )
    return newly, previously, stale, pending


def _working_tree_scope(workspace: Workspace) -> set[str]:
    """Keys with working-tree changes: staged, unstaged or untracked (§13.8).

    Degraded mode has no change list — the whole tree is in scope (change
    detection itself is hash-based either way, §7.1 refinement 1).
    """
    git = workspace.git
    keys = (
        set(workspace.index.documents)
        | set(workspace.index.changes)
        | set(workspace.index.terms)
    )
    if not git.is_repo():
        return keys
    paths = set(git.changed_paths()) | set(git.untracked_paths())
    assets_top = ASSETS_DIR.as_posix()
    scope: set[str] = set()
    for key, doc_loaded in workspace.index.documents.items():
        if doc_loaded.body in paths or doc_loaded.sidecar in paths:
            scope.add(key)
            continue
        for path in paths:
            if len(path.parts) >= 2 and path.parts[0] == assets_top:
                if path.parts[1] == key:
                    scope.add(key)
                    break
    for key, cr_loaded in workspace.index.changes.items():
        if cr_loaded.body in paths or cr_loaded.sidecar in paths:
            scope.add(key)
    for key, term_loaded in workspace.index.terms.items():
        if term_loaded.body in paths or term_loaded.sidecar in paths:
            scope.add(key)
    return scope


def _hook_decision(
    workspace: Workspace,
    findings: Sequence[Finding],
    newly: Sequence[versioning.Freshness],
) -> tuple[bool, tuple[str, ...]]:
    """The hook's abort conditions (spec §7.5, §9.3, §11.1)."""
    reasons: list[str] = []
    errors = [finding for finding in findings if finding.severity == "E"]
    if errors:
        reasons.append(f"{len(errors)} validation error(s)")
    if newly and workspace.config.versioning.on_outdated_links == "block":
        reasons.append(f"{len(newly)} link(s) newly outdated by this commit")
    git = workspace.git
    if (
        workspace.config.graph.open_conflicts == "block"
        and git.is_repo()
        and git.current_branch() == workspace.config.git.baseline_branch
        and any(finding.code == "W-CONFLICT-OPEN" for finding in findings)
    ):
        reasons.append("open conflicts on the baseline branch")
    if workspace.config.versioning.on_cr_modified == "block" and any(
        finding.code == "W-CR-MODIFIED-AFTER-DECISION" for finding in findings
    ):
        reasons.append("change request modified after its last decision")
    return bool(reasons), tuple(reasons)


def _rebuild_cache(workspace: Workspace) -> None:
    """Rebuild the §16.5 index cache (``files`` plus the seen maps)."""
    root = workspace.root
    files: dict[str, CacheFileEntry] = {}
    for entry in [*iter_documents(root), *iter_changes(root), *iter_terms(root)]:
        if not entry.body.is_file():
            continue
        key = entry.body.relative_to(root).as_posix()
        files[key] = stat_cache_entry(entry.body, body_hash(read_body(entry.body)))
    cache = refresh_cache(
        CacheIndex().model_copy(update={"files": files}),
        config=workspace.config,
        documents=(loaded.model for loaded in workspace.index.documents.values()),
        templates=load_template_dir(templates_dir(root)),
    )
    write_cache(root, cache)


def sync(workspace: Workspace, *, bump: bool = False) -> SyncResult:
    """§13.7 ``sync`` — reconcile all (§7.5); normalise; rebuild the cache.

    Versions bump only in degraded mode or with ``--bump`` (§7.5); report mode
    still normalises body line endings, rewrites sidecars whose serialisation
    (or H1-synced title, §5.6) differs from the canonical form, and rebuilds
    the §16.5 index cache. Documents, change requests and glossary terms are
    all reconciled (the §7.5 hook scope).

    Items in the initial-grace state (uncommitted ``v1``, §3.3) are
    *initialised* instead of bumped in bump mode: the recomputed hashes are
    stored in place and ``version`` stays ``1`` (AGENT-011). As its last step
    the run refreshes the agent files (``AGENTS.md`` and the skill, §7.3,
    AGENT-033); ``agents_files_changed`` lists the files it had to write.
    """
    root = workspace.root
    mode: Literal["bump", "report"] = (
        "bump" if bump or not workspace.git.is_repo() else "report"
    )
    items = _scan_items(workspace)
    deltas = {item.key: _item_change(workspace, item) for item in items}
    changed = tuple(item.key for item in items if deltas[item.key][0])
    grace_keys = {
        item.key
        for item in items
        if deltas[item.key][0] and _item_in_grace(workspace, item.model, item.body_rel)
    }
    if mode == "bump":
        initialised = tuple(key for key in changed if key in grace_keys)
        bumped = tuple(key for key in changed if key not in grace_keys)
    else:
        initialised = ()
        bumped = ()
    newly, previously, stale, pending = _freshness_report(
        workspace,
        bumped_ids=frozenset(bumped),
        unbumped_ids=(frozenset(changed) - frozenset(bumped)) - grace_keys,
    )
    for item in items:
        _item_title_sync(item)
        delta = deltas[item.key]
        if mode == "bump" and delta[0]:
            if item.key in grace_keys:
                _item_populate_grace(item, delta[1], delta[2], delta[3])
            else:
                _item_bump(item, delta[1], delta[2], delta[3])
    normalised: list[Path] = []
    rewritten: list[Path] = []
    for item in items:
        fixed = normalise_body(item.text)
        try:
            raw_body = (root / item.body_rel).read_bytes()
        except OSError:
            raw_body = b""
        if raw_body != fixed.encode("utf-8"):
            write_body(root / item.body_rel, fixed)
            normalised.append(item.body_rel)
        abs_sidecar = root / item.sidecar_rel
        try:
            disk = abs_sidecar.read_bytes()
        except OSError:
            disk = b""
        if disk != canonical_json_bytes(item.model):
            write_sidecar(abs_sidecar, item.model)
            rewritten.append(item.sidecar_rel)
    _rebuild_cache(workspace)
    agents_changed = agents.refresh(root)
    workspace.reload()
    findings = tuple(validate_workspace(workspace))
    return SyncResult(
        mode=mode,
        bumped=bumped,
        initialised=initialised,
        changed=changed,
        normalised=tuple(normalised),
        rewritten=tuple(rewritten),
        newly_outdated=tuple(newly),
        previously_outdated=tuple(previously),
        stale=tuple(stale),
        pending=tuple(pending),
        findings=findings,
        agents_files_changed=agents_changed,
    )


def check(workspace: Workspace) -> CheckResult:
    """§13.8 ``check`` — the hook simulation over all working-tree changes.

    Runs §7.5 in ``report`` mode over the documents/CRs/terms with staged,
    unstaged or untracked changes (never writes), computes the links the
    corresponding commit would newly outdate, and returns the hook's abort
    decision. Findings are ``validate_workspace`` unfiltered (§5.4, D-AGENT-7:
    validation itself reports ``W-LINK-PENDING`` instead of
    ``E-LINK-VERSION-AHEAD`` for links refreshed against an unbumped target,
    so no suppression is needed and the exit code still matches
    ``hook pre-commit``). Items in the initial-grace state (uncommitted
    ``v1``, §3.3) are reported under ``initialised`` instead of
    ``would_bump`` (AGENT-011) and are never pending-outdated targets
    (§3.3 rule 4).
    """
    items = _scan_items(workspace)
    deltas = {item.key: _item_change(workspace, item) for item in items}
    changed = {item.key for item in items if deltas[item.key][0]}
    grace_keys = {
        item.key
        for item in items
        if deltas[item.key][0] and _item_in_grace(workspace, item.model, item.body_rel)
    }
    in_scope = changed & _working_tree_scope(workspace)
    initialised = tuple(sorted(in_scope & grace_keys))
    would_bump = in_scope - grace_keys
    newly, previously, stale, pending = _freshness_report(
        workspace,
        bumped_ids=frozenset(would_bump),
        unbumped_ids=frozenset((changed - in_scope) - grace_keys),
    )
    findings = tuple(validate_workspace(workspace))
    blocked, reasons = _hook_decision(workspace, findings, newly)
    return CheckResult(
        blocked=blocked,
        would_bump=tuple(sorted(would_bump)),
        initialised=initialised,
        findings=findings,
        newly_outdated=tuple(newly),
        previously_outdated=tuple(previously),
        stale=tuple(stale),
        pending=tuple(pending),
        refresh_commands=tuple(
            f"gregraph link refresh {entry.source} {entry.type} {entry.target}"
            for entry in newly
        ),
        block_reasons=reasons,
    )


def validate(
    workspace: Workspace, *, strict: bool = False, only_errors: bool = False
) -> ValidateResult:
    """§13.9 ``validate`` — the full §14 report over the working tree.

    ``--strict`` promotes warnings to errors for the exit decision only;
    ``--only-errors`` filters the display report to errors.
    """
    findings = tuple(validate_workspace(workspace))
    errors = [finding for finding in findings if finding.severity == "E"]
    warnings = [finding for finding in findings if finding.severity == "W"]
    return ValidateResult(
        findings=tuple(errors) if only_errors else findings,
        failed=has_errors(findings, strict=strict),
        errors=len(errors),
        warnings=len(warnings),
    )


def status(workspace: Workspace) -> StatusResult:
    """§13.12 ``status`` — the WIP header data and every report section.

    Composes :func:`gregraph.core.status.compute_status` (the §8 model and WIP
    aggregate), the §7.4 link buckets, deprecated-template pins (§7.7), the
    change-request counts by effective status with pending decisions and drift
    (§9.3, §9.6) and the §12.3 hook state. Never refuses. Documents in the
    initial-grace state (§3.3) show as ``draft``/untracked as today and are
    additionally listed under the *pending initial version* note when they
    have unbumped modifications and at least one inbound link.
    """
    report = compute_status(workspace)
    counts: dict[str, int] = {}
    for item in report.documents.values():
        counts[item.status] = counts.get(item.status, 0) + 1
    items = _scan_items(workspace)
    changed = {item.key for item in items if _item_change(workspace, item)[0]}
    # §3.3 (AGENT_READINESS): grace items whose initial version is still
    # pending — uncommitted, modified v1 — and that other documents point at.
    pending_initial: list[str] = []
    for doc_id, doc_loaded in sorted(workspace.index.documents.items()):
        if not _item_in_grace(workspace, doc_loaded.model, doc_loaded.body):
            continue
        if not _has_unbumped_modifications(
            workspace, doc_loaded.model, doc_loaded.body
        ):
            continue
        if workspace.graph.inbound_edges(doc_id):
            pending_initial.append(doc_id)
    _newly, previously, stale, pending = _freshness_report(
        workspace,
        bumped_ids=frozenset(),
        unbumped_ids=frozenset(changed),
    )
    templates = load_template_dir(templates_dir(workspace.root))
    deprecated_templates: list[DeprecatedTemplateUse] = []
    for doc_id, doc_loaded in sorted(workspace.index.documents.items()):
        pinned = doc_loaded.model.template
        for candidate in templates.get(pinned.name, ()):
            if candidate.version == pinned.version and candidate.descriptor.deprecated:
                deprecated_templates.append(
                    DeprecatedTemplateUse(
                        id=doc_id, template=pinned.name, version=pinned.version
                    )
                )
    cr_counts: dict[str, int] = {}
    cr_pending: list[str] = []
    cr_drift: list[str] = []
    baseline = changes.BaselineView(workspace.git, workspace.config.git.baseline_branch)
    for cr_id, loaded in sorted(workspace.index.changes.items()):
        cr = loaded.model
        effective = changes.effective_status(baseline, cr)
        cr_counts[effective] = cr_counts.get(effective, 0) + 1
        if effective != cr.status:
            cr_pending.append(cr_id)
        if changes.drift_entries(baseline, cr):
            cr_drift.append(cr_id)
    hook_state = hooks_status(workspace)
    findings = sorted(
        (*report.findings, *workspace.index.findings),
        key=lambda finding: (finding.code, str(finding.subject)),
    )
    return StatusResult(
        wip=report.wip,
        document_counts=counts,
        cr_counts=cr_counts,
        outdated=tuple(previously),
        stale=tuple(stale),
        pending=tuple(pending),
        open_conflicts=report.open_conflicts,
        deprecated_templates=tuple(deprecated_templates),
        cr_pending=tuple(cr_pending),
        cr_drift=tuple(cr_drift),
        pending_initial_version=tuple(pending_initial),
        hook_installed=hook_state.installed,
        hook_up_to_date=hook_state.up_to_date,
        degraded=not workspace.git.is_repo(),
        findings=tuple(findings),
    )


def export_graph(
    workspace: Workspace,
    *,
    roots: Sequence[str] = (),
    depth: int | None = None,
    types: Sequence[str] = (),
    edges: Sequence[str] = (),
    include_superseded: bool = False,
    direction: str = "TD",
) -> ExportGraphResult:
    """§13.13 ``graph`` (CLI name) — the §15 Mermaid export of a scoped graph.

    ``roots``/``depth`` select the downstream subgraph first (§15: nodes that
    reach a root via directed edges); ``types`` then filters the scope by
    document type — the graph carries kinds, not type names, so the subset is
    built here (D-S16 (7)); explicit roots stay in the scope as anchors.
    ``edges`` overrides the default edge set (directed plus ``conflicts-with``).
    Unknown roots refuse ``E-ID-UNKNOWN``; unknown type/edge-type names and a
    negative depth are usage errors (``ValueError``).
    """
    if depth is not None and depth < 0:
        raise ValueError("depth must be zero or positive")
    if direction not in ("TD", "LR"):
        raise ValueError(f"direction must be 'TD' or 'LR', got {direction!r}")
    resolved_roots = tuple(_resolve_doc_id(workspace, raw) for raw in roots)
    wanted_types = frozenset(types)
    for name in wanted_types:
        if name not in workspace.config.types:
            raise ValueError(f"unknown document type: {name!r}")
    for name in edges:
        if name not in EDGE_RULES:
            raise ValueError(f"unknown edge type: {name!r}")
    graph = workspace.graph
    if resolved_roots:
        scope = set(resolved_roots)
        for root_id in resolved_roots:
            scope.update(graph.downstream(root_id, depth))
    else:
        scope = set(graph.nodes)
    if wanted_types:
        scope = {
            node_id
            for node_id in scope
            if node_id in workspace.index.documents
            and workspace.index.documents[node_id].model.type in wanted_types
        } | set(resolved_roots)
    keep = frozenset(scope)
    sub_graph = Graph(
        nodes=[graph.nodes[node_id] for node_id in sorted(keep)],
        edges=[
            edge for edge in graph.edges if edge.source in keep and edge.target in keep
        ],
    )
    export = export_mermaid(
        sub_graph,
        direction=cast("Literal['TD', 'LR']", direction),
        include_superseded=include_superseded,
        edge_types=(
            frozenset(cast("LinkType", name) for name in edges) if edges else None
        ),
    )
    return ExportGraphResult(diagram=export.diagram, findings=tuple(export.findings))


# --- S13: change requests (spec §9, §13.18) -------------------------------


def record_introduction(workspace: Workspace, *, cr_id: str, doc_id: str) -> Any:
    """Record that ``cr_id`` introduced ``doc_id`` (spec §9.5) — S13.

    Validates the CR (``E-CR-DISABLED``, ``E-CR-CLOSED``, unknown CR) and
    appends ``doc_id`` to its ``introduces`` list. The caller (``new``/
    ``supersede``) writes ``origin_cr`` on the new document's sidecar and calls
    this *before* any file is written, so a refusal leaves nothing behind.
    """
    return changes.record_origin(workspace, cr_id=cr_id, doc_id=doc_id)


def cr_new(
    workspace: Workspace,
    *,
    title: str | None = None,
    scope: Sequence[str] = (),
    external_ref: str | None = None,
    sections: Sequence[tuple[str, str]] = (),
    strict: bool = False,
) -> Any:
    """§13.18 ``cr new`` (§9.2, §9.4, §3.4) — implemented in S13."""
    return changes.new_change_request(
        workspace,
        title=title,
        scope_specs=scope,
        external_ref=external_ref,
        sections=sections,
        strict=strict,
    )


def cr_scope_add(
    workspace: Workspace, *, cr_id: str, target: str, intent: str = "modify"
) -> Any:
    """§13.18 ``cr scope add`` (§9.4) — implemented in S13."""
    return changes.scope_add(workspace, cr_id=cr_id, target=target, intent=intent)


def cr_scope_remove(workspace: Workspace, *, cr_id: str, target: str) -> Any:
    """§13.18 ``cr scope remove`` (§9.4) — implemented in S13."""
    return changes.scope_remove(workspace, cr_id=cr_id, target=target)


def cr_set(workspace: Workspace, *, cr_id: str, assignments: Sequence[str]) -> Any:
    """§13.18 ``cr set`` (status/branch/external_ref/tags/extra) — S13."""
    return changes.set_cr_fields(workspace, cr_id=cr_id, assignments=assignments)


def cr_reaffirm(workspace: Workspace, *, cr_id: str) -> Any:
    """§13.18 ``cr reaffirm`` (§9.3) — implemented in S13."""
    return changes.reaffirm_cr(workspace, cr_id=cr_id)


def cr_reanalyze(
    workspace: Workspace, *, cr_id: str, targets: Sequence[str] = ()
) -> Any:
    """§13.18 ``cr reanalyze`` (§9.4) — implemented in S13."""
    return changes.reanalyze(workspace, cr_id=cr_id, targets=targets)


def cr_list(
    workspace: Workspace,
    *,
    statuses: Sequence[str] = (),
    effective: bool = False,
    pending: bool = False,
    drift: bool = False,
) -> Any:
    """§13.18 ``cr list`` (proposed/effective/pending/drift filters) — S13."""
    return changes.list_changes(
        workspace,
        statuses=statuses,
        effective=effective,
        pending=pending,
        drift=drift,
    )


def cr_show(workspace: Workspace, cr_id: str) -> Any:
    """§13.18 ``cr show`` (§9.8 impact view) — implemented in S13."""
    return changes.show_change(workspace, cr_id)


# --- S14: glossary (spec §10, §13.20) ------------------------------------
#
# Glossary terms are first-class non-graph entities (§10.1): identified by
# slug (the filename stem), mentioned in prose by name. Result dataclasses and
# helpers live in this block so the S12/S13 sections stay untouched; the two
# validation codes (``E-TERM-SLUG``, ``E-TERM-ALIAS-CLASH``) are implemented in
# ``validation.check_terms`` (spec §10.2, §14). Usage matching is
# case-insensitive and word-boundary based over the term name and aliases,
# scanning document bodies only (spec §10.2 "documents whose bodies mention");
# rename lists those mentions and never rewrites prose (spec §10.2).

#: Refusal-only code for an unknown/ambiguous term slug — the §14 catalogue has
#: no row for it (mirrors S12's ``E-ID-UNKNOWN``, docs/backlog.md).
_TERM_UNKNOWN_CODE: Final = "E-TERM-UNKNOWN"


@dataclass(frozen=True, slots=True)
class TermInfo:
    """One glossary term: §10.2/appendix B.3 sidecar fields, paths and status."""

    slug: str
    term: str
    aliases: tuple[str, ...]
    created: dt.datetime
    created_by: Identity | None
    template: TemplateRef
    version: int
    body_hash: str
    deprecated: Deprecation | None
    body: Path
    sidecar: Path
    status: Status


@dataclass(frozen=True, slots=True)
class TermAddResult:
    """Result of :func:`term_add` (spec §13.20). Paths are repo-relative."""

    slug: str
    term: str
    aliases: tuple[str, ...]
    body: Path
    sidecar: Path
    template: TemplateRef
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()
    sections: tuple[TemplateSection, ...] = ()
    body_text: str = ""
    body_hash: str = ""


@dataclass(frozen=True, slots=True)
class TermListResult:
    """Result of :func:`term_list` (spec §13.20), sorted by slug."""

    terms: tuple[TermInfo, ...]


@dataclass(frozen=True, slots=True)
class TermMention:
    """One document body mentioning a term name or alias (spec §10.2)."""

    id: str
    path: Path
    matched: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TermUsageResult:
    """Result of :func:`term_usage` (spec §13.20, §10.2)."""

    slug: str
    term: str
    names: tuple[str, ...]
    mentions: tuple[TermMention, ...]


@dataclass(frozen=True, slots=True)
class TermRenameResult:
    """Result of :func:`term_rename` (spec §13.20, §10.2).

    ``mentions`` are the document bodies still containing the old name or one
    of its aliases — listed, never rewritten (prose is human-owned).
    """

    slug: str
    old_slug: str
    term: str
    old_term: str
    body: Path
    sidecar: Path
    mentions: tuple[TermMention, ...] = ()
    changed: bool = True
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TermDeprecateResult:
    """Result of :func:`term_deprecate` (spec §13.20)."""

    slug: str
    changed: bool
    deprecated: Deprecation | None
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


def derive_term_slug(name: str) -> str:
    """Derive the §10.2 slug: lowercase, non-alphanumerics → ``-``, collapsed, trimmed.

    The name is NFC-normalised first so composed characters slug identically
    on every platform (macOS stores NFD). Unicode alphanumerics are kept —
    §10.2 says "non-alphanumerics → -" without an ASCII restriction
    (docs/backlog.md).
    """
    text = unicodedata.normalize("NFC", name).lower()
    mapped = "".join(ch if ch.isalnum() else "-" for ch in text)
    return re.sub(r"-{2,}", "-", mapped).strip("-")


def _term_unknown(slug: str, message: str | None = None) -> OperationRefused:
    return OperationRefused(
        Finding(
            code=_TERM_UNKNOWN_CODE,
            severity="E",
            subject=slug,
            message=message or f"no glossary term with slug {slug!r}",
            fix="gregraph term list",
        )
    )


def _resolve_term_slug(workspace: Workspace, slug: str) -> str:
    """Canonical term slug for user input; refuses ``E-TERM-UNKNOWN``.

    Exact filename-stem match first, then case-insensitively (input tolerance
    in the spirit of §4.5's ID handling). Slugs are unique by stem (§10.2).
    """
    terms = workspace.index.terms
    if slug in terms:
        return slug
    matches = sorted(key for key in terms if key.casefold() == slug.casefold())
    if not matches:
        raise _term_unknown(slug)
    if len(matches) > 1:
        raise _term_unknown(slug, f"slug {slug!r} is ambiguous: {', '.join(matches)}")
    return matches[0]


def _clean_aliases(aliases: Sequence[str]) -> tuple[str, ...]:
    """Stripped aliases; blank ones raise ``ValueError`` (argument shape)."""
    cleaned: list[str] = []
    for raw in aliases:
        alias = raw.strip()
        if not alias:
            raise ValueError("aliases must not be blank")
        cleaned.append(alias)
    return tuple(cleaned)


def _word_pattern(name: str) -> re.Pattern[str]:
    """Word-boundary, case-insensitive pattern for one term name/alias.

    ``(?<!\\w)…(?!\\w)`` rather than ``\\b`` so names with non-word edges
    (e.g. "C++") still match at word boundaries (spec §10.2).
    """
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)


def _matched_names(text: str, names: Sequence[str]) -> tuple[str, ...]:
    """The names/aliases occurring in ``text`` (case-insensitive, word-boundary)."""
    hits = [name for name in names if name and _word_pattern(name).search(text)]
    return tuple(hits)


def _document_mentions(
    workspace: Workspace, names: Sequence[str]
) -> tuple[TermMention, ...]:
    """Documents whose bodies mention any of ``names`` (spec §10.2)."""
    mentions: list[TermMention] = []
    for doc_id in sorted(workspace.index.documents):
        loaded = workspace.index.documents[doc_id]
        try:
            text = read_body(workspace.root / loaded.body)
        except OSError:
            continue
        hits = _matched_names(text, names)
        if hits:
            mentions.append(TermMention(id=doc_id, path=loaded.body, matched=hits))
    return tuple(mentions)


def _clashes_with_alias(workspace: Workspace, text: str) -> str | None:
    """First existing alias ``text`` collides with (case-insensitive), else ``None``.

    Alias uniqueness spans every term (spec §10.2); the description names the
    owner for the refusal message.
    """
    for slug in sorted(workspace.index.terms):
        for alias in workspace.index.terms[slug].model.aliases:
            if alias and alias.casefold() == text.casefold():
                return f"alias {alias!r} of {slug}"
    return None


def _alias_conflicts(
    workspace: Workspace, name: str, aliases: Sequence[str]
) -> tuple[str, ...]:
    """Clash messages introduced by a new term's name/aliases (spec §10.2).

    Mirrors ``validation.check_terms``: an alias must not equal a term name
    (any term, including its own) or any other alias instance, and the name
    must not equal an existing alias — all case-insensitive.
    """
    messages: list[str] = []
    hit = _clashes_with_alias(workspace, name)
    if hit is not None:
        messages.append(f"term name {name!r} collides with {hit}")
    seen: dict[str, str] = {name.casefold(): f"the term name {name!r}"}
    for alias in aliases:
        key = alias.casefold()
        prior = seen.get(key)
        if prior is not None:
            messages.append(f"alias {alias!r} collides with {prior}")
        else:
            seen[key] = f"alias {alias!r}"
        for slug in sorted(workspace.index.terms):
            model = workspace.index.terms[slug].model
            if model.term and model.term.casefold() == key:
                messages.append(
                    f"alias {alias!r} collides with term name {model.term!r} of {slug}"
                )
            for other in model.aliases:
                if other and other.casefold() == key:
                    messages.append(
                        f"alias {alias!r} collides with alias {other!r} of {slug}"
                    )
    return tuple(messages)


def _term_info(workspace: Workspace, slug: str, report: StatusReport) -> TermInfo:
    loaded = workspace.index.terms[slug]
    model = loaded.model
    item = report.terms.get(slug)
    return TermInfo(
        slug=slug,
        term=model.term,
        aliases=tuple(model.aliases),
        created=model.created,
        created_by=model.created_by,
        template=model.template,
        version=model.version,
        body_hash=model.body_hash,
        deprecated=model.deprecated,
        body=loaded.body,
        sidecar=loaded.sidecar,
        status=item.status if item is not None else "unknown",
    )


def _move_file(source: Path, target: Path) -> None:
    """Move ``source`` to ``target``, tolerating case-only renames on any OS."""
    if source == target:
        return
    if source.name.casefold() == target.name.casefold():
        staging = source.with_name(source.name + ".gregraph-tmp")
        source.rename(staging)
        staging.rename(target)
        return
    source.rename(target)


def term_add(
    workspace: Workspace,
    *,
    term: str,
    aliases: Sequence[str] = (),
    sections: Sequence[tuple[str, str]] = (),
    strict: bool = False,
) -> TermAddResult:
    """§13.20 ``term add`` (§10.2, §3.4): create ``glossary/<slug>.md`` +
    ``<slug>.json``.

    The slug is derived from the name (:func:`derive_term_slug`); the body is
    the repository's ``term`` template with the name as title (pinned in the
    sidecar "for uniformity", §10.2). ``sections`` assembles the body from
    per-section input; ``strict`` requires every template-required section to
    be filled at write time (§3.4 rules 5–6). Refusals write nothing: slug
    collision (``E-TERM-SLUG``, the §10.2 slug-uniqueness rule), alias clashes
    (``E-TERM-ALIAS-CLASH``), missing template (``E-TEMPLATE-UNKNOWN``).
    Blank names/aliases raise ``ValueError`` (argument shape).
    """
    name = term.strip()
    if not name:
        raise ValueError("term name must not be blank")
    slug = derive_term_slug(name)
    if not slug:
        raise ValueError(f"term {term!r} derives an empty slug")
    cleaned = _clean_aliases(aliases)
    if any(key.casefold() == slug.casefold() for key in workspace.index.terms):
        raise OperationRefused(
            Finding(
                code="E-TERM-SLUG",
                severity="E",
                subject=slug,
                message=f"slug {slug!r} is already used by another glossary term",
                fix="gregraph term list",
            )
        )
    clashes = _alias_conflicts(workspace, name, cleaned)
    if clashes:
        raise OperationRefused(
            Finding(
                code="E-TERM-ALIAS-CLASH",
                severity="E",
                subject=slug,
                message="; ".join(clashes),
                fix="gregraph term list",
            )
        )
    picked = _pick_template(workspace, "term", version=None, allow_deprecated=True)
    created = _now()
    identity = workspace.git.identity()
    author = identity.name if identity is not None else ""
    rendered = render_template(
        picked, title=name, slug=slug, created=_stamp(created), author=author
    )
    if sections:
        resolved_sections = resolve_section_inputs(picked.descriptor, sections)
        rendered = assemble_sections(
            picked.descriptor,
            title=name,
            content=resolved_sections,
            base_body=rendered,
            preserve_existing=False,
        )
        check_required_sections(
            picked.descriptor,
            rendered,
            provided_headings=set(resolved_sections),
            require_provided=True,
        )
    elif strict:
        check_required_sections(picked.descriptor, rendered)
    abs_body, abs_sidecar = term_paths(workspace.root, slug)
    model = Term(
        schema=1,
        term=name,
        slug=slug,
        aliases=list(cleaned),
        created=created,
        created_by=identity,
        template=TemplateRef(name=picked.name, version=picked.version),
        version=1,
        body_hash=body_hash(rendered),
        deprecated=None,
    )
    write_body(abs_body, rendered)
    write_sidecar(abs_sidecar, model)
    workspace.reload()
    return TermAddResult(
        slug=slug,
        term=name,
        aliases=tuple(cleaned),
        body=abs_body.relative_to(workspace.root),
        sidecar=abs_sidecar.relative_to(workspace.root),
        template=model.template,
        findings=_identity_findings(workspace, slug),
        sections=tuple(picked.descriptor.sections),
        body_text=rendered,
        body_hash=model.body_hash,
    )


def term_list(workspace: Workspace) -> TermListResult:
    """§13.20 ``term list``: every glossary term, sorted by slug (spec §10.2)."""
    report = compute_status(workspace)
    return TermListResult(
        terms=tuple(
            _term_info(workspace, slug, report)
            for slug in sorted(workspace.index.terms)
        )
    )


def term_show(workspace: Workspace, slug: str) -> TermInfo:
    """§13.20 ``term show``: sidecar fields and derived status (spec §8, §10.2)."""
    resolved = _resolve_term_slug(workspace, slug)
    return _term_info(workspace, resolved, compute_status(workspace))


def term_usage(workspace: Workspace, slug: str) -> TermUsageResult:
    """§13.20 ``term usage`` (§10.2): documents mentioning the name or an alias.

    Case-insensitive, word-boundary matching over the term name and aliases
    (§10.2); document bodies only ("documents whose bodies mention").
    Informational — no edges are created.
    """
    resolved = _resolve_term_slug(workspace, slug)
    model = workspace.index.terms[resolved].model
    names = (model.term, *model.aliases)
    return TermUsageResult(
        slug=resolved,
        term=model.term,
        names=names,
        mentions=_document_mentions(workspace, names),
    )


def term_rename(workspace: Workspace, slug: str, new_term: str) -> TermRenameResult:
    """§13.20 ``term rename`` (§10.2): move the files, update the sidecar.

    The H1 is rewritten to the new name (``E-TERM-SLUG`` keeps H1 = ``term``)
    and the sidecar's ``term``/``slug`` follow the files. Body mentions of the
    old name and aliases are listed but never rewritten — prose is human-owned
    (§10.2). The stored ``body_hash`` is left stale on purpose: the H1 change
    is an effective content change (§7.3) and the version bump belongs to the
    reconcile pass (§7.5). A rename keeping the same slug (case change) edits
    in place. Refusals write nothing (``E-TERM-SLUG``, ``E-TERM-ALIAS-CLASH``).
    """
    old_slug = _resolve_term_slug(workspace, slug)
    old = workspace.index.terms[old_slug].model
    name = new_term.strip()
    if not name:
        raise ValueError("term name must not be blank")
    if name == old.term:
        loaded = workspace.index.terms[old_slug]
        return TermRenameResult(
            slug=old_slug,
            old_slug=old_slug,
            term=old.term,
            old_term=old.term,
            body=loaded.body,
            sidecar=loaded.sidecar,
            changed=False,
            notices=(f"{old_slug} is already named {old.term!r}",),
        )
    new_slug = derive_term_slug(name)
    if not new_slug:
        raise ValueError(f"term {new_term!r} derives an empty slug")
    taken = [
        key
        for key in workspace.index.terms
        if key != old_slug and key.casefold() == new_slug.casefold()
    ]
    if taken:
        raise OperationRefused(
            Finding(
                code="E-TERM-SLUG",
                severity="E",
                subject=new_slug,
                message=f"slug {new_slug!r} is already used by {taken[0]!r}",
                fix="gregraph term list",
            )
        )
    clash = _clashes_with_alias(workspace, name)
    if clash is not None:
        raise OperationRefused(
            Finding(
                code="E-TERM-ALIAS-CLASH",
                severity="E",
                subject=old_slug,
                message=f"term name {name!r} collides with {clash}",
                fix="gregraph term list",
            )
        )
    mentions = _document_mentions(workspace, (old.term, *old.aliases))
    loaded = workspace.index.terms[old_slug]
    text = read_body(workspace.root / loaded.body)
    old_abs_body, old_abs_sidecar = term_paths(workspace.root, old_slug)
    new_abs_body, new_abs_sidecar = term_paths(workspace.root, new_slug)
    if old_abs_body != new_abs_body:
        # move first (two-step for case-only renames on case-insensitive
        # filesystems), then rewrite the H1 and the sidecar in place
        _move_file(old_abs_body, new_abs_body)
        _move_file(old_abs_sidecar, new_abs_sidecar)
    write_body(new_abs_body, _replace_title(text, name))
    write_sidecar(
        new_abs_sidecar, old.model_copy(update={"term": name, "slug": new_slug})
    )
    workspace.reload()
    return TermRenameResult(
        slug=new_slug,
        old_slug=old_slug,
        term=name,
        old_term=old.term,
        body=new_abs_body.relative_to(workspace.root),
        sidecar=new_abs_sidecar.relative_to(workspace.root),
        mentions=mentions,
    )


def term_deprecate(
    workspace: Workspace, slug: str, *, reason: str
) -> TermDeprecateResult:
    """§13.20 ``term deprecate``: mark the term deprecated (spec §8, §10.2).

    Terms have no inbound links, so nothing becomes stale; deprecating an
    already-deprecated term is a no-op notice.
    """
    resolved = _resolve_term_slug(workspace, slug)
    loaded = workspace.index.terms[resolved]
    model = read_sidecar(workspace.root / loaded.sidecar, Term)
    if model.deprecated is not None:
        return TermDeprecateResult(
            slug=resolved,
            changed=False,
            deprecated=model.deprecated,
            notices=(f"{resolved} is already deprecated",),
        )
    marker = Deprecation(at=_now(), by=workspace.git.identity(), reason=reason)
    updated = model.model_copy(update={"deprecated": marker})
    write_sidecar(workspace.root / loaded.sidecar, updated)
    workspace.reload()
    return TermDeprecateResult(slug=resolved, changed=True, deprecated=marker)


# --- S15: templates, migrate, baselines, repair (spec §7.7, §12.4, §12.6) -
#
# Refusal-only codes outside the §14 catalogue (docs/backlog.md):
# ``E-GIT-UNAVAILABLE``, ``E-BASELINE-UNCOMMITTED``, ``E-BASELINE-INVALID``,
# ``E-BASELINE-EXISTS``.


@dataclass(frozen=True, slots=True)
class TemplateVersionInfo:
    """One template version row of ``template list``/``show`` (spec §13.17)."""

    version: int
    description: str
    deprecated: bool
    breaking: bool
    document_count: int


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """One template with all its versions (spec §13.17 ``template list``)."""

    name: str
    versions: tuple[TemplateVersionInfo, ...]


@dataclass(frozen=True, slots=True)
class TemplateListResult:
    """Result of :func:`template_list` (spec §13.17)."""

    templates: tuple[TemplateInfo, ...]


@dataclass(frozen=True, slots=True)
class TemplateAddResult:
    """Result of :func:`template_add` (spec §13.17). ``path`` is repo-relative."""

    name: str
    version: int
    path: Path
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateBumpResult:
    """Result of :func:`template_bump` (spec §13.17). ``path`` is repo-relative."""

    name: str
    version: int
    path: Path
    breaking: bool
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateShowResult:
    """Result of :func:`template_show` (spec §13.17, §4.2): descriptor +
    skeleton plus the repository-relative ``template.md`` path."""

    name: str
    descriptor: TemplateDescriptor
    skeleton: str
    path: Path = Path()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationItem:
    """Outcome of migrating one document (spec §7.7, §13.16)."""

    id: str
    kind: Literal["in-place", "superseding", "skipped"]
    from_version: int | None = None
    to_version: int | None = None
    new_id: str | None = None
    renamed: tuple[tuple[str, str], ...] = ()
    inserted: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    unmapped: tuple[str, ...] = ()
    manual_attention: tuple[str, ...] = ()
    stale_inbound: tuple[StaleInbound, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrateResult:
    """Result of :func:`migrate` (spec §13.16)."""

    dry_run: bool
    items: tuple[MigrationItem, ...]
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BaselineCreateResult:
    """Result of :func:`baseline_create` (spec §12.4): the annotated tag."""

    name: str
    tag: str
    manifest: str
    head: str | None
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BaselineListResult:
    """Result of :func:`baseline_list` (spec §12.4): ``baseline/*`` tag names."""

    tags: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairedSidecar:
    """One sidecar repaired by :func:`repair_versions` (spec §7.2, §12.6)."""

    path: Path
    version: int
    versions_seen: tuple[int, ...]
    clamped_links: int
    deduplicated_links: int
    changes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairVersionsResult:
    """Result of :func:`repair_versions` (spec §13.19)."""

    repaired: tuple[RepairedSidecar, ...] = ()
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RewrittenLink:
    """One inbound edge re-pointed by :func:`repair_regenerate_id` (§4.4)."""

    source: str
    type: LinkType
    old_target: str
    new_target: str


@dataclass(frozen=True, slots=True)
class RepairIdResult:
    """Result of :func:`repair_regenerate_id` (spec §4.4, §13.19)."""

    old_id: str
    new_id: str
    uuid: UUID
    body: Path
    sidecar: Path
    rewritten: tuple[RewrittenLink, ...] = ()
    manual: tuple[str, ...] = ()
    sidecar_document: Document | ChangeRequest | None = None
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairCacheResult:
    """Result of :func:`repair_cache` (spec §16.5): rebuilt cache sizes."""

    file_count: int
    types_seen: int
    templates_seen: int
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


# --- template commands (spec §13.17) --------------------------------------

_TEMPLATE_VERSION_DIR_RE: Final = re.compile(r"v(\d+)")
_BUILTIN_DIR: Final = "builtin_templates"
_BASELINE_TAG_PREFIX: Final = "baseline/"
_TAG_NAME_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_MANAGED_TOPS: Final = frozenset(
    directory.as_posix()
    for directory in (DOCUMENTS_DIR, CHANGES_DIR, GLOSSARY_DIR, ASSETS_DIR)
)


def _version_dir_number(name: str) -> int | None:
    match = _TEMPLATE_VERSION_DIR_RE.fullmatch(name)
    return int(match.group(1)) if match is not None else None


def _builtin_template(name: str) -> Traversable | None:
    source = resource_files("gregraph").joinpath(_BUILTIN_DIR).joinpath(name)
    return source if source.is_dir() else None


def _builtin_names() -> list[str]:
    root = resource_files("gregraph").joinpath(_BUILTIN_DIR)
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir())


def _write_version_dir(
    target: Path,
    version: int,
    files: Sequence[tuple[str, bytes]],
    *,
    breaking: bool | None = None,
) -> None:
    """Write one template version directory with ``version`` stamped in.

    ``template.json`` is rewritten with the new ``version`` (and ``breaking``
    when given) so the descriptor always matches its directory (spec §5.5).
    """
    target.mkdir(parents=True, exist_ok=True)
    for filename, data in files:
        if filename == "template.json":
            payload = json.loads(data.decode("utf-8"))
            payload["version"] = version
            if breaking is not None:
                payload["breaking"] = breaking
            text = (
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )
            (target / filename).write_text(text, encoding="utf-8")
        else:
            (target / filename).write_bytes(data)


def template_list(workspace: Workspace) -> TemplateListResult:
    """§13.17 ``template list``: names, versions, flags, document counts.

    ``document_count`` counts documents (spec §13.17) whose ``template`` pin is
    that exact ``<name>/v<N>``; CRs and terms are not counted.
    """
    templates = load_template_dir(templates_dir(workspace.root))
    counts: dict[tuple[str, int], int] = {}
    for loaded in workspace.index.documents.values():
        ref = loaded.model.template
        key = (ref.name, ref.version)
        counts[key] = counts.get(key, 0) + 1
    infos: list[TemplateInfo] = []
    for name in sorted(templates):
        versions = tuple(
            TemplateVersionInfo(
                version=entry.version,
                description=entry.descriptor.description,
                deprecated=entry.descriptor.deprecated,
                breaking=entry.descriptor.breaking,
                document_count=counts.get((name, entry.version), 0),
            )
            for entry in templates[name]
        )
        infos.append(TemplateInfo(name=name, versions=versions))
    return TemplateListResult(templates=tuple(infos))


def template_add(workspace: Workspace, builtin: str) -> TemplateAddResult:
    """§13.17 ``template add BUILTIN``: copy a built-in template in.

    Copied as ``v1``, or as the next version when the name already exists in
    the repository; the descriptor ``version`` is stamped to the directory
    number (spec §5.5, §13.17).
    """
    source = _builtin_template(builtin)
    if source is None:
        raise OperationRefused(
            Finding(
                code="E-TEMPLATE-UNKNOWN",
                severity="E",
                subject=builtin,
                message=(
                    f"no built-in template {builtin!r}; built-ins: "
                    + ", ".join(_builtin_names())
                ),
                fix="gregraph template list",
            )
        )
    existing = load_template_dir(templates_dir(workspace.root)).get(builtin)
    next_version = 1 if not existing else existing[-1].version + 1
    written = next_version
    root = templates_dir(workspace.root) / builtin
    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        if _version_dir_number(entry.name) is None or not entry.is_dir():
            continue
        files = [
            (child.name, child.read_bytes())
            for child in entry.iterdir()
            if child.is_file()
        ]
        _write_version_dir(root / f"v{next_version}", next_version, files)
        written = next_version
        next_version += 1
    return TemplateAddResult(
        name=builtin,
        version=written,
        path=(root / f"v{written}").relative_to(workspace.root),
    )


def template_bump(
    workspace: Workspace, name: str, *, breaking: bool = False
) -> TemplateBumpResult:
    """§13.17 ``template bump NAME [--breaking]``: copy ``v<N>`` to ``v<N+1>``.

    The new version's ``breaking`` flag is exactly ``--breaking`` (spec §5.5:
    ``breaking`` marks the step *to* that version, so a stale copy of the
    previous flag would mislabel the step); the user edits the new files.
    """
    versions = load_template_dir(templates_dir(workspace.root)).get(name)
    if not versions:
        raise OperationRefused(
            Finding(
                code="E-TEMPLATE-UNKNOWN",
                severity="E",
                subject=name,
                message=f"template {name!r} not found in the repository",
                fix="gregraph template list",
            )
        )
    latest = versions[-1]
    new_version = latest.version + 1
    source_dir = templates_dir(workspace.root) / name / f"v{latest.version}"
    target_dir = templates_dir(workspace.root) / name / f"v{new_version}"
    files = [
        (path.name, path.read_bytes())
        for path in sorted(source_dir.iterdir())
        if path.is_file()
    ]
    _write_version_dir(target_dir, new_version, files, breaking=breaking)
    return TemplateBumpResult(
        name=name,
        version=new_version,
        path=target_dir.relative_to(workspace.root),
        breaking=breaking,
    )


def template_show(
    workspace: Workspace, name: str, *, version: int | None = None
) -> TemplateShowResult:
    """§13.17 ``template show NAME [--version N]``: descriptor and skeleton.

    Without ``--version`` the latest non-deprecated version is shown; an
    explicit version is shown even when deprecated (``show`` is read-only).
    """
    versions = load_template_dir(templates_dir(workspace.root)).get(name)
    if not versions:
        raise OperationRefused(
            Finding(
                code="E-TEMPLATE-UNKNOWN",
                severity="E",
                subject=name,
                message=f"template {name!r} not found in the repository",
                fix="gregraph template list",
            )
        )
    notices: list[str] = []
    if version is not None:
        picked = next((t for t in versions if t.version == version), None)
        if picked is None:
            raise OperationRefused(
                Finding(
                    code="E-TEMPLATE-UNKNOWN",
                    severity="E",
                    subject=name,
                    message=f"template {name!r} has no version v{version}",
                    fix="gregraph template list",
                )
            )
    else:
        candidates = [t for t in versions if not t.descriptor.deprecated]
        if candidates:
            picked = candidates[-1]
        else:
            picked = versions[-1]
            notices.append(
                f"all versions of template {name!r} are deprecated; "
                f"showing v{picked.version}"
            )
    return TemplateShowResult(
        name=name,
        descriptor=picked.descriptor,
        skeleton=picked.body,
        path=TEMPLATES_RELPATH / name / f"v{picked.version}" / "template.md",
        notices=tuple(notices),
    )


# --- migrate (spec §7.7, §13.16) ------------------------------------------


def migrate(
    workspace: Workspace,
    *,
    doc_ids: Sequence[str] = (),
    select_all: bool = False,
    template: str | None = None,
    to_version: int | None = None,
    supersede: bool = False,
    dry_run: bool = False,
) -> MigrateResult:
    """§13.16 ``migrate`` (§7.7): execute S5's migration plans.

    Exactly one selection applies — explicit IDs, ``select_all`` (``--all``) or
    ``template`` (``--template NAME``); conflicting or empty selections are
    usage errors (:class:`ValueError`, exit 2). The target version is ``--to``
    or the latest non-deprecated version of the document's pinned template.

    In-place migration writes the plan's body (``renamed_from`` heading
    renames included) and updates the template pin only — the content change
    bumps ``version`` on the next commit (§7.7). Superseding migration (any
    breaking step, or ``supersede``) reuses :func:`supersede`, stamps the
    plan's body with ``## Unmapped content (migration)`` and pins the new
    document to the target template version. ``dry_run`` reports the plan
    without writing.
    """
    modes = sum((bool(doc_ids), bool(select_all), template is not None))
    if modes != 1:
        raise ValueError(
            "migrate takes exactly one selection: document IDs, --all or "
            "--template NAME"
        )
    selected = _migrate_selection(
        workspace, doc_ids=doc_ids, select_all=select_all, template=template
    )
    items = tuple(
        _migrate_one(
            workspace,
            doc_id,
            to_version=to_version,
            supersede=supersede,
            dry_run=dry_run,
        )
        for doc_id in selected
    )
    if not dry_run:
        workspace.reload()
    notices = () if items else ("nothing to migrate",)
    return MigrateResult(dry_run=dry_run, items=items, notices=notices)


def _migrate_selection(
    workspace: Workspace,
    *,
    doc_ids: Sequence[str],
    select_all: bool,
    template: str | None,
) -> list[str]:
    if select_all:
        return sorted(workspace.index.documents)
    if template is not None:
        return sorted(
            doc_id
            for doc_id, loaded in workspace.index.documents.items()
            if loaded.model.template.name == template
        )
    chosen: list[str] = []
    for raw in doc_ids:
        resolved = _resolve_doc_id(workspace, raw)
        if resolved not in chosen:
            chosen.append(resolved)
    return chosen


def _migration_skipped(
    doc_id: str, pin: TemplateRef, notice: str, to_version: int | None
) -> MigrationItem:
    return MigrationItem(
        id=doc_id,
        kind="skipped",
        from_version=pin.version,
        to_version=to_version,
        notices=(notice,),
    )


def _migrate_one(
    workspace: Workspace,
    doc_id: str,
    *,
    to_version: int | None,
    supersede: bool,
    dry_run: bool,
) -> MigrationItem:
    loaded = workspace.index.documents[doc_id]
    pin = loaded.model.template
    versions = load_template_dir(templates_dir(workspace.root)).get(pin.name)
    if not versions:
        return _migration_skipped(
            doc_id,
            pin,
            f"template {pin.name!r} is not in the repository",
            to_version,
        )
    current = next((t for t in versions if t.version == pin.version), None)
    if current is None:
        return _migration_skipped(
            doc_id,
            pin,
            f"template {pin.name!r} v{pin.version} is not in the repository",
            to_version,
        )
    if to_version is not None:
        target = next((t for t in versions if t.version == to_version), None)
        if target is None:
            return _migration_skipped(
                doc_id,
                pin,
                f"template {pin.name!r} has no version v{to_version}",
                to_version,
            )
    else:
        candidates = [t for t in versions if not t.descriptor.deprecated]
        if not candidates:
            return _migration_skipped(
                doc_id,
                pin,
                f"all versions of template {pin.name!r} are deprecated",
                to_version,
            )
        target = candidates[-1]
    if target.version == pin.version:
        return _migration_skipped(
            doc_id,
            pin,
            f"{doc_id} already pins template {pin.name!r} v{pin.version}",
            target.version,
        )
    if target.version < pin.version:
        return _migration_skipped(
            doc_id,
            pin,
            f"{doc_id} pins v{pin.version}, which is newer than target "
            f"v{target.version}; downgrade is not supported",
            to_version,
        )
    chain = tuple(t for t in versions if pin.version < t.version <= target.version)
    body_text = read_body(workspace.root / loaded.body)
    plan = plan_migration(
        current=current,
        target=target,
        body=body_text,
        chain=chain,
        supersede=supersede,
    )
    if dry_run:
        return MigrationItem(
            id=doc_id,
            kind=plan.kind,
            from_version=pin.version,
            to_version=target.version,
            renamed=tuple(plan.renamed),
            inserted=tuple(plan.inserted),
            unknown=tuple(plan.unknown),
            unmapped=tuple(plan.unmapped),
            manual_attention=tuple(plan.manual_attention),
            findings=tuple(plan.findings),
            notices=("dry run: nothing written",),
        )
    if plan.kind == "in-place":
        write_body(workspace.root / loaded.body, plan.new_body)
        document = read_sidecar(workspace.root / loaded.sidecar, Document)
        document.template = TemplateRef(name=pin.name, version=target.version)
        write_sidecar(workspace.root / loaded.sidecar, document)
        return MigrationItem(
            id=doc_id,
            kind="in-place",
            from_version=pin.version,
            to_version=target.version,
            renamed=tuple(plan.renamed),
            inserted=tuple(plan.inserted),
            unknown=tuple(plan.unknown),
            findings=tuple(plan.findings),
        )
    return _migrate_superseding(
        workspace, doc_id, pin=pin, target_version=target.version, plan=plan
    )


def _migrate_superseding(
    workspace: Workspace,
    doc_id: str,
    *,
    pin: TemplateRef,
    target_version: int,
    plan: MigrationPlan,
) -> MigrationItem:
    loaded = workspace.index.documents[doc_id]
    result = supersede(
        workspace,
        targets=[doc_id],
        title=loaded.model.title,
        type=loaded.model.type,
        copy_body=True,
        copy_links=True,
    )
    new_body = _replace_title(plan.new_body, loaded.model.title)
    write_body(workspace.root / result.body, new_body)
    document = read_sidecar(workspace.root / result.sidecar, Document)
    document.template = TemplateRef(name=pin.name, version=target_version)
    document.body_hash = body_hash(new_body)
    document.assets = _compute_assets(workspace, result.body, new_body, result.id)
    write_sidecar(workspace.root / result.sidecar, document)
    return MigrationItem(
        id=doc_id,
        kind="superseding",
        from_version=plan.from_version,
        to_version=target_version,
        new_id=result.id,
        renamed=tuple(plan.renamed),
        unmapped=tuple(plan.unmapped),
        manual_attention=tuple(plan.manual_attention),
        stale_inbound=result.stale_inbound,
        notices=tuple(result.notices),
    )


# --- baselines (spec §12.4, §13.21) ---------------------------------------


def _uncommitted_managed(workspace: Workspace) -> list[Path]:
    """Uncommitted (staged, unstaged or untracked) files under managed dirs."""
    git = workspace.git
    candidates = sorted(set(git.changed_paths()) | set(git.untracked_paths()))
    return [
        path for path in candidates if path.parts and path.parts[0] in _MANAGED_TOPS
    ]


def _baseline_manifest(workspace: Workspace) -> str:
    """The generated manifest embedded in the tag message (spec §12.4).

    JSON (``indent=2, sort_keys=True``): ID prefix, tool version and one row
    per document (``id``, ``version``, ``body_hash``, ``status``). The format
    is fixed now so v0.2 can diff manifests.
    """
    report = compute_status(workspace)
    rows: list[dict[str, object]] = []
    for doc_id in sorted(workspace.index.documents):
        loaded = workspace.index.documents[doc_id]
        item = report.documents.get(doc_id)
        rows.append(
            {
                "id": doc_id,
                "version": loaded.model.version,
                "body_hash": loaded.model.body_hash,
                "status": item.status if item is not None else "unknown",
            }
        )
    payload = {
        "schema": 1,
        "tool_version": __version__,
        "id_prefix": workspace.config.ids.prefix,
        "documents": rows,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def baseline_create(
    workspace: Workspace, name: str, *, message: str = ""
) -> BaselineCreateResult:
    """§13.21 ``baseline create NAME [-m MSG]`` (§12.4).

    Creates the annotated tag ``baseline/<name>`` whose message contains the
    generated manifest. Refuses when the working tree has uncommitted files
    under the managed directories, when ``validate`` reports errors, when the
    tag already exists, or without Git (``E-GIT-UNAVAILABLE``).
    """
    if _TAG_NAME_RE.fullmatch(name) is None:
        raise ValueError(
            f"invalid baseline name {name!r}: use letters, digits, '.', '_', '-'"
        )
    git = workspace.git
    if not git.is_repo():
        raise OperationRefused(
            Finding(
                code="E-GIT-UNAVAILABLE",
                severity="E",
                subject=name,
                message="baseline create needs a git repository",
                fix="git init",
            )
        )
    head = git.head_sha()
    if head is None:
        raise OperationRefused(
            Finding(
                code="E-GIT-UNAVAILABLE",
                severity="E",
                subject=name,
                message="cannot create a baseline: the repository has no commits",
                fix="git commit",
            )
        )
    uncommitted = _uncommitted_managed(workspace)
    if uncommitted:
        listed = ", ".join(path.as_posix() for path in uncommitted[:5])
        raise OperationRefused(
            Finding(
                code="E-BASELINE-UNCOMMITTED",
                severity="E",
                subject=uncommitted[0],
                message=(
                    "uncommitted file(s) under the managed directories: "
                    + listed
                    + ("…" if len(uncommitted) > 5 else "")
                ),
                fix="git add documents/ && git commit",
            )
        )
    findings = validate_workspace(workspace)
    if has_errors(findings):
        errors = [f for f in findings if f.severity == "E"]
        raise OperationRefused(
            Finding(
                code="E-BASELINE-INVALID",
                severity="E",
                subject=name,
                message=(
                    f"validation reports {len(errors)} error(s); fix them first "
                    f"(first: {errors[0].code} {errors[0].message})"
                ),
                fix="gregraph validate",
            )
        )
    tag = f"{_BASELINE_TAG_PREFIX}{name}"
    if tag in git.tags(_BASELINE_TAG_PREFIX):
        raise OperationRefused(
            Finding(
                code="E-BASELINE-EXISTS",
                severity="E",
                subject=tag,
                message=f"tag {tag!r} already exists",
                fix="gregraph baseline list",
            )
        )
    manifest = _baseline_manifest(workspace)
    text = f"{message}\n\n{manifest}" if message else manifest
    git.tag_annotated(tag, text)
    return BaselineCreateResult(name=name, tag=tag, manifest=manifest, head=head)


def baseline_list(workspace: Workspace) -> BaselineListResult:
    """§13.21 ``baseline list`` (§12.4): the ``baseline/*`` tags, sorted."""
    git = workspace.git
    if not git.is_repo():
        return BaselineListResult(
            notices=("note: not a git repository — baseline list unavailable",)
        )
    return BaselineListResult(tags=tuple(git.tags(_BASELINE_TAG_PREFIX)))


# --- repair (spec §7.2, §12.6, §4.4, §16.5, §13.19) -----------------------


def repair_versions(workspace: Workspace) -> RepairVersionsResult:
    """§13.19 ``repair versions`` (§7.2, §12.6): repair conflicted sidecars.

    Every managed sidecar still carrying conflict markers is repaired with S9
    :func:`gregraph.core.versioning.repair_versions`: ``version`` becomes
    ``max(versions seen) + 1``, ``body_hash``/``assets`` are recomputed from
    the body and ``links[].target_version`` is clamped and de-duplicated. A
    sidecar already resolved to valid JSON is left to ``sync``/the hook.
    """
    root = workspace.root
    entries: list[tuple[ManagedFiles, bool]] = [
        (entry, True) for entry in iter_documents(root)
    ]
    entries.extend((entry, False) for entry in iter_changes(root))
    entries.extend((entry, False) for entry in iter_terms(root))
    repaired: list[RepairedSidecar] = []
    notices: list[str] = []
    for entry, is_document in entries:
        if not entry.sidecar.is_file():
            continue
        text = entry.sidecar.read_bytes().decode("utf-8-sig")
        if "<<<<<<<" not in text:
            continue
        body_text = read_body(entry.body) if entry.body.is_file() else None
        asset_hashes: list[tuple[str, str]] | None = None
        if is_document and body_text is not None:
            assets = _compute_assets(
                workspace, entry.body.relative_to(root), body_text, entry.stem
            )
            asset_hashes = [(asset.path, asset.hash) for asset in assets]
        try:
            result = versioning.repair_versions(
                text, body=body_text, asset_hashes=asset_hashes
            )
        except ValueError as exc:
            notices.append(f"{entry.sidecar.relative_to(root)}: {exc}")
            continue
        entry.sidecar.write_bytes(result.text.encode("utf-8"))
        repaired.append(
            RepairedSidecar(
                path=entry.sidecar.relative_to(root),
                version=result.version,
                versions_seen=tuple(result.versions_seen),
                clamped_links=result.clamped_links,
                deduplicated_links=result.deduplicated_links,
                changes=tuple(result.changes),
            )
        )
    if not repaired and not notices:
        notices.append("no conflicted sidecars found")
    return RepairVersionsResult(repaired=tuple(repaired), notices=tuple(notices))


def _in_branch_history(workspace: Workspace, relpath: Path) -> bool:
    """Whether ``relpath`` is part of the current branch's history (§4.4).

    Without Git (or before the first commit) the working tree is the whole
    history, so every file qualifies; otherwise the file must be tracked.
    """
    git = workspace.git
    if not git.is_repo() or git.head_sha() is None:
        return True
    return git.is_tracked(relpath)


def repair_regenerate_id(workspace: Workspace, path: Path) -> RepairIdResult:
    """§13.19 ``repair regenerate-id PATH`` (§4.4): fix an ``E-ID-DUPLICATE``.

    Gives the document at ``path`` a fresh UUID/ID and renames its files.
    Inbound edges whose ``target`` is the old ID are rewritten to the new ID
    when the source is from the same branch's history; the rest — inbound
    links outside the history, body mentions and CR references to the old ID —
    are listed for manual re-linking (they cannot be disambiguated between
    the duplicate pair automatically). The old ID is left with the twin that
    keeps it; a notice points at the possible ambiguity.
    """
    root = workspace.root
    candidate = (path if path.is_absolute() else root / path).resolve()
    target: ManagedFiles | None = None
    for entry in iter_documents(root):
        if entry.body.resolve() == candidate or entry.sidecar.resolve() == candidate:
            target = entry
            break
    if target is None:
        raise OperationRefused(
            Finding(
                code="E-ID-UNKNOWN",
                severity="E",
                subject=path,
                message=f"no document at {path}",
                fix="gregraph list",
            )
        )
    old_id = target.stem
    try:
        document = read_sidecar(target.sidecar, Document)
    except (OSError, ValueError) as exc:
        raise OperationRefused(
            Finding(
                code="E-SIDECAR-INVALID",
                severity="E",
                subject=target.sidecar.relative_to(root),
                message=f"invalid sidecar ({exc})",
            )
        ) from exc
    if document.id != old_id:
        raise OperationRefused(
            Finding(
                code="E-ID-FILENAME",
                severity="E",
                subject=target.sidecar.relative_to(root),
                message=f"id {document.id!r} must equal the filename stem {old_id!r}",
            )
        )
    generated = generate_id(
        _existing_ids(workspace) | {old_id}, workspace.config.ids.prefix
    )
    body_rel = target.body.relative_to(root)
    sidecar_rel = target.sidecar.relative_to(root)
    new_body_rel = body_rel.with_name(f"{generated.id}.md")
    new_sidecar_rel = sidecar_rel.with_name(f"{generated.id}.json")

    document.uuid = generated.uuid
    document.id = generated.id
    _move_file(target.body, root / new_body_rel)
    _move_file(target.sidecar, root / new_sidecar_rel)
    write_sidecar(root / new_sidecar_rel, document)

    rewritten: list[RewrittenLink] = []
    manual: list[str] = []
    notices: list[str] = []
    for entry in iter_documents(root):
        if entry.sidecar == root / new_sidecar_rel:
            continue
        try:
            source = read_sidecar(entry.sidecar, Document)
        except (OSError, ValueError):
            continue
        source_rel = entry.sidecar.relative_to(root)
        changed = False
        for link_entry in source.links:
            if link_entry.target != old_id:
                continue
            if _in_branch_history(workspace, source_rel):
                rewritten.append(
                    RewrittenLink(
                        source=source.id,
                        type=link_entry.type,
                        old_target=old_id,
                        new_target=generated.id,
                    )
                )
                link_entry.target = generated.id
                changed = True
            else:
                manual.append(
                    f"link {source.id} {link_entry.type} -> {old_id} is outside "
                    f"the branch history; re-link manually"
                )
        if changed:
            write_sidecar(entry.sidecar, source)

    for entry in (
        list(iter_documents(root)) + list(iter_changes(root)) + list(iter_terms(root))
    ):
        if not entry.body.is_file():
            continue
        body_rel_path = entry.body.relative_to(root)
        for mention in find_mentions(read_body(entry.body), doc_path=body_rel_path):
            if mention.id == old_id:
                manual.append(
                    f"body of {body_rel_path.as_posix()} mentions {old_id}; "
                    "re-link manually"
                )
    for cr_id in sorted(workspace.index.changes):
        model = workspace.index.changes[cr_id].model
        if any(entry.id == old_id for entry in model.scope):
            manual.append(
                f"change request {cr_id} scope references {old_id}; update manually"
            )
        if old_id in model.introduces:
            manual.append(
                f"change request {cr_id} introduces {old_id}; update manually"
            )

    twins = [
        entry
        for entry in iter_documents(root)
        if entry.stem == old_id and entry.sidecar != root / new_sidecar_rel
    ]
    if twins:
        notices.append(
            f"{old_id} is still claimed by {twins[0].body.relative_to(root)}; "
            f"rewritten links may have meant that document — review them"
        )
    if assets_dir(root, old_id).is_dir():
        manual.append(
            f"assets/{old_id}/ still holds files for the old ID; copy or move "
            "them manually (assets are single-owner, §5.7)"
        )
    workspace.reload()
    return RepairIdResult(
        old_id=old_id,
        new_id=generated.id,
        uuid=generated.uuid,
        body=new_body_rel,
        sidecar=new_sidecar_rel,
        rewritten=tuple(rewritten),
        manual=tuple(manual),
        notices=tuple(notices),
    )


def repair_cache(workspace: Workspace) -> RepairCacheResult:
    """§13.19 ``repair cache`` (§16.5): delete and rebuild the index cache.

    Freshly recomputes the body-hash ``files`` map for every managed body and
    the ``types_seen``/``templates_seen`` maps via
    :func:`gregraph.core.validation.refresh_cache`.
    """
    root = workspace.root
    files: dict[str, CacheFileEntry] = {}
    bodies: list[ManagedFiles] = [
        *iter_documents(root),
        *iter_changes(root),
        *iter_terms(root),
    ]
    for entry in bodies:
        if not entry.body.is_file():
            continue
        key = entry.body.relative_to(root).as_posix()
        files[key] = stat_cache_entry(entry.body, body_hash(read_body(entry.body)))
    cache = CacheIndex().model_copy(update={"files": files})
    cache = refresh_cache(
        cache,
        config=workspace.config,
        documents=(loaded.model for loaded in workspace.index.documents.values()),
        templates=load_template_dir(templates_dir(root)),
    )
    write_cache(root, cache)
    workspace.reload()
    return RepairCacheResult(
        file_count=len(cache.files),
        types_seen=len(cache.types_seen),
        templates_seen=len(cache.templates_seen),
    )


# --- agent readiness: introspection, context, scaffolding (§4, §6, §7) -----
#
# ``describe_schema`` (§4.1), ``link_candidates`` (§4.3), ``build_context``
# (§6.1), ``list --body`` (§6.3) and the agent scaffolding (§7) make the tool
# agent-ready: one call answers "what are the rules" (AGENT-021), "what may I
# link" (AGENT-023) and "what is the context" (AGENT-027) without reading
# configuration files or source. ``core`` never prints; the CLI renders.

_KIND_ORDER: Final[tuple[str, ...]] = (
    "goal",
    "requirement",
    "design",
    "verification",
    "information",
)

#: §6.1 "Meaning / use when" per edge type, with the picker hints of the
#: interactive link flow (the CLI's wording, restated here so ``core`` never
#: imports ``cli``).
_EDGE_DESCRIPTIONS: Final[dict[str, str]] = {
    "refines": (
        "Source states the same intent as target, more concretely (decomposition)."
    ),
    "derives-from": (
        "Source is a new requirement caused by the target, not a decomposition of it."
    ),
    "depends-on": (
        "Source cannot be implemented or is meaningless unless target is "
        "realised (ordering, not decomposition)."
    ),
    "satisfies": "A design element realises a requirement.",
    "verifies": ("A test or inspection provides evidence for a requirement or design."),
    "constrains": (
        "Source is a cross-cutting requirement that limits how target may be "
        "realised; use instead of refines for quality attributes."
    ),
    "supersedes": "Source replaces target, which becomes superseded.",
    "conflicts-with": (
        "The two cannot both be satisfied as written; recorded until resolved."
    ),
    "relates-to": "Weak association with no other semantics (last resort).",
}


def _kind_tuple(kinds: Set[str]) -> tuple[str, ...]:
    """§4.1 kind sets in the canonical §4.1 kind order."""
    return tuple(kind for kind in _KIND_ORDER if kind in kinds)


@dataclass(frozen=True, slots=True)
class SchemaTypeInfo:
    """One configured type of ``describe_schema`` (AGENT_READINESS §4.1)."""

    kind: str
    folder: str
    template: str
    id_prefix: str
    description: str


@dataclass(frozen=True, slots=True)
class SchemaEdgeRule:
    """One §6.1 edge-rule row of ``describe_schema`` (AGENT_READINESS §4.1)."""

    type: str
    direction: str
    hierarchical: bool
    acyclic: bool
    source_kinds: tuple[str, ...]
    target_kinds: tuple[str, ...]
    same_kind_only: bool
    mutually_exclusive_with: tuple[str, ...]
    mutually_exclusive_opposite: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class SchemaTemplateInfo:
    """One template of ``describe_schema``: the active version plus all
    version numbers present (AGENT_READINESS §4.1)."""

    latest_version: int
    versions: tuple[int, ...]
    deprecated: bool
    breaking: bool
    description: str
    sections: tuple[TemplateSection, ...]


@dataclass(frozen=True, slots=True)
class SchemaCrLifecycle:
    """The CR state machine of ``describe_schema`` (AGENT_READINESS §4.1)."""

    statuses: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    scope_intents: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchemaInfo:
    """Result of :func:`describe_schema` — the repository rulebook (§4.1)."""

    schema_: int
    tool_version: str
    id_prefix: str
    baseline_branch: str
    versioning: dict[str, Any]
    graph: dict[str, Any]
    assets: dict[str, Any]
    cr: dict[str, Any]
    types: dict[str, SchemaTypeInfo]
    kinds: tuple[str, ...]
    edge_rules: tuple[SchemaEdgeRule, ...]
    templates: dict[str, SchemaTemplateInfo]
    cr_lifecycle: SchemaCrLifecycle


def describe_schema(workspace: Workspace, *, type: str | None = None) -> SchemaInfo:
    """The repository rulebook for agents (AGENT_READINESS §4.1, AGENT-021).

    ``--type`` filters ``types`` to that type and ``templates`` to the
    templates its entries reference (plus the CR template while CRs are
    enabled); unknown type names refuse ``E-TYPE-UNKNOWN``. ``edge_rules``,
    ``kinds`` and ``cr_lifecycle`` are global and stay.
    """
    if type is not None and type not in workspace.config.types:
        raise OperationRefused(
            Finding(
                code="E-TYPE-UNKNOWN",
                severity="E",
                subject=type,
                message=f"unknown document type {type!r}",
                fix="gregraph schema",
            )
        )
    templates = load_template_dir(templates_dir(workspace.root))
    active: dict[str, LoadedTemplate] = {}
    for name, versions in templates.items():
        live = [entry for entry in versions if not entry.descriptor.deprecated]
        active[name] = live[-1] if live else versions[-1]
    if type is not None:
        wanted_types = {type}
    else:
        wanted_types = set(workspace.config.types)
    config_types = workspace.config.types
    types: dict[str, SchemaTypeInfo] = {}
    for name in sorted(wanted_types):
        spec = config_types[name]
        chosen = active.get(spec.template)
        types[name] = SchemaTypeInfo(
            kind=spec.kind,
            folder=spec.folder,
            template=spec.template,
            id_prefix=workspace.config.ids.prefix,
            description=chosen.descriptor.description if chosen is not None else "",
        )
    if type is not None:
        template_names = {spec.template for spec in types.values()}
        if workspace.config.cr.enabled:
            template_names.add(workspace.config.cr.template)
    else:
        template_names = set(active)
    schema_templates: dict[str, SchemaTemplateInfo] = {}
    for name in sorted(template_names):
        chosen = active.get(name)
        if chosen is None:
            continue
        schema_templates[name] = SchemaTemplateInfo(
            latest_version=chosen.version,
            versions=tuple(entry.version for entry in templates[name]),
            deprecated=chosen.descriptor.deprecated,
            breaking=chosen.descriptor.breaking,
            description=chosen.descriptor.description,
            sections=tuple(chosen.descriptor.sections),
        )
    exclusive_same: dict[str, set[str]] = {}
    exclusive_opposite: dict[str, set[str]] = {}
    for pair in (*MUTUALLY_EXCLUSIVE_SAME_PAIR, *MUTUALLY_EXCLUSIVE_OPPOSITE):
        members = sorted(pair)
        target_map = (
            exclusive_same
            if pair in MUTUALLY_EXCLUSIVE_SAME_PAIR
            else exclusive_opposite
        )
        for member in members:
            target_map.setdefault(member, set()).update(
                other for other in members if other != member
            )
    edge_rules = tuple(
        SchemaEdgeRule(
            type=edge_type,
            direction=rule.direction,
            hierarchical=rule.hierarchical,
            acyclic=rule.direction == "directed",
            source_kinds=_kind_tuple(rule.source_kinds),
            target_kinds=_kind_tuple(rule.target_kinds),
            same_kind_only=rule.same_kind_only,
            mutually_exclusive_with=tuple(sorted(exclusive_same.get(edge_type, ()))),
            mutually_exclusive_opposite=tuple(
                sorted(exclusive_opposite.get(edge_type, ()))
            ),
            description=_EDGE_DESCRIPTIONS.get(edge_type, ""),
        )
        for edge_type, rule in EDGE_RULES.items()
    )
    transitions: dict[str, tuple[str, ...]] = {
        status: tuple(changes.ALLOWED_TRANSITIONS[status])
        for status in changes.CR_STATUSES
    }
    return SchemaInfo(
        schema_=workspace.config.gregraph.config_schema,
        tool_version=__version__,
        id_prefix=workspace.config.ids.prefix,
        baseline_branch=workspace.config.git.baseline_branch,
        versioning=dict(workspace.config.versioning.model_dump()),
        graph=dict(workspace.config.graph.model_dump()),
        assets=dict(workspace.config.assets.model_dump()),
        cr=dict(workspace.config.cr.model_dump()),
        types=types,
        kinds=_KIND_ORDER,
        edge_rules=edge_rules,
        templates=schema_templates,
        cr_lifecycle=SchemaCrLifecycle(
            statuses=tuple(changes.CR_STATUSES),
            transitions=transitions,
            scope_intents=tuple(changes.SCOPE_INTENTS),
        ),
    )


@dataclass(frozen=True, slots=True)
class LinkCandidate:
    """One admissible link target of :func:`link_candidates` (§4.3)."""

    type: LinkType
    target: str
    target_title: str
    target_type: str
    target_kind: Kind | None


@dataclass(frozen=True, slots=True)
class LinkCandidatesResult:
    """Result of :func:`link_candidates` (AGENT_READINESS §4.3, AGENT-023)."""

    source: str
    source_kind: Kind | None
    allowed_edge_types: tuple[LinkType, ...]
    candidates: tuple[LinkCandidate, ...]
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


def link_candidates(
    workspace: Workspace, *, source: str, edge_type: LinkType | None = None
) -> LinkCandidatesResult:
    """Admissible link targets for one source (AGENT_READINESS §4.3, AGENT-023).

    The interactive picker's filtering, moved into core so the picker becomes
    a caller: the §6.1 kind rule (unknown kinds skip the check, as in the
    picker), target liveness (not deprecated, not superseded) and cycle
    pre-exclusion via :meth:`gregraph.core.graph.Graph.check_link`. Unknown
    edge types are usage errors (``ValueError``); an unknown source refuses
    ``E-ID-UNKNOWN``. Candidates are sorted by ``(type, target)``.
    """
    if edge_type is not None and edge_type not in EDGE_RULES:
        raise ValueError(f"unknown link type {edge_type!r}")
    resolved = _resolve_doc_id(workspace, source)
    graph = workspace.graph
    source_kind = graph.kind_of(resolved)
    allowed = tuple(
        candidate
        for candidate, rule in EDGE_RULES.items()
        if source_kind is None or source_kind in rule.source_kinds
    )
    index = workspace.index
    wanted_types: tuple[LinkType, ...] = (
        (edge_type,) if edge_type is not None else allowed
    )
    candidates: list[LinkCandidate] = []
    for candidate_type in wanted_types:
        if candidate_type not in allowed:
            continue
        for target_id in sorted(index.documents):
            target_loaded = index.documents[target_id]
            target_kind = graph.kind_of(target_id)
            if (
                source_kind is not None
                and target_kind is not None
                and not edge_kind_allowed(candidate_type, source_kind, target_kind)
            ):
                continue
            if target_loaded.model.deprecated is not None or graph.is_superseded(
                target_id
            ):
                continue
            check = graph.check_link(resolved, candidate_type, target_id)
            if (
                check.outcome == "refused"
                and check.refusal is not None
                and check.refusal.code == "E-CYCLE"
            ):
                continue
            candidates.append(
                LinkCandidate(
                    type=candidate_type,
                    target=target_id,
                    target_title=target_loaded.model.title,
                    target_type=target_loaded.model.type,
                    target_kind=target_kind,
                )
            )
    candidates.sort(key=lambda item: (item.type, item.target))
    return LinkCandidatesResult(
        source=resolved,
        source_kind=source_kind,
        allowed_edge_types=allowed,
        candidates=tuple(candidates),
    )


@dataclass(frozen=True, slots=True)
class ContextEdge:
    """The edge connecting a neighbour to the bundle (AGENT_READINESS §6.1)."""

    source: str
    type: str
    target: str


@dataclass(frozen=True, slots=True)
class ContextTarget:
    """One requested bundle entry: the ``show`` payload plus parsed sections."""

    show: ShowResult
    sections: tuple[Section, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextNeighbor:
    """One BFS neighbour of the bundle (AGENT_READINESS §6.1, AGENT-027)."""

    id: str
    via: ContextEdge
    direction: Literal["upstream", "downstream"]
    depth: int
    freshness: str
    sidecar: Document
    body: str


@dataclass(frozen=True, slots=True)
class ContextTerm:
    """One glossary term matched in a bundle body (AGENT_READINESS §6.1)."""

    term: str
    slug: str
    aliases: tuple[str, ...]
    body: str


@dataclass(frozen=True, slots=True)
class ContextResult:
    """Result of :func:`build_context` (AGENT_READINESS §6.1)."""

    requested: tuple[str, ...]
    depth: int
    direction: Literal["both", "upstream", "downstream"]
    targets: tuple[ContextTarget, ...]
    neighbors: tuple[ContextNeighbor, ...]
    terms: tuple[ContextTerm, ...]
    findings: tuple[Finding, ...] = ()


def _finding_covers_edge(
    finding: Finding, source: str, edge_type: str, target: str
) -> bool:
    """Whether ``finding`` already reports the given edge (§6.1)."""
    return str(finding.subject) == source and (
        f"link {edge_type} → {target}" in finding.message
    )


def build_context(
    workspace: Workspace,
    *,
    ids: Sequence[str],
    depth: int = 1,
    direction: Literal["both", "upstream", "downstream"] = "both",
    include_terms: bool = True,
) -> ContextResult:
    """One-call context bundle (AGENT_READINESS §6.1, AGENT-027, D-AGENT-8).

    ``targets`` re-use the ``show`` payload per requested ID (documents and
    CRs) plus the parsed sections; ``neighbors`` is a BFS over graph edges up
    to ``depth`` filtered by ``direction`` — a CR's neighbours are its scope
    targets and impact set as downstream edges with a synthetic ``scope`` edge
    — each carrying the connecting edge, its direction, the BFS depth and the
    §7.4 freshness state of that edge. ``terms`` lists every glossary term (or
    alias) occurring in a bundle body (§10.2 word-boundary matching).
    ``findings`` collects the ``validate`` findings whose subject is a bundle
    ID plus the freshness findings of all non-fresh edges among bundle
    documents, de-duplicated by ``(code, subject, message)``.
    """
    if depth < 0:
        raise ValueError("depth must be >= 0")
    if direction not in ("both", "upstream", "downstream"):
        raise ValueError(
            f"invalid direction {direction!r}: use both|upstream|downstream"
        )
    if not ids:
        raise ValueError("build_context needs at least one document or CR id")
    known = set(workspace.index.documents) | set(workspace.index.changes)
    requested: list[str] = []
    for raw in ids:
        resolved = normalise_id(raw, workspace.config.ids.prefix, known=known)
        if resolved is None:
            raise OperationRefused(
                Finding(
                    code="E-ID-UNKNOWN",
                    severity="E",
                    subject=raw,
                    message=f"no document or change request with id {raw!r}",
                    fix="gregraph list",
                )
            )
        if resolved not in requested:
            requested.append(resolved)

    freshness = _link_freshness(workspace)
    state_by_key = {entry.key: entry.state for entry in freshness.entries}
    graph = workspace.graph

    targets: list[ContextTarget] = []
    for target_id in requested:
        show = show_document(workspace, target_id, body=True)
        if show.change_request is not None:
            body_text = show.change_request.body
        else:
            body_text = show.body_text or ""
        targets.append(
            ContextTarget(show=show, sections=tuple(parse_sections(body_text)))
        )

    visited: set[str] = set(requested)
    neighbors: list[ContextNeighbor] = []
    frontier: list[str] = list(requested)
    for current_depth in range(1, depth + 1):
        next_frontier: list[str] = []
        for node_id in frontier:
            candidates: list[
                tuple[str, ContextEdge, Literal["upstream", "downstream"]]
            ] = []
            if node_id in workspace.index.changes:
                if direction in ("both", "downstream"):
                    cr_show = changes.show_change(workspace, node_id)
                    seen: set[str] = set()
                    for neighbour_id in (
                        *(row.id for row in cr_show.scope),
                        *cr_show.impact,
                    ):
                        if neighbour_id in seen:
                            continue
                        seen.add(neighbour_id)
                        candidates.append(
                            (
                                neighbour_id,
                                ContextEdge(
                                    source=node_id, type="scope", target=neighbour_id
                                ),
                                "downstream",
                            )
                        )
            elif node_id in workspace.index.documents:
                if direction in ("both", "downstream"):
                    for edge in graph.outbound_edges(node_id):
                        candidates.append(
                            (
                                edge.target,
                                ContextEdge(
                                    source=edge.source,
                                    type=edge.type,
                                    target=edge.target,
                                ),
                                "downstream",
                            )
                        )
                if direction in ("both", "upstream"):
                    for edge in graph.inbound_edges(node_id):
                        if edge.source != node_id:
                            candidates.append(
                                (
                                    edge.source,
                                    ContextEdge(
                                        source=edge.source,
                                        type=edge.type,
                                        target=edge.target,
                                    ),
                                    "upstream",
                                )
                            )
            for neighbour_id, via, edge_direction in candidates:
                if neighbour_id in visited or neighbour_id not in graph.nodes:
                    continue
                if neighbour_id not in workspace.index.documents:
                    continue
                visited.add(neighbour_id)
                next_frontier.append(neighbour_id)
                loaded = workspace.index.documents[neighbour_id]
                neighbors.append(
                    ContextNeighbor(
                        id=neighbour_id,
                        via=via,
                        direction=edge_direction,
                        depth=current_depth,
                        freshness=state_by_key.get(
                            (via.source, via.type, via.target), "fresh"
                        ),
                        sidecar=loaded.model,
                        body=_body_text_or_none(workspace.root, loaded.body) or "",
                    )
                )
        frontier = next_frontier

    terms: list[ContextTerm] = []
    if include_terms:
        bundle_bodies = [
            *(target.show.body_text or "" for target in targets),
            *(neighbour.body for neighbour in neighbors),
        ]
        for slug in sorted(workspace.index.terms):
            term_loaded = workspace.index.terms[slug]
            model = term_loaded.model
            names = (model.term, *model.aliases)
            if any(_matched_names(text, names) for text in bundle_bodies):
                terms.append(
                    ContextTerm(
                        term=model.term,
                        slug=model.slug,
                        aliases=tuple(model.aliases),
                        body=_body_text_or_none(workspace.root, term_loaded.body) or "",
                    )
                )

    bundle_ids = set(requested) | {neighbour.id for neighbour in neighbors}
    findings: list[Finding] = [
        finding
        for finding in validate_workspace(workspace)
        if str(finding.subject) in bundle_ids
    ]
    for entry in freshness.entries:
        if entry.state == "fresh" or entry.type == "supersedes":
            continue
        if entry.source not in bundle_ids or entry.target not in bundle_ids:
            continue
        if any(
            _finding_covers_edge(finding, entry.source, entry.type, entry.target)
            for finding in findings
        ):
            continue
        if entry.state == "stale":
            if graph.is_superseded(entry.target):
                findings.append(
                    Finding(
                        code="W-LINK-STALE",
                        severity="W",
                        subject=entry.source,
                        message=(
                            f"link {entry.type} → {entry.target}: target is superseded"
                        ),
                        fix=(
                            f"gregraph link refresh {entry.source} {entry.target} "
                            "--follow"
                        ),
                    )
                )
            else:
                findings.append(
                    Finding(
                        code="W-LINK-STALE",
                        severity="W",
                        subject=entry.source,
                        message=(
                            f"link {entry.type} → {entry.target}: target is deprecated"
                        ),
                        fix=(
                            f"gregraph unlink {entry.source} {entry.type} "
                            f"{entry.target}"
                        ),
                    )
                )
        elif entry.state == "outdated" and not (
            entry.link_target_version > entry.effective
        ):
            findings.append(
                Finding(
                    code="W-LINK-OUTDATED",
                    severity="W",
                    subject=entry.source,
                    message=(
                        f"link {entry.type} → {entry.target}: target_version "
                        f"{entry.link_target_version} is below the target's "
                        f"version {entry.target_version}"
                    ),
                    fix=f"gregraph link refresh {entry.source} {entry.target}",
                )
            )
        elif entry.state == "pending-outdated":
            if (
                entry.link_target_version == entry.effective
                and entry.effective > entry.target_version
            ):
                findings.append(
                    Finding(
                        code="W-LINK-PENDING",
                        severity="W",
                        subject=entry.source,
                        message=(
                            f"link {entry.type} → {entry.target}: target_version "
                            f"{entry.link_target_version} matches target's "
                            "pending version; target has unbumped modifications"
                        ),
                        fix="gregraph sync --bump",
                    )
                )
            else:
                findings.append(
                    Finding(
                        code="W-LINK-PENDING",
                        severity="W",
                        subject=entry.source,
                        message=(
                            f"link {entry.type} → {entry.target}: target has "
                            "unbumped modifications; the link will become "
                            "outdated on the next commit"
                        ),
                        fix=f"gregraph link refresh {entry.source} {entry.target}",
                    )
                )
    deduped: dict[tuple[str, str, str], Finding] = {}
    for finding in findings:
        key = (finding.code, str(finding.subject), finding.message)
        deduped.setdefault(key, finding)
    return ContextResult(
        requested=tuple(requested),
        depth=depth,
        direction=direction,
        targets=tuple(targets),
        neighbors=tuple(neighbors),
        terms=tuple(terms),
        findings=tuple(deduped.values()),
    )


@dataclass(frozen=True, slots=True)
class RepairAgentsResult:
    """Result of :func:`repair_agents` (AGENT_READINESS §7.3, AGENT-033)."""

    agents_files: tuple[Path, ...]
    changed: tuple[Path, ...]
    findings: tuple[Finding, ...] = ()
    notices: tuple[str, ...] = ()


def repair_agents(workspace: Workspace) -> RepairAgentsResult:
    """Regenerate ``AGENTS.md`` and ``SKILL.md`` (AGENT_READINESS §7.3).

    The managed block is replaced in place and ``SKILL.md`` is rewritten when
    its content differs; only changed files are written. Refuses nothing
    except a missing repository (the caller's exit-3 concern).
    """
    return RepairAgentsResult(
        agents_files=agents.AGENTS_FILES, changed=agents.refresh(workspace.root)
    )


# --- hooks (spec §12.3, §13.22) -------------------------------------------
#
# ``hooks install/uninstall/status`` wrap :mod:`gregraph.core.hooks` and
# refuse ``E-GIT-UNAVAILABLE`` outside a repository (writing ``.git/hooks``
# into a non-repository would create a bogus ``.git`` directory).
# ``hook_pre_commit`` implements the §7.5 reconcile pass for the hook: scope =
# staged ``.md`` files under the managed directories plus documents whose
# staged assets or sidecars changed; ``mode = bump``. Bodies and asset bytes
# are hashed from the Git index (the content being committed — §7.2 "the
# increment happens in the pre-commit hook for staged files"), falling back to
# the working tree for paths not in the index. The freshness table is computed
# over the working tree (as ``check`` does, §13.8), and a link is *newly*
# outdated only when it was not already outdated at ``HEAD`` (§7.1
# refinement 2). Blocking (spec §7.5, §11.1, §9.3): validation errors,
# newly outdated links under ``versioning.on_outdated_links = "block"``,
# open conflicts under ``graph.open_conflicts = "block"`` on the baseline
# branch, and ``W-CR-MODIFIED-AFTER-DECISION`` under
# ``versioning.on_cr_modified = "block"``. Warnings never abort; drift and
# scope-target changes never abort (BOOT-128, BOOT-303).


@dataclass(frozen=True, slots=True)
class HookPreCommitResult:
    """Report of :func:`hook_pre_commit` (spec §7.5 step 5, §13.22).

    ``refresh_commands`` are the exact ``gregraph link refresh …`` commands
    resolving each newly outdated link; ``blocked``/``block_reasons`` carry
    the abort decision of §7.5.
    """

    bumped: tuple[str, ...] = ()
    initialised: tuple[str, ...] = ()
    newly_outdated: tuple[versioning.Freshness, ...] = ()
    previously_outdated: tuple[versioning.Freshness, ...] = ()
    stale: tuple[versioning.Freshness, ...] = ()
    pending: tuple[versioning.Freshness, ...] = ()
    findings: tuple[Finding, ...] = ()
    refresh_commands: tuple[str, ...] = ()
    blocked: bool = False
    block_reasons: tuple[str, ...] = ()
    notices: tuple[str, ...] = ()


def _hook_git_unavailable(what: str) -> OperationRefused:
    return OperationRefused(
        Finding(
            code="E-GIT-UNAVAILABLE",
            severity="E",
            subject=what,
            message=f"{what} needs a git repository",
            fix="git init",
        )
    )


def hooks_install(workspace: Workspace) -> hooks.HookStatus:
    """§13.22 ``hooks install`` (§12.3): write/refresh ``.git/hooks/pre-commit``.

    The hook block is appended to an existing hook or created fresh; the
    interpreter recorded is the one running the command. Refuses outside a
    Git repository (``E-GIT-UNAVAILABLE``).
    """
    git = workspace.git
    if not git.is_repo():
        raise _hook_git_unavailable("hooks install")
    root = git.root()
    hooks.install(root)
    return hooks.status(root)


def hooks_uninstall(workspace: Workspace) -> hooks.HookStatus:
    """§13.22 ``hooks uninstall`` (§12.3): remove the gregraph hook block.

    Foreign hook content is preserved; a hook left with nothing but its
    shebang is deleted. Refuses outside a Git repository.
    """
    git = workspace.git
    if not git.is_repo():
        raise _hook_git_unavailable("hooks uninstall")
    root = git.root()
    hooks.uninstall(root)
    return hooks.status(root)


def hooks_status(workspace: Workspace) -> hooks.HookStatus:
    """§13.22 ``hooks status`` (§12.3): installed? up to date?"""
    git = workspace.git
    if not git.is_repo():
        return hooks.HookStatus(installed=False, up_to_date=False)
    return hooks.status(git.root())


def _hook_staged_scope(
    workspace: Workspace,
) -> tuple[set[str], set[str], set[str]]:
    """Scope of the hook pass from the staged paths (spec §7.5).

    Staged ``.md``/``.json`` under ``documents/``, ``changes/``, ``glossary/``
    select that entity (ID/slug = filename stem) and any staged file under
    ``assets/<ID>/`` selects the owning document.
    """
    documents: set[str] = set()
    changes_ids: set[str] = set()
    terms: set[str] = set()
    for path in workspace.git.staged_paths():
        parts = path.parts
        if len(parts) < 2:
            continue
        top = parts[0]
        if top == ASSETS_DIR.as_posix():
            documents.add(parts[1])
        elif top == DOCUMENTS_DIR.as_posix() and path.suffix in (".md", ".json"):
            documents.add(path.stem)
        elif top == CHANGES_DIR.as_posix() and path.suffix in (".md", ".json"):
            changes_ids.add(path.stem)
        elif top == GLOSSARY_DIR.as_posix() and path.suffix in (".md", ".json"):
            terms.add(path.stem)
    return documents, changes_ids, terms


def _hook_body_text(workspace: Workspace, rel: Path) -> str | None:
    """Body text being committed: the index blob, else the working-tree file."""
    data = workspace.git.file_at("", rel)
    if data is not None:
        return data.decode("utf-8")
    try:
        return read_body(workspace.root / rel)
    except OSError:
        return None


def _hook_assets(
    workspace: Workspace, body_rel: Path, text: str, doc_id: str
) -> list[AssetRef]:
    """Stored asset references of one body (spec §5.7) over the index blobs.

    Same shape as :func:`_compute_assets` (paths relative to ``assets/<ID>/``,
    raw-byte SHA-256) but hashing the staged bytes when the file is in the
    index so the committed sidecar matches the committed asset.
    """
    assets: list[AssetRef] = []
    for ref in find_asset_refs(text, doc_path=body_rel, doc_id=doc_id):
        if ref.foreign:
            continue
        data = workspace.git.file_at("", ref.path)
        if data is None:
            file = workspace.root / ref.path
            if not file.is_file():
                continue
            data = file.read_bytes()
        assets.append(
            AssetRef(path=str(Path(*ref.path.parts[2:])), hash=asset_hash(data))
        )
    return assets


def _hook_bump(
    workspace: Workspace, documents: set[str], change_ids: set[str], terms: set[str]
) -> tuple[list[str], list[str]]:
    """Bump every scoped entity whose committed content changed (spec §7.5).

    Returns ``(bumped, initialised)``. Entities in the initial-grace state —
    ``version == 1`` and absent from Git ``HEAD`` (§3.3, AGENT-011) — are
    *populated* instead: ``version`` stays ``1``, the recomputed hashes are
    stored in place, and the ID lands in ``initialised``. Everything else is
    bumped by exactly one version. Sidecars are rewritten in canonical form
    and staged so they travel with the commit (§7.5 step 2). Entities whose
    sidecars cannot be parsed are skipped — validation reports the error and
    the hook blocks on it. Degraded mode never reaches this pass
    (``hook_pre_commit`` refuses without Git), so the grace predicate's
    ``is_repo()`` check is satisfied by construction.
    """
    bumped: list[str] = []
    initialised: list[str] = []
    root = workspace.root
    for doc_id in sorted(documents):
        doc_loaded = workspace.index.documents.get(doc_id)
        if doc_loaded is None:
            continue
        try:
            sidecar = read_sidecar(root / doc_loaded.sidecar, Document)
        except (OSError, ValueError):
            continue
        text = _hook_body_text(workspace, doc_loaded.body)
        if text is None:
            continue
        new_hash = body_hash(text)
        new_assets = _hook_assets(workspace, doc_loaded.body, text, doc_id)
        title = extract_title(text)
        if title is not None and sidecar.title != title:
            sidecar.title = title
        stored_assets = sorted((asset.path, asset.hash) for asset in sidecar.assets)
        current_assets = sorted((asset.path, asset.hash) for asset in new_assets)
        if new_hash == sidecar.body_hash and stored_assets == current_assets:
            continue
        if sidecar.version == 1 and (
            workspace.git.file_at("HEAD", doc_loaded.body) is None
        ):
            sidecar.body_hash = new_hash
            sidecar.assets = new_assets
            write_sidecar(root / doc_loaded.sidecar, sidecar)
            workspace.git.stage([doc_loaded.sidecar])
            initialised.append(sidecar.id)
            continue
        sidecar.version += 1
        sidecar.body_hash = new_hash
        sidecar.assets = new_assets
        write_sidecar(root / doc_loaded.sidecar, sidecar)
        workspace.git.stage([doc_loaded.sidecar])
        bumped.append(sidecar.id)
    for cr_id in sorted(change_ids):
        cr_loaded = workspace.index.changes.get(cr_id)
        if cr_loaded is None:
            continue
        try:
            request = read_sidecar(root / cr_loaded.sidecar, ChangeRequest)
        except (OSError, ValueError):
            continue
        text = _hook_body_text(workspace, cr_loaded.body)
        if text is None:
            continue
        new_hash = body_hash(text)
        new_scope_hash = changes.scope_hash(request.scope)
        title = extract_title(text)
        if title is not None and request.title != title:
            request.title = title
        if new_hash == request.body_hash and new_scope_hash == request.scope_hash:
            continue
        if request.version == 1 and (
            workspace.git.file_at("HEAD", cr_loaded.body) is None
        ):
            request.body_hash = new_hash
            request.scope_hash = new_scope_hash
            write_sidecar(root / cr_loaded.sidecar, request)
            workspace.git.stage([cr_loaded.sidecar])
            initialised.append(request.id)
            continue
        request.version += 1
        request.body_hash = new_hash
        request.scope_hash = new_scope_hash
        write_sidecar(root / cr_loaded.sidecar, request)
        workspace.git.stage([cr_loaded.sidecar])
        bumped.append(request.id)
    for slug in sorted(terms):
        term_loaded = workspace.index.terms.get(slug)
        if term_loaded is None:
            continue
        try:
            term = read_sidecar(root / term_loaded.sidecar, Term)
        except (OSError, ValueError):
            continue
        text = _hook_body_text(workspace, term_loaded.body)
        if text is None:
            continue
        new_hash = body_hash(text)
        if new_hash == term.body_hash:
            continue
        if term.version == 1 and (
            workspace.git.file_at("HEAD", term_loaded.body) is None
        ):
            term.body_hash = new_hash
            write_sidecar(root / term_loaded.sidecar, term)
            workspace.git.stage([term_loaded.sidecar])
            initialised.append(term.slug)
            continue
        term.version += 1
        term.body_hash = new_hash
        write_sidecar(root / term_loaded.sidecar, term)
        workspace.git.stage([term_loaded.sidecar])
        bumped.append(term.slug)
    return bumped, initialised


def _hook_head_version(
    workspace: Workspace, doc_id: str, cache: dict[str, int]
) -> int | None:
    """``version`` of ``doc_id`` at ``HEAD``, or ``None`` when absent there.

    The commit-in-progress view of §7.1 refinement 2: a link is *newly*
    outdated when the commit in progress makes it so — it was not already
    outdated in the committed state.
    """
    if doc_id in cache:
        return cache[doc_id] if cache[doc_id] >= 0 else None
    loaded = workspace.index.documents.get(doc_id)
    value: int | None = None
    if loaded is not None:
        data = workspace.git.file_at("HEAD", loaded.sidecar)
        if data is not None:
            try:
                value = int(json.loads(data.decode("utf-8")).get("version"))
            except (ValueError, TypeError, AttributeError):
                value = None
    cache[doc_id] = -1 if value is None else value
    return value


def hook_pre_commit(workspace: Workspace) -> HookPreCommitResult:
    """``hook pre-commit`` (§7.5, hidden command): reconcile staged scope.

    Bumps versions for the staged content (mode ``bump``), computes the link
    freshness table over the whole graph and runs validation, then returns
    the §7.5 report plus the abort decision: any validation error blocks;
    newly outdated links block when ``versioning.on_outdated_links`` is
    ``block``; ``W-CONFLICT-OPEN`` blocks when ``graph.open_conflicts`` is
    ``block`` and the current branch is the baseline branch;
    ``W-CR-MODIFIED-AFTER-DECISION`` blocks when ``versioning.on_cr_modified``
    is ``block``. A link is *newly* outdated when it was not already outdated
    at ``HEAD`` (§7.1 refinement 2: links already outdated before this commit
    are reported but never block). Warnings never abort, and drift or
    scope-target changes never abort (BOOT-128, BOOT-303).
    """
    git = workspace.git
    if not git.is_repo():
        return HookPreCommitResult(
            notices=("not a git repository — nothing to reconcile",)
        )
    documents, change_ids, terms = _hook_staged_scope(workspace)
    bumped, initialised = _hook_bump(workspace, documents, change_ids, terms)
    if bumped or initialised:
        workspace.reload()
    after = _link_freshness(workspace)
    head_versions: dict[str, int] = {}
    newly: list[versioning.Freshness] = []
    previous: list[versioning.Freshness] = []
    for entry in after.outdated:
        head = _hook_head_version(workspace, entry.target, head_versions)
        if head is not None and entry.link_target_version < head:
            previous.append(entry)
        else:
            newly.append(entry)
    findings = tuple(validate_workspace(workspace))
    refresh_commands = tuple(
        f"gregraph link refresh {entry.source} {entry.type} {entry.target}"
        for entry in newly
    )
    reasons: list[str] = []
    errors = [finding for finding in findings if finding.severity == "E"]
    if errors:
        reasons.append(f"{len(errors)} validation error(s)")
    if newly and workspace.config.versioning.on_outdated_links == "block":
        reasons.append(f"{len(newly)} link(s) newly outdated by this commit")
    if (
        workspace.config.graph.open_conflicts == "block"
        and git.current_branch() == workspace.config.git.baseline_branch
        and any(finding.code == "W-CONFLICT-OPEN" for finding in findings)
    ):
        reasons.append("open conflicts on the baseline branch")
    if workspace.config.versioning.on_cr_modified == "block" and any(
        finding.code == "W-CR-MODIFIED-AFTER-DECISION" for finding in findings
    ):
        reasons.append("change request modified after its last decision")
    return HookPreCommitResult(
        bumped=tuple(bumped),
        initialised=tuple(initialised),
        newly_outdated=tuple(newly),
        previously_outdated=tuple(previous),
        stale=tuple(after.stale),
        pending=tuple(after.pending),
        findings=findings,
        refresh_commands=refresh_commands,
        blocked=bool(reasons),
        block_reasons=tuple(reasons),
    )
