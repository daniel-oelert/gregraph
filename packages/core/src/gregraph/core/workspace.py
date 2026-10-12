"""Workspace: root discovery, config, index, git adapter (spec §3, §1.5, §16).

Root rule (spec §3): the repository root is the nearest ancestor directory of
the start path containing ``.gregraph/config.toml``. :class:`Workspace` is the
single entry point for all operations; it is constructed once per process and
lazily loads the index (all sidecars in memory, spec §1.5) and the cache
(spec §16.5). The Git adapter defaults to :class:`~gregraph.core.git.NullGitAdapter`
(degraded mode) until the adapter implementation lands.

Index loading materialises content and reports what it cannot:
``E-SIDECAR-MISSING``, ``E-BODY-MISSING``, ``E-SIDECAR-INVALID`` and
``E-ID-DUPLICATE`` (documents and change requests share one ID space, spec §2).
Full validation is the validate layer's job (spec §14). Paths in :class:`Loaded`
are repository-relative (spec §16.2). Never imports ``cli``, never prints.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from gregraph.core.config import Config, read_config
from gregraph.core.git import GitAdapter, NullGitAdapter
from gregraph.core.graph import Graph, build_graph
from gregraph.core.models import ChangeRequest, Document, Finding, Term
from gregraph.core.rules import Kind
from gregraph.core.storage import (
    CacheIndex,
    ManagedFiles,
    config_path,
    iter_changes,
    iter_documents,
    iter_terms,
    load_cache,
    read_sidecar,
)


@dataclass(frozen=True)
class Loaded[M: BaseModel]:
    """One parsed sidecar with its repository-relative paths (spec §3, §16.2)."""

    model: M
    body: Path
    sidecar: Path


@dataclass(frozen=True)
class Index:
    """All sidecars held in memory (spec §1.5).

    ``documents``/``changes`` are keyed by ID (shared ID space, spec §2);
    ``terms`` by filename stem (the slug, spec §3, §10). ``findings`` lists what
    loading could not materialise or had to drop.
    """

    documents: dict[str, Loaded[Document]] = field(default_factory=dict)
    changes: dict[str, Loaded[ChangeRequest]] = field(default_factory=dict)
    terms: dict[str, Loaded[Term]] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()


def find_root(start: Path) -> Path | None:
    """Nearest ancestor of ``start`` (inclusive) with ``.gregraph/config.toml`` (§3)."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if config_path(candidate).is_file():
            return candidate
    return None


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _read_stems[M: BaseModel](
    root: Path,
    files: Iterable[ManagedFiles],
    model: type[M],
) -> tuple[list[tuple[str, M, Path, Path]], list[Finding]]:
    """Parse each managed stem's sidecar; report missing sidecar/body and bad JSON.

    Returns ``(stem, model, body_rel, sidecar_rel)`` rows for every sidecar that
    parsed, plus findings for what could not be loaded (spec §14 load subset).
    """
    loaded: list[tuple[str, M, Path, Path]] = []
    findings: list[Finding] = []
    for entry in files:
        body_rel = entry.body.relative_to(root)
        sidecar_rel = entry.sidecar.relative_to(root)
        if not entry.sidecar.is_file():
            findings.append(
                Finding(
                    code="E-SIDECAR-MISSING",
                    severity="E",
                    subject=body_rel,
                    message=f"{entry.stem}: markdown body without JSON sidecar",
                )
            )
            continue
        if not entry.body.is_file():
            findings.append(
                Finding(
                    code="E-BODY-MISSING",
                    severity="E",
                    subject=sidecar_rel,
                    message=f"{entry.stem}: JSON sidecar without markdown body",
                )
            )
        try:
            parsed = read_sidecar(entry.sidecar, model)
        except (OSError, ValueError) as exc:
            findings.append(
                Finding(
                    code="E-SIDECAR-INVALID",
                    severity="E",
                    subject=sidecar_rel,
                    message=f"{entry.stem}: invalid sidecar ({_first_line(exc)})",
                )
            )
            continue
        loaded.append((entry.stem, parsed, body_rel, sidecar_rel))
    return loaded, findings


def _index_by_id[M: BaseModel](
    rows: list[tuple[str, M, Path, Path]],
    key_of: Callable[[M], str],
    claimed: dict[str, Path],
    findings: list[Finding],
) -> dict[str, Loaded[M]]:
    result: dict[str, Loaded[M]] = {}
    for _stem, model, body_rel, sidecar_rel in rows:
        key = key_of(model)
        if key in claimed:
            findings.append(
                Finding(
                    code="E-ID-DUPLICATE",
                    severity="E",
                    subject=key,
                    message=(
                        f"id {key} already used by {claimed[key]}; "
                        f"ignoring {sidecar_rel}"
                    ),
                )
            )
            continue
        claimed[key] = sidecar_rel
        result[key] = Loaded(model=model, body=body_rel, sidecar=sidecar_rel)
    return result


def load_index(root: Path) -> Index:
    """Load every sidecar under the managed directories into memory (spec §1.5).

    Documents (``documents/**``), change requests (``changes/``) and glossary
    terms (``glossary/``). Documents and CRs share the ID space (spec §2), so a
    duplicate ID across either drops the later one with ``E-ID-DUPLICATE``.
    Terms are keyed by filename stem; slug mismatches are ``E-TERM-SLUG``
    (validate layer). Load order is sorted, so "first" is deterministic.
    """
    findings: list[Finding] = []
    claimed: dict[str, Path] = {}

    document_rows, document_findings = _read_stems(root, iter_documents(root), Document)
    findings.extend(document_findings)
    documents = _index_by_id(document_rows, lambda m: m.id, claimed, findings)

    change_rows, change_findings = _read_stems(root, iter_changes(root), ChangeRequest)
    findings.extend(change_findings)
    changes = _index_by_id(change_rows, lambda m: m.id, claimed, findings)

    term_rows, term_findings = _read_stems(root, iter_terms(root), Term)
    findings.extend(term_findings)
    terms: dict[str, Loaded[Term]] = {
        stem: Loaded(model=model, body=body_rel, sidecar=sidecar_rel)
        for stem, model, body_rel, sidecar_rel in term_rows
    }

    return Index(
        documents=documents,
        changes=changes,
        terms=terms,
        findings=tuple(findings),
    )


class Workspace:
    """Single entry point for all operations (spec §16.1–16.2).

    Holds ``root``, ``config`` and the Git adapter; the index (all sidecars),
    the cache and the graph are loaded lazily and can be re-read with
    :meth:`reload` after files change. No global state.
    """

    def __init__(
        self,
        root: Path,
        config: Config,
        git: GitAdapter | None = None,
    ) -> None:
        self.root = root
        self.config = config
        self.git: GitAdapter = git if git is not None else NullGitAdapter()
        self._index: Index | None = None
        self._cache: CacheIndex | None = None
        self._graph: Graph | None = None

    @classmethod
    def open(
        cls, start: Path | None = None, *, git: GitAdapter | None = None
    ) -> Workspace:
        """Discover the root from ``start`` (default cwd) and load the config.

        Raises ``FileNotFoundError`` when no ancestor carries the root marker
        (spec §3: commands other than ``init`` exit with code 3 — the CLI maps
        this error).
        """
        base = start if start is not None else Path.cwd()
        root = find_root(base)
        if root is None:
            raise FileNotFoundError(
                f"no gregraph repository (no .gregraph/config.toml) at or above {base}"
            )
        return cls(root=root, config=read_config(config_path(root)), git=git)

    @property
    def index(self) -> Index:
        """All sidecars in memory, loaded on first access (spec §1.5)."""
        if self._index is None:
            self._index = load_index(self.root)
        return self._index

    @property
    def cache(self) -> CacheIndex:
        """The rebuildable body-hash cache, loaded on first access (spec §16.5)."""
        if self._cache is None:
            self._cache = load_cache(self.root)
        return self._cache

    @property
    def graph(self) -> Graph:
        """The in-memory graph over the document index (spec §6)."""
        if self._graph is None:
            kinds: dict[str, Kind] = {
                name: spec.kind for name, spec in self.config.types.items()
            }
            self._graph = build_graph(
                (entry.model for entry in self.index.documents.values()), kinds
            )
        return self._graph

    def reload(self) -> None:
        """Drop all lazy loads so the next access re-reads from disk."""
        self._index = None
        self._cache = None
        self._graph = None
