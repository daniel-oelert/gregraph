"""File I/O: paths, canonical JSON, documents, terms, cache (spec §3, §5.4, §16.5).

The only module that turns repository-relative model paths into absolute ones.
Canonical JSON: ``indent=2, ensure_ascii=False, sort_keys=True`` + trailing
newline; links sorted by ``(type, target)``, CR ``scope`` sorted by ``id``,
``introduces`` sorted (spec §5.4, §9.2). Cache: ``.gregraph/cache/index.json``
per §16.5, silently rebuilt on absence or corruption.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gregraph import __version__

GREGRAPH_DIR: Final = Path(".gregraph")
CONFIG_RELPATH: Final = GREGRAPH_DIR / "config.toml"
CACHE_RELPATH: Final = GREGRAPH_DIR / "cache" / "index.json"
TEMPLATES_RELPATH: Final = GREGRAPH_DIR / "templates"
DOCUMENTS_DIR: Final = Path("documents")
CHANGES_DIR: Final = Path("changes")
GLOSSARY_DIR: Final = Path("glossary")
ASSETS_DIR: Final = Path("assets")

_BODY_SUFFIX: Final = ".md"
_SIDECAR_SUFFIX: Final = ".json"


@dataclass(frozen=True)
class ManagedFiles:
    """Body and sidecar paths of one stem in a managed directory (spec §3)."""

    stem: str
    body: Path
    sidecar: Path


def config_path(root: Path) -> Path:
    """Absolute path of the repository configuration file (spec §3)."""
    return root / CONFIG_RELPATH


def cache_path(root: Path) -> Path:
    """Absolute path of the index cache (spec §3, §16.5)."""
    return root / CACHE_RELPATH


def templates_dir(root: Path) -> Path:
    """Absolute path of the repository template directory (spec §5.5)."""
    return root / TEMPLATES_RELPATH


def document_paths(root: Path, folder: str | Path, doc_id: str) -> tuple[Path, Path]:
    """Absolute ``(body, sidecar)`` paths under ``documents/<folder>/``."""
    directory = root / DOCUMENTS_DIR / folder
    body = directory / f"{doc_id}{_BODY_SUFFIX}"
    sidecar = directory / f"{doc_id}{_SIDECAR_SUFFIX}"
    return body, sidecar


def change_paths(root: Path, cr_id: str) -> tuple[Path, Path]:
    """Absolute ``(body, sidecar)`` paths of a change request under ``changes/``."""
    directory = root / CHANGES_DIR
    return directory / f"{cr_id}{_BODY_SUFFIX}", directory / f"{cr_id}{_SIDECAR_SUFFIX}"


def term_paths(root: Path, slug: str) -> tuple[Path, Path]:
    """Absolute ``(body, sidecar)`` paths of a glossary term under ``glossary/``."""
    directory = root / GLOSSARY_DIR
    return directory / f"{slug}{_BODY_SUFFIX}", directory / f"{slug}{_SIDECAR_SUFFIX}"


def assets_dir(root: Path, doc_id: str) -> Path:
    """Absolute path of a document's asset folder ``assets/<ID>/`` (spec §5.7)."""
    return root / ASSETS_DIR / doc_id


def _iter_managed(directory: Path, *, recursive: bool) -> Iterator[ManagedFiles]:
    if not directory.is_dir():
        return
    candidates = directory.rglob("*") if recursive else directory.iterdir()
    stems: set[tuple[Path, str]] = set()
    for path in candidates:
        if path.is_file() and path.suffix in {_BODY_SUFFIX, _SIDECAR_SUFFIX}:
            stems.add((path.parent, path.stem))
    for parent, stem in sorted(stems):
        yield ManagedFiles(
            stem=stem,
            body=parent / f"{stem}{_BODY_SUFFIX}",
            sidecar=parent / f"{stem}{_SIDECAR_SUFFIX}",
        )


def iter_documents(root: Path) -> Iterator[ManagedFiles]:
    """Every stem found under ``documents/**`` (spec §3)."""
    return _iter_managed(root / DOCUMENTS_DIR, recursive=True)


def iter_changes(root: Path) -> Iterator[ManagedFiles]:
    """Every stem found under ``changes/`` (spec §3)."""
    return _iter_managed(root / CHANGES_DIR, recursive=False)


def iter_terms(root: Path) -> Iterator[ManagedFiles]:
    """Every stem found under ``glossary/`` (spec §3)."""
    return _iter_managed(root / GLOSSARY_DIR, recursive=False)


def _find(files: Iterator[ManagedFiles], stem: str) -> ManagedFiles | None:
    for entry in files:
        if entry.stem == stem:
            return entry
    return None


def find_document(root: Path, doc_id: str) -> ManagedFiles | None:
    """Locate a document by ID anywhere under ``documents/**`` (spec §3)."""
    return _find(iter_documents(root), doc_id)


def find_change(root: Path, cr_id: str) -> ManagedFiles | None:
    """Locate a change request by ID under ``changes/``, or ``None`` (spec §3)."""
    return _find(iter_changes(root), cr_id)


def find_term(root: Path, slug: str) -> ManagedFiles | None:
    """Locate a glossary term by slug under ``glossary/``, or ``None`` (spec §3)."""
    return _find(iter_terms(root), slug)


def canonical_json_dumps(obj: BaseModel | Mapping[str, Any]) -> str:
    """Canonical JSON text (spec §5.4): indent=2, ensure_ascii=False, sort_keys=True.

    Trailing newline. Top-level ``links`` are sorted by ``(type, target)``,
    ``scope`` by ``id``, ``introduces`` ascending (spec §5.4, §9.2).
    """
    return (
        json.dumps(
            _normalise_lists(_to_data(obj)),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )


def canonical_json_bytes(obj: BaseModel | Mapping[str, Any]) -> bytes:
    """UTF-8 bytes of :func:`canonical_json_dumps`."""
    return canonical_json_dumps(obj).encode("utf-8")


def _to_data(obj: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json", by_alias=True)
    return dict(obj)


def _is_str(entry: object, key: str) -> bool:
    return isinstance(entry, Mapping) and isinstance(entry.get(key), str)


def _normalise_lists(data: dict[str, Any]) -> dict[str, Any]:
    links = data.get("links")
    if isinstance(links, list) and all(
        _is_str(entry, "type") and _is_str(entry, "target") for entry in links
    ):
        data["links"] = sorted(
            links, key=lambda entry: (entry["type"], entry["target"])
        )
    scope = data.get("scope")
    if isinstance(scope, list) and all(_is_str(entry, "id") for entry in scope):
        data["scope"] = sorted(scope, key=lambda entry: entry["id"])
    introduces = data.get("introduces")
    if isinstance(introduces, list) and all(
        isinstance(item, str) for item in introduces
    ):
        data["introduces"] = sorted(introduces)
    return data


def write_sidecar(path: Path, obj: BaseModel | Mapping[str, Any]) -> None:
    """Write ``obj`` to ``path`` as canonical JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(obj))


def read_sidecar[M: BaseModel](path: Path, model: type[M]) -> M:
    """Read and validate the sidecar at ``path`` as ``model``.

    Raises ``FileNotFoundError`` when absent and ``pydantic.ValidationError``
    when unparsable or invalid (mapped to ``E-SIDECAR-INVALID`` by callers).
    """
    text = path.read_bytes().decode("utf-8-sig")
    return model.model_validate_json(text)


def read_body(path: Path) -> str:
    """Read a Markdown body: UTF-8, BOM stripped, line endings normalised to LF."""
    with path.open("r", encoding="utf-8-sig", newline=None) as handle:
        return handle.read()


def write_body(path: Path, text: str) -> None:
    """Write a Markdown body as UTF-8 without BOM and LF line endings (spec §5.2)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(normalised)


class CacheFileEntry(BaseModel):
    """One ``files`` entry of the index cache (spec §16.5)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    mtime_ns: int
    size: int
    body_hash: str


class CacheIndex(BaseModel):
    """Rebuildable index cache ``.gregraph/cache/index.json`` (spec §16.5).

    ``files`` keys are repository-relative POSIX paths. Absence or corruption
    of the file is never an error: :func:`load_cache` returns a fresh empty
    index and the caller repopulates it silently.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_: int = Field(
        default=1,
        alias="schema",
        validation_alias="schema",
        serialization_alias="schema",
    )
    tool_version: str = __version__
    files: dict[str, CacheFileEntry] = Field(default_factory=dict)
    types_seen: dict[str, str] = Field(default_factory=dict)
    templates_seen: dict[str, str] = Field(default_factory=dict)


def load_cache(root: Path) -> CacheIndex:
    """Read the index cache, rebuilding silently on absence/corruption (§16.5)."""
    try:
        return read_sidecar(cache_path(root), CacheIndex)
    except (OSError, ValueError, ValidationError):
        return CacheIndex()


def write_cache(root: Path, cache: CacheIndex) -> None:
    """Write the index cache as canonical JSON."""
    write_sidecar(cache_path(root), cache)


def stat_cache_entry(path: Path, body_hash: str) -> CacheFileEntry:
    """Cache entry for ``path`` with the given body hash (spec §16.5)."""
    stat = path.stat()
    return CacheFileEntry(
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
        body_hash=body_hash,
    )


def cache_entry_is_fresh(entry: CacheFileEntry, path: Path) -> bool:
    """Whether ``entry`` still matches ``path``'s mtime and size (skip re-hashing)."""
    try:
        stat = path.stat()
    except OSError:
        return False
    return entry.mtime_ns == stat.st_mtime_ns and entry.size == stat.st_size
