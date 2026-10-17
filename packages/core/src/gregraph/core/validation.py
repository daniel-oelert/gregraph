"""Findings catalogue and checks (spec §14, §16.1).

Findings are data (``code, severity, subject, message, fix``), never exceptions
(spec §16.2). This module is the single entry point for ``validate``: it
composes the load findings of :mod:`gregraph.core.workspace` and the graph
findings of :mod:`gregraph.core.graph`, and implements the structural,
document-side, relational and asset codes of spec §14 — files, IDs (§4.3–4.4),
types (§5.3), body conventions (§5.2), templates and sections (§5.5),
serialisation hygiene (§5.2/§5.4), the Git-identity warning (§12.2), the
graph/link rules (§6, §7.4, §7.6, §8), mentions (§5.2), assets (§5.7) and
open conflicts (§11.1).

Layout (extension structure for S11):

- ``CODE_SEVERITIES`` — the §14 code registry (code → severity); the collector
  derives severity from it, so codes are registered exactly once.
- ``FindingCollector`` — the collector; ``add`` for checks, ``extend`` to
  compose pre-built findings (load/graph layers). Suggested commands are
  attached where the spec names one (``fix``).
- ``ValidationContext`` — workspace plus repository templates, with a small
  raw-bytes cache so bodies are read once per run (§16.6).
- one ``check_*`` function per area, each documenting its codes; structural
  checks are registered in ``STRUCTURAL_CHECKS``, relational/asset checks in
  ``RELATIONAL_CHECKS`` (compose ``Graph.validation_findings()``,
  ``versioning.freshness_table`` and ``status.open_conflicts``; link-type,
  link-target, mention, asset and orphan checks implemented here).
- :func:`validate_workspace` runs every registered check and returns the
  sorted report; :func:`report_payload` maps it to the ``validate --json``
  shape ``[{code, severity, id|path, message, fix?}]`` (spec §14).
- :func:`refresh_cache` computes the updated ``types_seen``/``templates_seen``
  cache maps (spec §16.5) for the caller to persist with
  :func:`gregraph.core.storage.write_cache`; disagreements that back
  ``E-TYPE-KIND-CHANGED``/``E-TEMPLATE-MUTATED`` are kept until fixed so the
  findings persist across runs.
- :func:`aggregate_severity` / :func:`has_errors` implement the ``--strict``
  aggregation the CLI needs (warnings promoted to errors) without duplicating
  exit-code logic (spec §13.9).

``core`` never imports ``cli`` and never prints — this module returns data.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from gregraph.core import changes
from gregraph.core.config import Config
from gregraph.core.hashing import asset_hash, body_hash, effective_content_changed
from gregraph.core.ids import derive_id, split_id
from gregraph.core.markdown import (
    extract_title,
    find_asset_refs,
    find_mentions,
    find_section,
    has_front_matter,
    heading_matches,
    parse_sections,
    section_is_empty,
)
from gregraph.core.models import (
    ChangeRequest,
    Document,
    Finding,
    Link,
    Severity,
    TemplateRef,
)
from gregraph.core.rules import DIRECTED_EDGE_TYPES, EDGE_RULES
from gregraph.core.status import open_conflicts
from gregraph.core.storage import (
    ASSETS_DIR,
    CONFIG_RELPATH,
    TEMPLATES_RELPATH,
    CacheIndex,
    canonical_json_bytes,
    iter_documents,
    templates_dir,
)
from gregraph.core.templates import LoadedTemplate, load_template_dir, sections_hash
from gregraph.core.versioning import freshness_table
from gregraph.core.workspace import Workspace

__all__ = [
    "CODE_SEVERITIES",
    "CR_CHECKS",
    "FindingCollector",
    "TERM_CHECKS",
    "ValidationContext",
    "aggregate_severity",
    "build_context",
    "has_errors",
    "refresh_cache",
    "report_payload",
    "validate_workspace",
]


# --------------------------------------------------------------------------
# code registry (spec §14)
# --------------------------------------------------------------------------

#: The full §14 catalogue: code → severity. Checks register codes here once;
#: the collector refuses unknown codes. Entries for codes implemented by
#: S11–S14 (relational, asset, CR, term) are listed so every finding in the
#: system validates against one table.
CODE_SEVERITIES: Final[dict[str, Severity]] = {
    "E-SIDECAR-MISSING": "E",
    "E-BODY-MISSING": "E",
    "E-SIDECAR-INVALID": "E",
    "E-ID-FILENAME": "E",
    "E-ID-DERIVATION": "E",
    "E-ID-DUPLICATE": "E",
    "E-UUID-DUPLICATE": "E",
    "E-TYPE-UNKNOWN": "E",
    "E-TYPE-KIND-CHANGED": "E",
    "E-TITLE-MISSING": "E",
    "E-FRONTMATTER-FORBIDDEN": "E",
    "E-TEMPLATE-UNKNOWN": "E",
    "E-TEMPLATE-MUTATED": "E",
    "E-SECTION-REQUIRED-MISSING": "E",
    "E-SECTION-REQUIRED-EMPTY": "E",
    "W-SECTION-UNKNOWN": "W",
    "W-SECTION-ORDER": "W",
    "E-LINK-TARGET-MISSING": "E",
    "E-LINK-TYPE-UNKNOWN": "E",
    "E-EDGE-RULE": "E",
    "E-EDGE-EXCLUSIVE": "E",
    "E-CYCLE": "E",
    "E-LINK-VERSION-AHEAD": "E",
    "W-LINK-OUTDATED": "W",
    "W-LINK-STALE": "W",
    "W-LINK-PENDING": "W",
    "W-ORPHAN": "W",
    "W-MENTION-UNLINKED": "W",
    "E-MENTION-UNKNOWN": "E",
    "E-ASSET-MISSING": "E",
    "E-ASSET-FOREIGN": "E",
    "W-ASSET-ORPHAN": "W",
    "W-ASSET-LARGE": "W",
    "E-ASSET-OWNERLESS": "E",
    "W-TEMPLATE-DEPRECATED": "W",
    "W-CONFLICT-OPEN": "W",
    "E-TARGET-SUPERSEDED": "E",
    "E-TARGET-DEPRECATED": "E",
    "E-CR-DISABLED": "E",
    "E-CR-STATUS": "E",
    "E-CR-SCOPE-TARGET": "E",
    "E-CR-CLOSED": "E",
    "E-CR-ORIGIN-MISSING": "E",
    "E-CR-ORIGIN-MISMATCH": "E",
    "W-CR-MODIFIED-AFTER-DECISION": "W",
    "W-CR-DECIDER-UNKNOWN": "W",
    "W-CR-BASE-DRIFT": "W",
    "W-CR-IMPLEMENTED-UNCHANGED": "W",
    "W-CR-MENTION-UNSCOPED": "W",
    "E-TERM-SLUG": "E",
    "E-TERM-ALIAS-CLASH": "E",
    "W-LINE-ENDINGS": "W",
    "W-SIDECAR-NONCANONICAL": "W",
    "W-NO-GIT-IDENTITY": "W",
    "W-PREFIX-MISMATCH": "W",
}

#: Static suggested commands for composed findings that cannot name a concrete
#: path themselves (spec §4.4: ``E-ID-DUPLICATE`` is resolved with
#: ``gregraph repair regenerate-id``). Checks set concrete ``fix`` values where
#: they can; this map fills the rest in :meth:`FindingCollector.result`.
FIX_SUGGESTIONS: Final[dict[str, str]] = {
    "E-ID-DUPLICATE": "gregraph repair regenerate-id <PATH>",
}


# --------------------------------------------------------------------------
# collector and context
# --------------------------------------------------------------------------


class FindingCollector:
    """Collects findings, deriving severity from :data:`CODE_SEVERITIES`."""

    def __init__(self) -> None:
        self._findings: list[Finding] = []

    def add(
        self, code: str, subject: str | Path, message: str, fix: str | None = None
    ) -> None:
        """Record one finding; ``code`` must be registered (spec §14)."""
        severity = CODE_SEVERITIES.get(code)
        if severity is None:
            raise ValueError(f"unknown validation code: {code!r}")
        self._findings.append(
            Finding(
                code=code, severity=severity, subject=subject, message=message, fix=fix
            )
        )

    def extend(self, findings: Iterable[Finding]) -> None:
        """Compose pre-built findings (load layer, later the graph layer)."""
        self._findings.extend(findings)

    def result(self) -> list[Finding]:
        """Sorted report with suggested commands filled in where known."""
        decorated = [_with_suggested_fix(item) for item in self._findings]
        return sorted(
            decorated, key=lambda item: (item.code, str(item.subject), item.message)
        )


def _with_suggested_fix(finding: Finding) -> Finding:
    if finding.fix is not None:
        return finding
    suggestion = FIX_SUGGESTIONS.get(finding.code)
    if suggestion is None:
        return finding
    return finding.model_copy(update={"fix": suggestion})


@dataclass
class ValidationContext:
    """Workspace plus repository templates and a raw-bytes read cache (§16.6)."""

    workspace: Workspace
    templates: dict[str, list[LoadedTemplate]]
    _raw: dict[Path, bytes | None] = field(default_factory=dict, repr=False)

    def raw_bytes(self, rel: Path) -> bytes | None:
        """Raw file contents for a repository-relative path, ``None`` if absent."""
        if rel not in self._raw:
            try:
                self._raw[rel] = (self.workspace.root / rel).read_bytes()
            except OSError:
                self._raw[rel] = None
        return self._raw[rel]


def build_context(workspace: Workspace) -> ValidationContext:
    """Load the repository templates and build the validation context.

    A corrupt template tree (version gap, unreadable ``template.json``) raises
    like a corrupt ``config.toml`` would — an environment error for the CLI to
    map, not a finding (spec §5.5 has no catalogue code for it).
    """
    return ValidationContext(
        workspace=workspace,
        templates=load_template_dir(templates_dir(workspace.root)),
    )


Check = Callable[[ValidationContext, FindingCollector], None]


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def _id_entities(
    ctx: ValidationContext,
) -> list[tuple[Document | ChangeRequest, Path, Path]]:
    """Documents and change requests — one ID space (spec §2) — sorted by path.

    Yields ``(model, body_rel, sidecar_rel)``.
    """
    entries: list[tuple[Document | ChangeRequest, Path, Path]] = [
        (loaded.model, loaded.body, loaded.sidecar)
        for loaded in ctx.workspace.index.documents.values()
    ]
    entries.extend(
        (loaded.model, loaded.body, loaded.sidecar)
        for loaded in ctx.workspace.index.changes.values()
    )
    return sorted(entries, key=lambda item: item[2].as_posix())


def _resolve_pin(
    templates: Mapping[str, Sequence[LoadedTemplate]], ref: TemplateRef
) -> LoadedTemplate | None:
    for candidate in templates.get(ref.name, ()):
        if candidate.version == ref.version:
            return candidate
    return None


def _is_unfilled(content: str, placeholder: str) -> bool:
    """Whether ``content`` is empty or only the section placeholder (§5.5).

    Skeletons write the descriptor placeholder wrapped in emphasis (``*…*``,
    appendix B.2), so the bare, italic and bold spellings all count as
    untouched (see docs/backlog.md on ``section_is_empty``).
    """
    if section_is_empty(content, placeholder):
        return True
    stripped = placeholder.strip()
    if not stripped:
        return False
    return section_is_empty(content, f"*{stripped}*") or section_is_empty(
        content, f"**{stripped}**"
    )


# --------------------------------------------------------------------------
# structural checks (S10)
# --------------------------------------------------------------------------


def check_load_findings(ctx: ValidationContext, out: FindingCollector) -> None:
    """Compose the load-layer findings (spec §14 load subset).

    Codes: ``E-SIDECAR-MISSING``, ``E-BODY-MISSING``, ``E-SIDECAR-INVALID``,
    ``E-ID-DUPLICATE`` — reported by ``workspace.load_index`` and reused here
    unchanged (no duplicated checks).
    """
    out.extend(ctx.workspace.index.findings)


def check_identifiers(ctx: ValidationContext, out: FindingCollector) -> None:
    """Identifier invariants over the shared document/CR ID space (§4.3–4.4).

    Codes: ``E-ID-FILENAME``, ``E-ID-DERIVATION``, ``E-UUID-DUPLICATE``,
    ``W-PREFIX-MISMATCH``. ``E-ID-DERIVATION`` follows §4.3/§14 literally: the
    ID must derive from the UUID with the *configured* prefix, so a prefix
    mismatch fails derivation *and* additionally warns ``W-PREFIX-MISMATCH``.
    """
    prefix = ctx.workspace.config.ids.prefix
    seen_uuids: dict[UUID, tuple[str, Path]] = {}
    for model, body_rel, sidecar_rel in _id_entities(ctx):
        stem = body_rel.stem
        if model.id != stem:
            out.add(
                "E-ID-FILENAME",
                sidecar_rel,
                f"id {model.id!r} does not match filename stem {stem!r}",
            )
        expected = derive_id(model.uuid, prefix)
        if model.id != expected:
            out.add(
                "E-ID-DERIVATION",
                model.id,
                f"id {model.id!r} is not derivable from uuid {model.uuid} "
                f"with prefix {prefix!r} (expected {expected})",
                fix=f"gregraph repair regenerate-id {sidecar_rel.as_posix()}",
            )
        parts = split_id(model.id)
        if parts is not None and parts[0] != prefix:
            out.add(
                "W-PREFIX-MISMATCH",
                model.id,
                f"prefix {parts[0]!r} does not match configured prefix {prefix!r}",
            )
        prior = seen_uuids.get(model.uuid)
        if prior is not None:
            prior_id, prior_sidecar = prior
            out.add(
                "E-UUID-DUPLICATE",
                model.id,
                f"uuid {model.uuid} already used by {prior_id} "
                f"({prior_sidecar.as_posix()})",
                fix=f"gregraph repair regenerate-id {sidecar_rel.as_posix()}",
            )
        else:
            seen_uuids[model.uuid] = (model.id, sidecar_rel)


def check_types(ctx: ValidationContext, out: FindingCollector) -> None:
    """Type existence and kind immutability (spec §5.3, §16.5).

    Codes: ``E-TYPE-UNKNOWN``, ``E-TYPE-KIND-CHANGED``. The kind check compares
    ``config.toml`` against ``cache.types_seen`` (the kind seen at last run)
    and only fires while documents of the type exist — a kind change with no
    documents is free (§5.3).
    """
    config = ctx.workspace.config
    counts: dict[str, int] = {}
    for doc_id, loaded in sorted(ctx.workspace.index.documents.items()):
        doc = loaded.model
        if doc.type not in config.types:
            out.add(
                "E-TYPE-UNKNOWN",
                doc_id,
                f"type {doc.type!r} is not defined in config.toml",
            )
        counts[doc.type] = counts.get(doc.type, 0) + 1
    seen = ctx.workspace.cache.types_seen
    for name, count in sorted(counts.items()):
        spec = config.types.get(name)
        if spec is None:
            continue
        previous = seen.get(name)
        if previous is not None and previous != spec.kind:
            out.add(
                "E-TYPE-KIND-CHANGED",
                CONFIG_RELPATH,
                f"type {name!r} kind changed from {previous!r} to {spec.kind!r} "
                f"while {count} document(s) exist",
            )


def check_document_bodies(ctx: ValidationContext, out: FindingCollector) -> None:
    """Markdown conventions of document bodies (spec §5.2).

    Codes: ``E-TITLE-MISSING``, ``E-FRONTMATTER-FORBIDDEN``.
    """
    for doc_id, loaded in sorted(ctx.workspace.index.documents.items()):
        raw = ctx.raw_bytes(loaded.body)
        if raw is None:
            continue
        if extract_title(raw) is None:
            out.add(
                "E-TITLE-MISSING",
                doc_id,
                "no H1 title as the first non-blank line",
                fix=f"gregraph edit {doc_id}",
            )
        if has_front_matter(raw):
            out.add(
                "E-FRONTMATTER-FORBIDDEN",
                doc_id,
                "body starts with '---'; YAML front matter is forbidden",
                fix=f"gregraph edit {doc_id}",
            )


def check_templates(ctx: ValidationContext, out: FindingCollector) -> None:
    """Template pinning against the repository templates (spec §5.5, §16.5).

    Codes: ``E-TEMPLATE-UNKNOWN``, ``E-TEMPLATE-MUTATED``,
    ``W-TEMPLATE-DEPRECATED``. The mutation check compares the pinned version's
    ``sections_hash`` against ``cache.templates_seen`` and only fires while
    documents are pinned to that version (§7.7: the fix is a new version).
    """
    cache = ctx.workspace.cache
    pinned: dict[tuple[str, int], int] = {}
    for doc_id, loaded in sorted(ctx.workspace.index.documents.items()):
        ref = loaded.model.template
        target = _resolve_pin(ctx.templates, ref)
        if target is None:
            out.add(
                "E-TEMPLATE-UNKNOWN",
                doc_id,
                f"template {ref.name!r} v{ref.version} is not in the repository",
                fix="gregraph template list",
            )
            continue
        pinned[(ref.name, ref.version)] = pinned.get((ref.name, ref.version), 0) + 1
        if target.descriptor.deprecated:
            out.add(
                "W-TEMPLATE-DEPRECATED",
                doc_id,
                f"template {ref.name!r} v{ref.version} is deprecated",
                fix=f"gregraph migrate {doc_id}",
            )
    for (name, version), count in sorted(pinned.items()):
        key = f"{name}/v{version}"
        previous = cache.templates_seen.get(key)
        target = _resolve_pin(ctx.templates, TemplateRef(name=name, version=version))
        if previous is None or target is None:
            continue
        current = sections_hash(target.descriptor)
        if previous != current:
            out.add(
                "E-TEMPLATE-MUTATED",
                TEMPLATES_RELPATH / name / f"v{version}" / "template.json",
                f"sections of template {name!r} v{version} changed since last "
                f"seen; {count} document(s) pinned",
                fix=f"gregraph template bump {name}",
            )


def check_sections(ctx: ValidationContext, out: FindingCollector) -> None:
    """Section structure of document bodies against the pinned template (§5.5).

    Codes: ``E-SECTION-REQUIRED-MISSING``, ``E-SECTION-REQUIRED-EMPTY``,
    ``W-SECTION-UNKNOWN``, ``W-SECTION-ORDER``. Required sections must be
    present and filled (beyond the placeholder); unknown level-2 headings warn
    so templates can be extended organically; known sections must appear in
    template order.
    """
    for doc_id, loaded in sorted(ctx.workspace.index.documents.items()):
        ref = loaded.model.template
        target = _resolve_pin(ctx.templates, ref)
        if target is None:
            continue
        raw = ctx.raw_bytes(loaded.body)
        if raw is None:
            continue
        sections = parse_sections(raw)
        descriptor = target.descriptor
        label = f"template {ref.name!r} v{ref.version}"
        for section in descriptor.sections:
            found = find_section(sections, section.heading, section.renamed_from)
            if found is None:
                if section.required:
                    out.add(
                        "E-SECTION-REQUIRED-MISSING",
                        doc_id,
                        f"required section {section.heading!r} is missing ({label})",
                        fix=f"gregraph edit {doc_id}",
                    )
            elif section.required and _is_unfilled(found.content, section.placeholder):
                out.add(
                    "E-SECTION-REQUIRED-EMPTY",
                    doc_id,
                    f"required section {section.heading!r} is empty or "
                    f"placeholder only ({label})",
                    fix=f"gregraph edit {doc_id}",
                )
        matched: list[tuple[str, int]] = []
        for body_section in sections:
            for index, section in enumerate(descriptor.sections):
                if heading_matches(
                    body_section.heading, section.heading, section.renamed_from
                ):
                    matched.append((body_section.heading, index))
                    break
            else:
                out.add(
                    "W-SECTION-UNKNOWN",
                    doc_id,
                    f"section {body_section.heading!r} is not in {label}",
                )
        for (_prev_heading, prev), (heading, cur) in pairwise(matched):
            if cur < prev:
                out.add(
                    "W-SECTION-ORDER",
                    doc_id,
                    f"section {heading!r} is out of template order ({label})",
                )
                break


def check_serialisation(ctx: ValidationContext, out: FindingCollector) -> None:
    """File hygiene of bodies and sidecars (spec §5.2, §5.4).

    Codes: ``W-LINE-ENDINGS`` (CRLF/CR found; ``sync`` fixes),
    ``W-SIDECAR-NONCANONICAL`` (sidecar bytes differ from the canonical JSON
    form; ``sync`` fixes).
    """
    for model, body_rel, sidecar_rel in _id_entities(ctx):
        raw_body = ctx.raw_bytes(body_rel)
        if raw_body is not None and b"\r" in raw_body:
            out.add(
                "W-LINE-ENDINGS",
                body_rel,
                "CR/CRLF line endings found (expected LF)",
                fix="gregraph sync",
            )
        raw_sidecar = ctx.raw_bytes(sidecar_rel)
        if raw_sidecar is not None and raw_sidecar != canonical_json_bytes(model):
            out.add(
                "W-SIDECAR-NONCANONICAL",
                sidecar_rel,
                "sidecar is not in canonical JSON form",
                fix="gregraph sync",
            )


def check_git_identity(ctx: ValidationContext, out: FindingCollector) -> None:
    """Git identity availability (spec §12.2, §14 ``W-NO-GIT-IDENTITY``).

    Warns when the working tree *is* a Git repository but ``user.name``/
    ``user.email`` are unset. Degraded mode (no repository / no ``git``) is
    covered by the §12.1 ``note:`` channel and stays silent here (same
    conservative reading as ``W-BASELINE-MISSING``, docs/backlog.md).
    """
    git = ctx.workspace.git
    if git.is_repo() and git.identity() is None:
        out.add(
            "W-NO-GIT-IDENTITY",
            CONFIG_RELPATH,
            "git user.name/user.email not configured; authorship will be empty",
            fix='git config user.name "…" && git config user.email "…"',
        )


STRUCTURAL_CHECKS: Final[tuple[Check, ...]] = (
    check_load_findings,
    check_identifiers,
    check_types,
    check_document_bodies,
    check_templates,
    check_sections,
    check_serialisation,
    check_git_identity,
)


# --------------------------------------------------------------------------
# relational, link, asset and misc checks (S11)
# --------------------------------------------------------------------------


def check_graph_findings(ctx: ValidationContext, out: FindingCollector) -> None:
    """Compose the whole-graph findings (spec §6, §14).

    Codes: ``E-LINK-TARGET-MISSING``, ``E-EDGE-RULE``, ``E-EDGE-EXCLUSIVE``,
    ``E-CYCLE`` — reported by ``Graph.validation_findings()`` (Kahn, §6.2;
    the cycle message carries the reconstructed path) and reused here
    unchanged (no duplicated checks).
    """
    out.extend(ctx.workspace.graph.validation_findings())


def check_link_types(ctx: ValidationContext, out: FindingCollector) -> None:
    """Edge types of hand-edited sidecars (spec §6.1, §14).

    Code: ``E-LINK-TYPE-UNKNOWN``. ``Link.type`` is a typed literal, so an
    unknown type fails sidecar schema at load time (``E-SIDECAR-INVALID``)
    and is invisible in loaded models; the violation itself is read from the
    raw sidecar JSON — "as found in files edited outside the tool" (§14).
    """
    root = ctx.workspace.root
    known = frozenset(EDGE_RULES)
    for entry in iter_documents(root):
        rel = entry.sidecar.relative_to(root)
        raw = ctx.raw_bytes(rel)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue  # unparsable JSON is E-SIDECAR-INVALID (load layer)
        if not isinstance(data, dict):
            continue
        links = data.get("links")
        if not isinstance(links, list):
            continue
        raw_id = data.get("id")
        subject: str | Path = raw_id if isinstance(raw_id, str) else rel
        for item in links:
            if not isinstance(item, dict):
                continue
            edge_type = item.get("type")
            if isinstance(edge_type, str) and edge_type not in known:
                out.add(
                    "E-LINK-TYPE-UNKNOWN",
                    subject,
                    f"edge type {edge_type!r} is not in the fixed set",
                )


def _unbumped_ids(ctx: ValidationContext) -> set[str]:
    """Document IDs whose working-tree content differs from stored hashes (§7.3).

    The hash-based "modified, unbumped" definition of spec §7.1 refinement 1
    (same rule as ``status._unbumped_modifications``), reading through the
    raw-bytes cache so bodies are hashed once per run (§16.6).
    """
    result: set[str] = set()
    for doc_id, loaded in ctx.workspace.index.documents.items():
        doc = loaded.model
        raw = ctx.raw_bytes(loaded.body)
        if raw is None:
            result.add(doc_id)
            continue
        stored_assets = [(Path(asset.path), asset.hash) for asset in doc.assets]
        current_assets: list[tuple[Path, str]] = []
        for ref in find_asset_refs(raw, doc_path=loaded.body, doc_id=doc_id):
            if ref.foreign:
                continue
            data = ctx.raw_bytes(ref.path)
            if data is not None:
                current_assets.append((Path(*ref.path.parts[2:]), asset_hash(data)))
        if effective_content_changed(
            doc.body_hash,
            stored_assets,
            body_hash(raw),
            current_assets,
        ):
            result.add(doc_id)
    return result


def _grace_ids(ctx: ValidationContext) -> set[str]:
    """Document IDs in the initial-grace state (spec §3.3, AGENT-012).

    A ``v1`` document absent from Git ``HEAD`` — untracked or
    staged-but-uncommitted — is being populated: its effective version stays
    ``1`` and links into it are not pending (§3.3 rules 3–4).  Degraded mode
    has no commit step, hence no grace period (AGENT-014).  A missing body
    file is ``E-BODY-MISSING``, not a grace case.
    """
    if not ctx.workspace.git.is_repo():
        return set()
    result: set[str] = set()
    for doc_id, loaded in ctx.workspace.index.documents.items():
        body = loaded.body
        if (
            loaded.model.version == 1
            and (ctx.workspace.root / body).is_file()
            and ctx.workspace.git.file_at("HEAD", body) is None
        ):
            result.add(doc_id)
    return result


def check_link_freshness(ctx: ValidationContext, out: FindingCollector) -> None:
    """Link freshness of spec §7.4 over the document graph (§3.3, §5.4).

    Codes: ``E-LINK-VERSION-AHEAD``, ``W-LINK-OUTDATED``, ``W-LINK-STALE``,
    ``W-LINK-PENDING``. Composes ``versioning.freshness_table`` and maps its
    states onto codes: stale targets (superseded or deprecated, regardless of
    version) warn on every link except ``supersedes`` (a supersession edge
    *is* the supersession — §7.6 "OLD's inbound links… become stale" refers to
    links that predate it, and ``link refresh --follow`` must not re-point a
    chain onto its own successor); ``target_version > effective_version`` is
    the ``E-LINK-VERSION-AHEAD`` invariant (D-AGENT-7: the *effective*
    version, so a link refreshed to ``version + 1`` against an unbumped
    target is not an error); ``target_version < target.version`` warns
    ``W-LINK-OUTDATED``; a link matching the pending version of an unbumped
    target or fresh against one warns ``W-LINK-PENDING`` (§7.4:
    pending-outdated is a Git-mode state, gated on ``git.is_repo()``), except
    that a target in the initial-grace state (uncommitted ``v1``, §3.3) is
    never pending — a draft being populated is fresh.
    """
    index = ctx.workspace.index
    graph = ctx.workspace.graph
    documents = index.documents
    dead: dict[str, bool] = {
        doc_id: (loaded.model.deprecated is not None or graph.is_superseded(doc_id))
        for doc_id, loaded in documents.items()
    }
    unbumped = {doc_id: True for doc_id in _unbumped_ids(ctx)}
    grace = {doc_id: True for doc_id in _grace_ids(ctx)}
    triples: list[tuple[str, Link, Document | None]] = []
    for doc_id, loaded in sorted(documents.items()):
        for link in loaded.model.links:
            target = documents.get(link.target)
            triples.append((doc_id, link, target.model if target else None))
    table = freshness_table(
        triples,
        deprecated_or_superseded=dead,
        unbumped=unbumped,
        in_grace=grace,
    )
    git_mode = ctx.workspace.git.is_repo()
    for entry in table.entries:
        ahead = entry.link_target_version > entry.effective
        if ahead:
            out.add(
                "E-LINK-VERSION-AHEAD",
                entry.source,
                f"link {entry.type} → {entry.target}: target_version "
                f"{entry.link_target_version} exceeds the target's version "
                f"{entry.target_version}",
                fix="gregraph repair versions",
            )
        refresh = f"gregraph link refresh {entry.source} {entry.target}"
        if entry.state == "stale":
            if entry.type == "supersedes":
                continue
            if graph.is_superseded(entry.target):
                out.add(
                    "W-LINK-STALE",
                    entry.source,
                    f"link {entry.type} → {entry.target}: target is superseded",
                    fix=f"{refresh} --follow",
                )
            else:
                out.add(
                    "W-LINK-STALE",
                    entry.source,
                    f"link {entry.type} → {entry.target}: target is deprecated",
                    fix=f"gregraph unlink {entry.source} {entry.type} {entry.target}",
                )
        elif entry.state == "outdated" and not ahead:
            out.add(
                "W-LINK-OUTDATED",
                entry.source,
                f"link {entry.type} → {entry.target}: target_version "
                f"{entry.link_target_version} is below the target's version "
                f"{entry.target_version}",
                fix=refresh,
            )
        elif (
            entry.link_target_version == entry.effective
            and entry.effective > entry.target_version
        ):
            # §5.4/D-AGENT-7/AGENT-026: the link holds the target's pending
            # version — the state a refresh just created, not a mishap.
            out.add(
                "W-LINK-PENDING",
                entry.source,
                f"link {entry.type} → {entry.target}: target_version "
                f"{entry.link_target_version} matches target's pending "
                "version; target has unbumped modifications",
                fix="gregraph sync --bump",
            )
        elif entry.state == "pending-outdated" and git_mode:
            out.add(
                "W-LINK-PENDING",
                entry.source,
                f"link {entry.type} → {entry.target}: target has unbumped "
                "modifications; the link will become outdated on the next commit",
                fix=refresh,
            )


def check_link_targets(ctx: ValidationContext, out: FindingCollector) -> None:
    """Dead targets of directed edges (spec §7.6, §8, §14).

    Codes: ``E-TARGET-SUPERSEDED``, ``E-TARGET-DEPRECATED`` — the link-time
    refusals "also reported by validate if found in files" (§14): a
    superseded/deprecated document "can no longer be linked as a target of any
    new *directed* edge except ``supersedes``" (§7.6/§8). Only directed
    non-``supersedes`` edges are rule-checked — symmetric edges are not
    directed edges and §11.2 keeps ``conflicts-with`` history on dead
    documents — and ``supersedes`` is the stated exception (chains and forks
    target superseded documents by design). The same edges additionally warn
    ``W-LINK-STALE`` on the §7.4 freshness axis.
    """
    graph = ctx.workspace.graph
    for edge in graph.edges:
        if edge.type not in DIRECTED_EDGE_TYPES or edge.type == "supersedes":
            continue
        if edge.target not in graph.nodes:
            continue  # E-LINK-TARGET-MISSING (composed above)
        if graph.is_superseded(edge.target):
            out.add(
                "E-TARGET-SUPERSEDED",
                edge.source,
                f"target {edge.target} is superseded; only supersedes may target it",
                fix=f"gregraph unlink {edge.source} {edge.type} {edge.target}",
            )
        elif graph.is_deprecated(edge.target):
            out.add(
                "E-TARGET-DEPRECATED",
                edge.source,
                f"target {edge.target} is deprecated; only supersedes may target it",
                fix=f"gregraph unlink {edge.source} {edge.type} {edge.target}",
            )


def check_orphans(ctx: ValidationContext, out: FindingCollector) -> None:
    """Orphan nodes (spec §6.3, §14).

    Code: ``W-ORPHAN``. Composes ``Graph.orphans()``: nodes with no edges of
    any type in either direction, excluding deprecated/superseded nodes (a
    freshly created document is an orphan until linked — a warning, not an
    error).
    """
    for node_id in ctx.workspace.graph.orphans():
        out.add(
            "W-ORPHAN",
            node_id,
            "no edges of any type in either direction",
            fix="gregraph link",
        )


def check_mentions(ctx: ValidationContext, out: FindingCollector) -> None:
    """ID mentions in document bodies (spec §5.2).

    Codes: ``W-MENTION-UNLINKED`` (a mentioned document ID with no edge in
    either direction), ``E-MENTION-UNKNOWN`` (a mentioned ID that is neither a
    document nor a change request). CR IDs are mentionable freely (§5.2) and
    raise neither code; a document's mentions of its own ID are not reported
    either (no self-edge is a legal fix — see docs/backlog.md). Mentions
    inside CR bodies follow §9.7 and are the CR checks' job.
    """
    index = ctx.workspace.index
    graph = ctx.workspace.graph
    for doc_id, loaded in sorted(index.documents.items()):
        raw = ctx.raw_bytes(loaded.body)
        if raw is None:
            continue
        seen: set[str] = set()
        for mention in find_mentions(raw, doc_path=loaded.body):
            other = mention.id
            if other in seen:
                continue
            seen.add(other)
            if other == doc_id:
                continue
            if other in index.changes:
                continue
            if other in index.documents:
                linked = any(
                    edge.source == other or edge.target == other
                    for edge in graph.edges_of(doc_id)
                )
                if linked:
                    continue
                out.add(
                    "W-MENTION-UNLINKED",
                    doc_id,
                    f"mentions {other} with no edge in either direction",
                    fix="gregraph link",
                )
            else:
                out.add(
                    "E-MENTION-UNKNOWN",
                    doc_id,
                    f"mentions {other}, which is neither a document nor a "
                    "change request",
                    fix=f"gregraph edit {doc_id}",
                )


def check_assets(ctx: ValidationContext, out: FindingCollector) -> None:
    """Asset references and asset folders (spec §5.7).

    Codes: ``E-ASSET-MISSING`` (referenced but absent), ``E-ASSET-FOREIGN``
    (reference into another owner's folder — assets are single-owner),
    ``W-ASSET-ORPHAN`` (file in ``assets/<ID>/`` not referenced by the owning
    body), ``W-ASSET-LARGE`` (file over ``assets.max_size_kb``),
    ``E-ASSET-OWNERLESS`` (``assets/<X>/`` where ``X`` is not a document ID).
    Folder ownership matches document IDs case-insensitively (consistent with
    ``markdown.resolve_asset_ref``); files inside an ownerless folder are
    large-checked but not per-file reported — the folder error names the
    problem. A body that cannot be read reports ``E-BODY-MISSING``/load
    findings instead of spurious orphans.
    """
    root = ctx.workspace.root
    index = ctx.workspace.index
    config = ctx.workspace.config
    max_bytes = config.assets.max_size_kb * 1024
    referenced: dict[str, set[Path]] = {}
    for doc_id, loaded in sorted(index.documents.items()):
        raw = ctx.raw_bytes(loaded.body)
        if raw is None:
            continue
        own: set[Path] = set()
        for ref in find_asset_refs(raw, doc_path=loaded.body, doc_id=doc_id):
            if ref.foreign:
                out.add(
                    "E-ASSET-FOREIGN",
                    doc_id,
                    f"reference {ref.raw!r} lands in {ref.owner}'s asset "
                    "folder; assets are single-owner (copy the file)",
                    fix=f"gregraph edit {doc_id}",
                )
            else:
                if not (root / ref.path).is_file():
                    out.add(
                        "E-ASSET-MISSING",
                        doc_id,
                        f"referenced asset {ref.path.as_posix()!r} does not exist",
                        fix=f"gregraph edit {doc_id}",
                    )
                own.add(ref.path)
        referenced[doc_id] = own

    assets_root = root / ASSETS_DIR
    if not assets_root.is_dir():
        return
    owners = {doc_id.upper(): doc_id for doc_id in index.documents}
    for folder in sorted(assets_root.iterdir()):
        if not folder.is_dir():
            continue  # loose files under assets/: no catalogue code
        owner = owners.get(folder.name.upper())
        if owner is None:
            out.add(
                "E-ASSET-OWNERLESS",
                ASSETS_DIR / folder.name,
                f"asset folder {folder.name!r} does not belong to any document ID",
            )
        refs = referenced.get(owner) if owner is not None else None
        for file in sorted(folder.rglob("*")):
            if not file.is_file():
                continue
            rel = file.relative_to(root)
            if file.stat().st_size > max_bytes:
                out.add(
                    "W-ASSET-LARGE",
                    rel,
                    f"asset is larger than {config.assets.max_size_kb} kB",
                )
            if refs is not None and rel not in refs:
                out.add(
                    "W-ASSET-ORPHAN",
                    rel,
                    f"file is not referenced by {owner}",
                    fix=f"gregraph edit {owner}",
                )


def check_open_conflicts(ctx: ValidationContext, out: FindingCollector) -> None:
    """Open conflicts between live nodes (spec §11.1, §14).

    Code: ``W-CONFLICT-OPEN``. Composes ``status.open_conflicts``: one
    warning per ``conflicts-with`` pair whose both endpoints are neither
    deprecated nor superseded. ``graph.open_conflicts = "block"`` is a hook
    policy (§11.1) and does not change the validate severity.
    """
    for low, high in open_conflicts(ctx.workspace.graph):
        out.add(
            "W-CONFLICT-OPEN",
            low,
            f"open conflicts-with between {low} and {high}; both endpoints are live",
        )


RELATIONAL_CHECKS: Final[tuple[Check, ...]] = (
    check_graph_findings,
    check_link_types,
    check_link_freshness,
    check_link_targets,
    check_orphans,
    check_mentions,
    check_assets,
    check_open_conflicts,
)


# --------------------------------------------------------------------------
# change-request checks (S13, spec §9)
# --------------------------------------------------------------------------


def check_change_requests(ctx: ValidationContext, out: FindingCollector) -> None:
    """CR subsystem findings (spec §9, §14) — composed from ``changes.cr_findings``.

    Codes: ``E-CR-STATUS``, ``E-CR-SCOPE-TARGET``, ``E-CR-ORIGIN-MISSING``,
    ``E-CR-ORIGIN-MISMATCH``, ``W-CR-MODIFIED-AFTER-DECISION``,
    ``W-CR-DECIDER-UNKNOWN``, ``W-CR-BASE-DRIFT``,
    ``W-CR-IMPLEMENTED-UNCHANGED``, ``W-CR-MENTION-UNSCOPED``, plus the
    CR-body codes of §9.2/§9.7 (``E-TITLE-MISSING``, ``E-TEMPLATE-*``,
    ``E-SECTION-*``, ``W-SECTION-*``, ``E-MENTION-UNKNOWN``). ``E-CR-DISABLED``
    and ``E-CR-CLOSED`` are refusal codes and are never reported here (§9.1:
    existing CR files are still validated while CRs are disabled). The
    baseline snapshot is loaded lazily and at most once per run (§9.6).
    """
    workspace = ctx.workspace
    if not workspace.index.changes and not any(
        loaded.model.origin_cr for loaded in workspace.index.documents.values()
    ):
        return
    baseline = changes.BaselineView(workspace.git, workspace.config.git.baseline_branch)
    for issue in changes.cr_findings(
        workspace, baseline=baseline, templates=ctx.templates
    ):
        out.add(issue.code, issue.subject, issue.message, issue.fix)


CR_CHECKS: Final[tuple[Check, ...]] = (check_change_requests,)


# --------------------------------------------------------------------------
# glossary checks (S14, spec §10)
# --------------------------------------------------------------------------


def check_terms(ctx: ValidationContext, out: FindingCollector) -> None:
    """Glossary term consistency (spec §10.2, §14).

    Codes: ``E-TERM-SLUG`` — sidecar ``slug`` ≠ filename stem (the slug *is*
    the stem, §10.2), two stems colliding case-insensitively (slug uniqueness;
    slugs are lowercase by construction so a case-variant pair is a duplicate
    on case-insensitive filesystems), or body H1 ≠ ``term`` (missing H1
    included) — and ``E-TERM-ALIAS-CLASH`` — an alias equal to a term name
    (any term, including its own) or to another alias instance, all compared
    case-insensitively (§10.2 "alias uniqueness across terms and against term
    names"). Term names are unique only through their slugs; name-vs-name is
    not validated (no catalogue code). One finding per offending alias.
    """
    index = ctx.workspace.index.terms
    for stem in sorted(index):
        loaded = index[stem]
        model = loaded.model
        if model.slug != stem:
            out.add(
                "E-TERM-SLUG",
                loaded.sidecar,
                f"slug {model.slug!r} does not match filename stem {stem!r}",
            )
        raw = ctx.raw_bytes(loaded.body)
        if raw is not None and extract_title(raw) != model.term:
            out.add(
                "E-TERM-SLUG",
                loaded.body,
                f"H1 title does not equal term {model.term!r}",
            )
        collisions = [
            other
            for other in sorted(index)
            if other != stem and other.casefold() == stem.casefold()
        ]
        if collisions:
            out.add(
                "E-TERM-SLUG",
                loaded.sidecar,
                f"filename stem {stem!r} collides with {collisions[0]!r} "
                f"(slugs are unique)",
            )
    for stem in sorted(index):
        model = index[stem].model
        for position, alias in enumerate(model.aliases):
            key = alias.casefold()
            clashes: list[str] = []
            for other in sorted(index):
                other_model = index[other].model
                if other_model.term and other_model.term.casefold() == key:
                    clashes.append(f"term name {other_model.term!r} of {other!r}")
                for other_position, other_alias in enumerate(other_model.aliases):
                    if (other, other_position) == (stem, position):
                        continue
                    if other_alias and other_alias.casefold() == key:
                        clashes.append(f"alias {other_alias!r} of {other!r}")
            if clashes:
                out.add(
                    "E-TERM-ALIAS-CLASH",
                    index[stem].sidecar,
                    f"alias {alias!r} collides with " + ", ".join(sorted(set(clashes))),
                )


TERM_CHECKS: Final[tuple[Check, ...]] = (check_terms,)

ALL_CHECKS: Final[tuple[Check, ...]] = (
    *STRUCTURAL_CHECKS,
    *RELATIONAL_CHECKS,
    *CR_CHECKS,
    *TERM_CHECKS,
)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def validate_workspace(workspace: Workspace) -> list[Finding]:
    """Run every registered check and return the sorted §14 report.

    Pure read: the ``types_seen``/``templates_seen`` cache is consulted but not
    written — persist the result of :func:`refresh_cache` with
    :func:`gregraph.core.storage.write_cache` after the run (spec §16.5).
    """
    ctx = build_context(workspace)
    out = FindingCollector()
    for check in ALL_CHECKS:
        check(ctx, out)
    return out.result()


# --------------------------------------------------------------------------
# cache refresh (spec §16.5)
# --------------------------------------------------------------------------


def refresh_cache(
    cache: CacheIndex,
    *,
    config: Config,
    documents: Iterable[Document],
    templates: Mapping[str, Sequence[LoadedTemplate]],
) -> CacheIndex:
    """Return ``cache`` with ``types_seen``/``templates_seen`` updated.

    The cache stores "what validate last saw" (spec §16.5): every configured
    type's kind and every repository template version's ``sections_hash`` is
    recorded fresh each run — *except* while a disagreement is still reported
    (``E-TYPE-KIND-CHANGED``/``E-TEMPLATE-MUTATED``): as long as documents of
    the type exist / documents are pinned to the version, the previously seen
    value is kept so the finding persists until fixed. With no documents
    involved a change is free (spec §5.3, §7.7) and the new value is recorded.
    Keys for types/versions that left config/the repository are dropped.
    ``files`` (the body-hash map) is managed by ``sync`` and left untouched.
    """
    docs = list(documents)
    occupied: set[str] = {document.type for document in docs}
    pins: set[tuple[str, int]] = {
        (document.template.name, document.template.version) for document in docs
    }

    types_seen: dict[str, str] = {}
    for name in sorted(config.types):
        spec = config.types[name]
        previous = cache.types_seen.get(name)
        if name in occupied and previous is not None and previous != spec.kind:
            types_seen[name] = previous
        else:
            types_seen[name] = spec.kind

    templates_seen: dict[str, str] = {}
    for name in sorted(templates):
        for loaded in templates[name]:
            key = f"{name}/v{loaded.version}"
            current = sections_hash(loaded.descriptor)
            previous = cache.templates_seen.get(key)
            pinned = (name, loaded.version) in pins
            if pinned and previous is not None and previous != current:
                templates_seen[key] = previous
            else:
                templates_seen[key] = current

    return cache.model_copy(
        update={"types_seen": types_seen, "templates_seen": templates_seen}
    )


# --------------------------------------------------------------------------
# reporting helpers (spec §13.9, §14)
# --------------------------------------------------------------------------


def aggregate_severity(
    findings: Iterable[Finding], *, strict: bool = False
) -> Severity | None:
    """Worst severity in ``findings`` — ``None`` for an empty report.

    ``strict`` implements ``validate --strict`` (spec §13.9): warnings are
    promoted to errors, so callers can decide exit codes from the result alone.
    """
    worst: Severity | None = None
    for finding in findings:
        level: Severity = (
            "E" if strict and finding.severity == "W" else finding.severity
        )
        if level == "E":
            return "E"
        worst = "W"
    return worst


def has_errors(findings: Iterable[Finding], *, strict: bool = False) -> bool:
    """Whether the report should fail the command (spec §13.9 exit code 1)."""
    return aggregate_severity(findings, strict=strict) == "E"


def report_payload(findings: Iterable[Finding]) -> list[dict[str, Any]]:
    """The ``validate --json`` shape: ``[{code, severity, id|path, message, fix?}]``.

    ``id``/``path`` is chosen by the subject type and ``fix`` is omitted when
    there is no suggested command (spec §14, :class:`~gregraph.core.models.Finding`).
    """
    return [finding.model_dump() for finding in findings]
