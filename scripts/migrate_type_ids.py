#!/usr/bin/env python3
"""Migrate GREGraph IDs to typed IDs (config schema 1 -> 2).

Legacy IDs are ``<PREFIX>-<6 Crockford chars>``.  Typed IDs are
``<PREFIX>-<ABBREVIATION>-<6 Crockford chars>`` for documents and
``<PREFIX>-CHG-<6 Crockford chars>`` for change requests.  Type
abbreviations live under ``[types.<name>]`` in ``.gregraph/config.toml``
as ``abbreviation = "FEAT"`` (pattern ``[A-Z]{3,5}``, unique, ``CHG``
reserved).

The script is deliberately standalone: standard library only, no imports
from ``gregraph``.  It accepts schema-1 repositories so users can migrate
before upgrading.  Default mode is a dry run; ``--apply`` is required to
write anything.  It never commits.

Usage::

    python scripts/migrate_type_ids.py [REPO] [--dry-run] [--apply]
        [--abbreviation TYPE=ABBR ...] [--allow-dirty] [--map-out PATH]
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from uuid import UUID

CROCKFORD_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ID_BODY_LENGTH: Final = 6
ID_BODY_BITS: Final = 30
ID_BODY_PATTERN: Final = re.compile(r"[0-9A-HJKMNP-TV-Z]{6}")
ABBREVIATION_PATTERN: Final = re.compile(r"[A-Z]{3,5}")
PREFIX_PATTERN: Final = re.compile(r"[A-Z][A-Z0-9]{0,7}")
TYPE_NAME_PATTERN: Final = re.compile(r"[a-z][a-z0-9-]*")
RESERVED_ABBREVIATION: Final = "CHG"
DEFAULT_PREFIX: Final = "RE"

CONFIG_RELPATH: Final = Path(".gregraph/config.toml")
CACHE_RELPATH: Final = Path(".gregraph/cache/index.json")

#: Shipped type -> abbreviation (docs/design.md; also used when [types] is absent).
SHIPPED_ABBREVIATIONS: Final[dict[str, str]] = {
    "context": "CTX",
    "goal": "GOAL",
    "epic": "EPIC",
    "feature": "FEAT",
    "user-story": "STORY",
    "functional-requirement": "FUNC",
    "non-functional-requirement": "NFR",
    "constraint": "CON",
    "design": "DSGN",
    "decision": "DEC",
    "test-case": "TEST",
    "stakeholder": "STKH",
    "assumption": "ASM",
}

#: Shipped default type tables, in appendix B.1 order: name -> (kind, template).
SHIPPED_TYPES: Final[tuple[tuple[str, str, str], ...]] = (
    ("context", "goal", "context"),
    ("goal", "goal", "goal"),
    ("epic", "goal", "epic"),
    ("feature", "requirement", "feature"),
    ("user-story", "requirement", "user-story"),
    ("functional-requirement", "requirement", "requirement-ears"),
    ("non-functional-requirement", "requirement", "requirement-ears"),
    ("constraint", "requirement", "constraint"),
    ("design", "design", "design"),
    ("decision", "design", "decision"),
    ("test-case", "verification", "test-case"),
    ("stakeholder", "information", "stakeholder"),
    ("assumption", "information", "assumption"),
)

_BARE_KEY_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]+")
_BODY_MASK: Final = (1 << ID_BODY_BITS) - 1


class MigrationError(RuntimeError):
    """A validation error that aborts the migration before any write."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def encode_body(value: int) -> str:
    """Encode a 30-bit value as six Crockford base32 characters."""
    if not 0 <= value <= _BODY_MASK:
        raise ValueError(f"body value out of range: {value}")
    chars: list[str] = []
    for shift in range((ID_BODY_LENGTH - 1) * 5, -1, -5):
        chars.append(CROCKFORD_ALPHABET[(value >> shift) & 0x1F])
    return "".join(chars)


def id_body(uuid: UUID) -> str:
    """The six-character Crockford body derived from ``uuid``."""
    return encode_body(uuid.int >> (128 - ID_BODY_BITS))


def normalise_body(body: str) -> str:
    """Normalise Markdown exactly like ``gregraph.core.hashing.normalise_body``."""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    collapsed: list[str] = []
    blanks = 0
    for line in lines:
        if line == "":
            blanks += 1
            if blanks <= 2:
                collapsed.append(line)
        else:
            blanks = 0
            collapsed.append(line)
    joined = "\n".join(collapsed)
    return joined.rstrip("\n") + "\n"


def body_hash(body: str) -> str:
    """Canonical body hash: ``sha256:`` plus the hex digest (spec §7.3)."""
    return "sha256:" + hashlib.sha256(normalise_body(body).encode("utf-8")).hexdigest()


def scope_hash(ids: list[str]) -> str:
    """Canonical CR scope hash: JSON list of the sorted IDs (spec §9.2)."""
    payload = json.dumps(sorted(ids), ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_json(data: dict[str, Any]) -> str:
    """Canonical sidecar JSON (spec §5.4): indented, UTF-8, sorted keys."""
    return (
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True).rstrip("\n")
        + "\n"
    )


def read_text(path: Path) -> str:
    """Read UTF-8 text, stripping a BOM and normalising line endings."""
    return (
        path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    )


def discover_root(start: Path) -> Path:
    """Nearest ancestor (inclusive) containing ``.gregraph/config.toml``."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_RELPATH).is_file():
            return candidate
    raise MigrationError(
        f"no GREGraph repository found at or above {start}: "
        f"missing {CONFIG_RELPATH.as_posix()}"
    )


def git_top_level(root: Path) -> Path | None:
    """Return the Git work-tree root containing ``root``, or ``None``."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return Path(text).resolve() if text else None


def git_status(root: Path) -> str | None:
    """Porcelain status of the Git work tree, or ``None`` outside Git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _git_path_argument(git_root: Path, absolute: Path) -> str:
    return absolute.relative_to(git_root).as_posix()


def git_tracks(git_root: Path, absolute: Path) -> bool:
    """Whether ``absolute`` (file or directory contents) is tracked by Git."""
    relative = _git_path_argument(git_root, absolute)
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "ls-files", "--", relative],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def move_path(source: Path, destination: Path, *, git_root: Path | None) -> None:
    """Move a file or directory, using ``git mv`` for tracked paths."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if git_root is not None and git_tracks(git_root, source):
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(git_root),
                    "mv",
                    "--",
                    _git_path_argument(git_root, source),
                    _git_path_argument(git_root, destination),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            result = None
        if result is not None and result.returncode == 0:
            return
    source.rename(destination)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@dataclass
class ConfigPlan:
    """Parsed config plus the schema-2 text to write."""

    path: Path
    original_text: str
    data: dict[str, Any]
    schema: int
    prefix: str
    types: dict[str, dict[str, Any]]
    abbreviations: dict[str, str]
    new_text: str

    @property
    def changed(self) -> bool:
        return self.new_text != self.original_text


def _default_types() -> dict[str, dict[str, Any]]:
    return {
        name: {"kind": kind, "template": template}
        for name, kind, template in SHIPPED_TYPES
    }


def _load_config(
    root: Path, overrides: dict[str, str], issues: list[str]
) -> ConfigPlan:
    path = root / CONFIG_RELPATH
    original = read_text(path)
    try:
        data = tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        raise MigrationError(f"cannot parse {path}: {exc}") from exc

    gregraph = data.get("gregraph")
    if gregraph is None:
        gregraph = {}
        data["gregraph"] = gregraph
    if not isinstance(gregraph, dict):
        raise MigrationError("config: [gregraph] must be a table")
    schema = gregraph.get("config_schema", 1)
    if schema not in (1, 2):
        raise MigrationError(f"unsupported config_schema {schema!r}; expected 1 or 2")
    if not isinstance(schema, int) or isinstance(schema, bool):
        raise MigrationError(f"unsupported config_schema {schema!r}; expected 1 or 2")

    ids = data.get("ids")
    prefix = DEFAULT_PREFIX
    if isinstance(ids, dict):
        raw_prefix = ids.get("prefix", DEFAULT_PREFIX)
        if isinstance(raw_prefix, str) and PREFIX_PATTERN.fullmatch(raw_prefix):
            prefix = raw_prefix
        else:
            issues.append(f"config: [ids].prefix is invalid: {raw_prefix!r}")

    types_data = data.get("types")
    types_were_absent = types_data is None
    if types_data is None:
        types = _default_types()
        data["types"] = types
    elif isinstance(types_data, dict):
        types = {
            str(name): dict(spec)
            for name, spec in types_data.items()
            if isinstance(spec, dict)
        }
        if len(types) != len(types_data):
            issues.append("config: every [types.<name>] entry must be a table")
    else:
        issues.append("config: [types] must be a table")
        types = {}

    abbreviations: dict[str, str] = {}
    for name in types:
        abbreviations[name] = SHIPPED_ABBREVIATIONS.get(name, "")
        configured = types[name].get("abbreviation")
        if configured is not None:
            if not isinstance(configured, str):
                issues.append(f"config: types.{name}.abbreviation must be a string")
            else:
                abbreviations[name] = configured
    abbreviations.update(overrides)

    new_types: dict[str, dict[str, Any]] = {}
    for name, spec in types.items():
        abbreviation = abbreviations.get(name, "")
        if not abbreviation:
            issues.append(
                f"type {name!r} has no abbreviation; pass --abbreviation {name}=ABBR"
            )
        new_spec = dict(spec)
        new_spec["abbreviation"] = abbreviation
        new_types[name] = new_spec

    _validate_abbreviations(new_types, abbreviations, issues)

    needs_rewrite = schema != 2 or types_were_absent or bool(overrides)
    if not types_were_absent and isinstance(types_data, dict):
        needs_rewrite = needs_rewrite or any(
            "abbreviation" not in spec
            for spec in types_data.values()
            if isinstance(spec, dict)
        )
    gregraph["config_schema"] = 2
    data["types"] = new_types
    new_text = dumps_toml(data) if needs_rewrite else original
    return ConfigPlan(
        path=path,
        original_text=original,
        data=data,
        schema=schema,
        prefix=prefix,
        types=types,
        abbreviations=dict(abbreviations),
        new_text=new_text,
    )


def _validate_abbreviations(
    types: dict[str, dict[str, Any]],
    abbreviations: dict[str, str],
    issues: list[str],
) -> None:
    seen: dict[str, str] = {}
    for name, abbreviation in abbreviations.items():
        if not abbreviation:
            continue
        if ABBREVIATION_PATTERN.fullmatch(abbreviation) is None:
            issues.append(
                f"invalid abbreviation for type {name!r}: {abbreviation!r} "
                "(expected [A-Z]{3,5})"
            )
            continue
        if abbreviation == RESERVED_ABBREVIATION:
            issues.append(
                f"abbreviation {abbreviation!r} for type {name!r} is reserved "
                "for change requests"
            )
            continue
        other = seen.get(abbreviation)
        if other is not None and other != name:
            issues.append(
                f"duplicate abbreviation {abbreviation!r} for types "
                f"{other!r} and {name!r}"
            )
        else:
            seen[abbreviation] = name
    for name, spec in types.items():
        abbreviation = spec.get("abbreviation", "")
        if isinstance(abbreviation, str) and abbreviation == RESERVED_ABBREVIATION:
            # Already reported above, but keep the message once per type.
            if not any(name in message and "reserved" in message for message in issues):
                issues.append(
                    f"abbreviation {abbreviation!r} for type {name!r} is reserved "
                    "for change requests"
                )


# ---------------------------------------------------------------------------
# TOML writer (minimal; comments are not preserved)
# ---------------------------------------------------------------------------


def _toml_key(key: str) -> str:
    if _BARE_KEY_PATTERN.fullmatch(key):
        return key
    return _toml_string(key)


def _toml_string(value: str) -> str:
    escaped: list[str] = ['"']
    for char in value:
        if char == '"':
            escaped.append('\\"')
        elif char == "\\":
            escaped.append("\\\\")
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif char == "\b":
            escaped.append("\\b")
        elif char == "\f":
            escaped.append("\\f")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            escaped.append(f"\\u{ord(char):04X}")
        else:
            escaped.append(char)
    escaped.append('"')
    return "".join(escaped)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")


def dumps_toml(data: dict[str, Any]) -> str:
    """Serialise a config mapping to TOML text (comments are lost)."""
    lines: list[str] = []
    _emit_table([], data, lines)
    text = "\n".join(lines).rstrip("\n")
    return text + "\n"


def _emit_table(path: list[str], table: dict[str, Any], lines: list[str]) -> None:
    scalars = [
        (key, value) for key, value in table.items() if not isinstance(value, dict)
    ]
    tables = [(key, value) for key, value in table.items() if isinstance(value, dict)]
    if path and (scalars or not tables):
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("[" + ".".join(_toml_key(part) for part in path) + "]")
    for key, value in scalars:
        lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    for key, value in tables:
        assert isinstance(value, dict)
        _emit_table([*path, key], value, lines)


# ---------------------------------------------------------------------------
# managed files
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    """One managed sidecar/body pair, before and after the rewrite."""

    category: str  # "document" | "change" | "term"
    sidecar: Path
    body: Path
    data: dict[str, Any]
    original_json: str
    original_body: str
    uuid: UUID | None = None
    type_name: str | None = None
    slug: str | None = None
    old_id: str = ""
    new_id: str = ""
    new_body: str = ""
    new_data: dict[str, Any] = field(default_factory=dict)
    new_sidecar: Path | None = None
    new_body_path: Path | None = None

    @property
    def body_changed(self) -> bool:
        return self.new_body != self.original_body

    @property
    def sidecar_changed(self) -> bool:
        assert self.new_sidecar is not None
        return canonical_json(self.new_data) != self.original_json

    @property
    def renamed(self) -> bool:
        assert self.new_sidecar is not None and self.new_body_path is not None
        return self.new_sidecar != self.sidecar or self.new_body_path != self.body


def _load_sidecar(path: Path) -> tuple[dict[str, Any] | None, str, list[str]]:
    issues: list[str] = []
    try:
        text = read_text(path)
    except OSError as exc:
        return None, "", [f"{path}: cannot read sidecar: {exc}"]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, text, [f"{path}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, text, [f"{path}: sidecar must be a JSON object"]
    return data, text, issues


def _same_derived_body(stem: str, sidecar_id: str, uuid: UUID) -> bool:
    body = id_body(uuid)
    return stem.endswith("-" + body) and sidecar_id.endswith("-" + body)


def load_entries(root: Path, issues: list[str]) -> list[Entry]:
    """Load documents, change requests and glossary terms, validating shapes."""
    entries: list[Entry] = []

    documents_dir = root / "documents"
    if documents_dir.is_dir():
        for path in sorted(documents_dir.rglob("*.json")):
            data, text, problems = _load_sidecar(path)
            issues.extend(problems)
            if data is None:
                continue
            stem = path.stem
            body_path = path.with_suffix(".md")
            if not body_path.is_file():
                issues.append(f"{path}: markdown body {body_path.name} is missing")
                continue
            sidecar_id = data.get("id")
            if not isinstance(sidecar_id, str) or not sidecar_id:
                issues.append(f"{path}: sidecar has no string 'id'")
                continue
            raw_uuid = data.get("uuid")
            try:
                uuid = UUID(str(raw_uuid))
            except (ValueError, TypeError, AttributeError):
                issues.append(f"{path}: sidecar has no valid 'uuid'")
                continue
            if stem != sidecar_id and not _same_derived_body(stem, sidecar_id, uuid):
                issues.append(
                    f"{path}: filename stem {stem!r} does not match sidecar id "
                    f"{sidecar_id!r}"
                )
                continue
            type_name = data.get("type")
            if not isinstance(type_name, str) or not type_name:
                issues.append(f"{path}: sidecar has no string 'type'")
                continue
            entries.append(
                Entry(
                    category="document",
                    sidecar=path,
                    body=body_path,
                    data=data,
                    original_json=text,
                    original_body=read_text(body_path),
                    uuid=uuid,
                    type_name=type_name,
                    old_id=sidecar_id,
                )
            )

    changes_dir = root / "changes"
    if changes_dir.is_dir():
        for path in sorted(changes_dir.glob("*.json")):
            data, text, problems = _load_sidecar(path)
            issues.extend(problems)
            if data is None:
                continue
            stem = path.stem
            body_path = path.with_suffix(".md")
            if not body_path.is_file():
                issues.append(f"{path}: markdown body {body_path.name} is missing")
                continue
            sidecar_id = data.get("id")
            if not isinstance(sidecar_id, str) or not sidecar_id:
                issues.append(f"{path}: sidecar has no string 'id'")
                continue
            raw_uuid = data.get("uuid")
            try:
                uuid = UUID(str(raw_uuid))
            except (ValueError, TypeError, AttributeError):
                issues.append(f"{path}: sidecar has no valid 'uuid'")
                continue
            if stem != sidecar_id and not _same_derived_body(stem, sidecar_id, uuid):
                issues.append(
                    f"{path}: filename stem {stem!r} does not match sidecar id "
                    f"{sidecar_id!r}"
                )
                continue
            entries.append(
                Entry(
                    category="change",
                    sidecar=path,
                    body=body_path,
                    data=data,
                    original_json=text,
                    original_body=read_text(body_path),
                    uuid=uuid,
                    old_id=sidecar_id,
                )
            )

    glossary_dir = root / "glossary"
    if glossary_dir.is_dir():
        for path in sorted(glossary_dir.glob("*.json")):
            data, text, problems = _load_sidecar(path)
            issues.extend(problems)
            if data is None:
                continue
            slug = data.get("slug")
            if not isinstance(slug, str) or not slug:
                issues.append(f"{path}: sidecar has no string 'slug'")
                continue
            if path.stem != slug:
                issues.append(
                    f"{path}: filename stem {path.stem!r} does not match slug {slug!r}"
                )
                continue
            body_path = path.with_suffix(".md")
            if not body_path.is_file():
                issues.append(f"{path}: markdown body {body_path.name} is missing")
                continue
            entries.append(
                Entry(
                    category="term",
                    sidecar=path,
                    body=body_path,
                    data=data,
                    original_json=text,
                    original_body=read_text(body_path),
                    slug=slug,
                    old_id=slug,
                    new_id=slug,
                )
            )

    return entries


# ---------------------------------------------------------------------------
# rewrite planning
# ---------------------------------------------------------------------------


@dataclass
class MigrationPlan:
    root: Path
    config: ConfigPlan
    entries: list[Entry]
    assets: list[tuple[Path, Path]]
    cache: Path
    id_map: dict[str, str]
    document_map: dict[str, str]
    change_map: dict[str, str]

    @property
    def documents(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.category == "document"]

    @property
    def changes(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.category == "change"]

    @property
    def terms(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.category == "term"]

    @property
    def changed_entries(self) -> list[Entry]:
        return [
            entry
            for entry in self.entries
            if entry.body_changed
            or entry.sidecar_changed
            or (entry.category != "term" and entry.renamed)
        ]

    @property
    def has_changes(self) -> bool:
        return bool(
            self.changed_entries
            or self.assets
            or self.config.changed
            or self.cache.exists()
        )


def _rewrite_text(text: str, id_map: dict[str, str]) -> str:
    """Replace exact known old IDs, case-insensitively, longest first."""
    replacements = {key: value for key, value in id_map.items() if key != value.upper()}
    if not replacements:
        return text
    alternatives = sorted(replacements, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![A-Za-z0-9_-])(?:"
        + "|".join(re.escape(item) for item in alternatives)
        + r")(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        return replacements.get(match.group(0).upper(), match.group(0))

    return pattern.sub(replace, text)


def _resolve_id(value: str, id_map: dict[str, str]) -> str:
    return id_map.get(value.upper(), value)


def _build_plan(
    root: Path,
    config: ConfigPlan,
    entries: list[Entry],
    issues: list[str],
) -> MigrationPlan:
    documents = [entry for entry in entries if entry.category == "document"]
    changes = [entry for entry in entries if entry.category == "change"]
    terms = [entry for entry in entries if entry.category == "term"]

    for entry in documents:
        assert entry.uuid is not None and entry.type_name is not None
        if entry.type_name not in config.types:
            issues.append(
                f"{entry.sidecar}: document type {entry.type_name!r} is not "
                "configured in [types]"
            )
            continue
        abbreviation = config.abbreviations.get(entry.type_name, "")
        if not abbreviation:
            issues.append(
                f"{entry.sidecar}: document type {entry.type_name!r} has no "
                f"abbreviation; pass --abbreviation {entry.type_name}=ABBR"
            )
            continue
        entry.new_id = f"{config.prefix}-{abbreviation}-{id_body(entry.uuid)}"

    for entry in changes:
        assert entry.uuid is not None
        entry.new_id = f"{config.prefix}-{RESERVED_ABBREVIATION}-{id_body(entry.uuid)}"

    if issues:
        raise MigrationError(_format_issues(issues))

    # Reject collisions in the new ID space and between replacement aliases.
    new_owners: dict[str, Entry] = {}
    id_map: dict[str, str] = {}
    for entry in [*documents, *changes]:
        owner = new_owners.get(entry.new_id)
        if owner is not None and owner is not entry:
            issues.append(
                f"new ID collision: {owner.sidecar} and {entry.sidecar} "
                f"both map to {entry.new_id}"
            )
        else:
            new_owners[entry.new_id] = entry

        assert entry.uuid is not None
        aliases = {
            entry.old_id,
            entry.sidecar.stem,
            f"{config.prefix}-{id_body(entry.uuid)}",
            entry.new_id,
        }
        for alias in aliases:
            if not alias:
                continue
            existing = id_map.get(alias.upper())
            if existing is not None and existing != entry.new_id:
                issues.append(
                    f"reference {alias!r} maps to both {existing} and {entry.new_id}"
                )
            else:
                id_map[alias.upper()] = entry.new_id

    document_map: dict[str, str] = {}
    change_map: dict[str, str] = {}
    for entry in documents:
        if entry.old_id != entry.new_id:
            document_map[entry.old_id] = entry.new_id
    for entry in changes:
        if entry.old_id != entry.new_id:
            change_map[entry.old_id] = entry.new_id

    assets: list[tuple[Path, Path]] = []
    for entry in documents:
        assert entry.new_id
        asset_root = root / "assets"
        destination = asset_root / entry.new_id
        candidates = [entry.old_id, entry.sidecar.stem]
        seen: set[Path] = set()
        for candidate in candidates:
            source = asset_root / candidate
            if source in seen:
                continue
            seen.add(source)
            if source == destination or not source.exists():
                continue
            if destination.exists():
                issues.append(f"asset collision: both {source} and {destination} exist")
                continue
            assets.append((source, destination))

    if issues:
        raise MigrationError(_format_issues(issues))

    for entry in [*documents, *changes]:
        new_sidecar = entry.sidecar.with_name(entry.new_id + ".json")
        new_body = entry.body.with_name(entry.new_id + ".md")
        if new_sidecar != entry.sidecar and new_sidecar.exists():
            issues.append(f"destination already exists: {new_sidecar}")
        if new_body != entry.body and new_body.exists():
            issues.append(f"destination already exists: {new_body}")
        entry.new_sidecar = new_sidecar
        entry.new_body_path = new_body

    for entry in terms:
        entry.new_sidecar = entry.sidecar
        entry.new_body_path = entry.body

    if issues:
        raise MigrationError(_format_issues(issues))

    for entry in entries:
        entry.new_body = _rewrite_text(entry.original_body, id_map)
        if entry.category == "document":
            entry.new_data = _rewrite_document(entry, id_map)
        elif entry.category == "change":
            entry.new_data = _rewrite_change(entry, id_map)
        else:
            entry.new_data = _rewrite_term(entry)

    return MigrationPlan(
        root=root,
        config=config,
        entries=entries,
        assets=assets,
        cache=root / CACHE_RELPATH,
        id_map=id_map,
        document_map=document_map,
        change_map=change_map,
    )


def _rewrite_document(entry: Entry, id_map: dict[str, str]) -> dict[str, Any]:
    data = dict(entry.data)
    data["id"] = entry.new_id
    title = data.get("title")
    if isinstance(title, str):
        data["title"] = _rewrite_text(title, id_map)
    origin_cr = data.get("origin_cr")
    if isinstance(origin_cr, str):
        data["origin_cr"] = _rewrite_text(origin_cr, id_map)
    links = data.get("links")
    if isinstance(links, list):
        rewritten: list[dict[str, Any]] = []
        for raw_link in links:
            if not isinstance(raw_link, dict):
                rewritten.append(raw_link)
                continue
            link = dict(raw_link)
            target = link.get("target")
            if isinstance(target, str):
                link["target"] = _resolve_id(target, id_map)
            rewritten.append(link)
        rewritten.sort(
            key=lambda link: (
                str(link.get("type", "")),
                str(link.get("target", "")),
            )
        )
        data["links"] = rewritten
    data["body_hash"] = body_hash(entry.new_body)
    return data


def _rewrite_change(entry: Entry, id_map: dict[str, str]) -> dict[str, Any]:
    data = dict(entry.data)
    data["id"] = entry.new_id
    for key in ("title", "branch", "external_ref"):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = _rewrite_text(value, id_map)
    scope = data.get("scope")
    new_ids: list[str] = []
    if isinstance(scope, list):
        rewritten_scope: list[dict[str, Any]] = []
        for raw_entry in scope:
            if not isinstance(raw_entry, dict):
                rewritten_scope.append(raw_entry)
                continue
            item = dict(raw_entry)
            item_id = item.get("id")
            if isinstance(item_id, str):
                item["id"] = _resolve_id(item_id, id_map)
                new_ids.append(item["id"])
            rewritten_scope.append(item)
        rewritten_scope.sort(key=lambda item: str(item.get("id", "")))
        data["scope"] = rewritten_scope
    introduces = data.get("introduces")
    if isinstance(introduces, list):
        data["introduces"] = sorted(
            _resolve_id(item, id_map) for item in introduces if isinstance(item, str)
        )
    data["body_hash"] = body_hash(entry.new_body)
    data["scope_hash"] = scope_hash(new_ids)
    return data


def _rewrite_term(entry: Entry) -> dict[str, Any]:
    data = dict(entry.data)
    data["body_hash"] = body_hash(entry.new_body)
    return data


def _format_issues(issues: list[str]) -> str:
    return "migration aborted:\n  - " + "\n  - ".join(issues)


def _contains_id(text: str, id_: str) -> bool:
    pattern = re.compile(
        r"(?<![A-Za-z0-9_-])" + re.escape(id_) + r"(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def _nothing_to_do(plan: MigrationPlan) -> bool:
    """Whether schema 2, typed IDs and complete abbreviations need no work.

    JSON formatting and hashes are not migrated on their own; only an actual
    legacy reference (in a body or sidecar) counts as remaining work.
    """
    if plan.config.schema != 2 or plan.config.changed:
        return False
    for entry in [*plan.documents, *plan.changes]:
        if (
            entry.old_id != entry.new_id
            or entry.sidecar.stem != entry.new_id
            or entry.body.stem != entry.new_id
        ):
            return False
    legacy_aliases = {
        f"{plan.config.prefix}-{id_body(entry.uuid)}"
        for entry in [*plan.documents, *plan.changes]
        if entry.uuid is not None
    }
    for entry in plan.entries:
        for legacy in legacy_aliases:
            if _contains_id(entry.original_body, legacy) or _contains_id(
                entry.original_json, legacy
            ):
                return False
    return True


# ---------------------------------------------------------------------------
# applying
# ---------------------------------------------------------------------------


def apply_plan(plan: MigrationPlan) -> None:
    """Perform renames, then content writes, cache removal and config last."""
    git_root = git_top_level(plan.root)

    for source, destination in plan.assets:
        move_path(source, destination, git_root=git_root)

    for entry in plan.changed_entries:
        assert entry.new_sidecar is not None and entry.new_body_path is not None
        if entry.new_sidecar != entry.sidecar:
            move_path(entry.sidecar, entry.new_sidecar, git_root=git_root)
        if entry.new_body_path != entry.body:
            move_path(entry.body, entry.new_body_path, git_root=git_root)

    for entry in plan.changed_entries:
        assert entry.new_sidecar is not None and entry.new_body_path is not None
        if entry.body_changed:
            entry.new_body_path.write_text(
                entry.new_body, encoding="utf-8", newline="\n"
            )
        if entry.sidecar_changed:
            entry.new_sidecar.write_text(
                canonical_json(entry.new_data), encoding="utf-8", newline="\n"
            )

    if plan.cache.exists():
        plan.cache.unlink()

    if plan.config.changed:
        plan.config.path.write_text(
            plan.config.new_text, encoding="utf-8", newline="\n"
        )


def write_mapping(plan: MigrationPlan, path: Path) -> None:
    payload = {
        "documents": plan.document_map,
        "changes": plan.change_map,
        "abbreviations": {
            name: abbreviation
            for name, abbreviation in plan.config.abbreviations.items()
            if abbreviation
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True).rstrip("\n")
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_overrides(raw: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in raw:
        name, separator, abbreviation = item.partition("=")
        if not separator or not name or not abbreviation:
            raise MigrationError(f"invalid --abbreviation {item!r}; expected TYPE=ABBR")
        if TYPE_NAME_PATTERN.fullmatch(name) is None:
            raise MigrationError(f"invalid type name in --abbreviation: {name!r}")
        overrides[name] = abbreviation
    return overrides


def _print_plan(plan: MigrationPlan, *, apply: bool, map_out: Path | None) -> None:
    documents = plan.documents
    changes = plan.changes
    terms = plan.terms
    document_changes = [entry for entry in documents if entry.old_id != entry.new_id]
    change_changes = [entry for entry in changes if entry.old_id != entry.new_id]
    print(f"repository: {plan.root}")
    print(f"mode: {'apply' if apply else 'dry run'}")
    print(f"documents: {len(documents)} ({len(document_changes)} to migrate)")
    print(f"change requests: {len(changes)} ({len(change_changes)} to migrate)")
    print(f"glossary terms: {len(terms)}")
    print(f"asset directories: {len(plan.assets)}")
    print(f"config schema: {plan.config.schema} -> 2")
    if document_changes or change_changes:
        print("mapping:")
        for entry in document_changes:
            print(f"  document  {entry.old_id} -> {entry.new_id}")
        for entry in change_changes:
            print(f"  change    {entry.old_id} -> {entry.new_id}")
    print("abbreviations:")
    for name, abbreviation in plan.config.abbreviations.items():
        if abbreviation:
            print(f"  {name} = {abbreviation}")
    print(
        "warning: Git history, tags and external references are not rewritten; "
        "use --map-out to update external systems."
    )
    if plan.config.changed and "#" in plan.config.original_text:
        print("warning: comments in .gregraph/config.toml are not preserved.")
    if map_out is not None and not apply:
        print(f"note: --map-out {map_out} is not written during a dry run.")
    if not apply:
        print("dry run: nothing written")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate GREGraph IDs to typed IDs and .gregraph/config.toml "
            "to schema 2. Dry run by default."
        )
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        help="repository root or any path inside it (default: current directory)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="plan only (default)")
    mode.add_argument("--apply", action="store_true", help="write the migration")
    parser.add_argument(
        "--abbreviation",
        action="append",
        default=[],
        metavar="TYPE=ABBR",
        help="override or add a type abbreviation (repeatable)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow a dirty Git working tree",
    )
    parser.add_argument(
        "--map-out",
        type=Path,
        metavar="PATH",
        help="write the old -> new ID mapping as JSON (apply only)",
    )
    args = parser.parse_args(argv)

    try:
        root = discover_root(Path(args.repo))
        overrides = _parse_overrides(args.abbreviation)

        git_root = git_top_level(root)
        if git_root is not None and not args.allow_dirty:
            status = git_status(git_root)
            if status:
                raise MigrationError(
                    "Git working tree is dirty; commit or stash changes, "
                    "or pass --allow-dirty"
                )

        issues: list[str] = []
        config = _load_config(root, overrides, issues)
        if issues:
            raise MigrationError(_format_issues(issues))

        entries = load_entries(root, issues)
        if issues:
            raise MigrationError(_format_issues(issues))

        plan = _build_plan(root, config, entries, issues)

        if _nothing_to_do(plan) or not plan.has_changes:
            print("nothing to do")
            return 0

        _print_plan(plan, apply=args.apply, map_out=args.map_out)

        if not args.apply:
            return 0

        apply_plan(plan)
        if args.map_out is not None:
            write_mapping(plan, args.map_out)
        print("migration complete")
        return 0
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
