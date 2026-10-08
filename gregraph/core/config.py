"""config.toml model (pydantic), defaults, types (spec §3, §5.3, appendix B.1).

Sections: gregraph, ids, git, versioning, graph, assets, types, cr.
Read with stdlib ``tomllib``; written with the minimal internal TOML emitter
below (docs/decisions.md ``D-TOML-EMITTER``, spec §16.3) — no ``tomli-w``
dependency. ``folder`` defaults to the type name and is omitted when written
if it still equals the type name (matches appendix B.1 text).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gregraph import __version__

Kind = Literal["goal", "requirement", "design", "verification", "information"]
Policy = Literal["block", "warn"]

_TYPE_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
_PREFIX_RE = re.compile(r"[A-Z][A-Z0-9]{0,7}")
_BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")


class GregraphSection(BaseModel):
    """``[gregraph]``: config schema version and writing tool version."""

    model_config = ConfigDict(extra="forbid")

    config_schema: Literal[1] = 1
    tool_version: str = __version__


class IdsSection(BaseModel):
    """``[ids]``: human-ID prefix (spec §4.1)."""

    model_config = ConfigDict(extra="forbid")

    prefix: str = "RE"

    @field_validator("prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        if _PREFIX_RE.fullmatch(value) is None:
            raise ValueError(
                f"ids.prefix must match [A-Z][A-Z0-9]{{0,7}}, got {value!r}"
            )
        return value


class GitSection(BaseModel):
    """``[git]``: baseline branch (spec §12.4)."""

    model_config = ConfigDict(extra="forbid")

    baseline_branch: str = "main"


class VersioningSection(BaseModel):
    """``[versioning]``: link-freshness and CR-modification policies."""

    model_config = ConfigDict(extra="forbid")

    on_outdated_links: Policy = "block"
    on_cr_modified: Policy = "warn"


class GraphSection(BaseModel):
    """``[graph]``: open-conflict policy (spec §11)."""

    model_config = ConfigDict(extra="forbid")

    open_conflicts: Policy = "warn"


class AssetsSection(BaseModel):
    """``[assets]``: asset size warning threshold (spec §5.7)."""

    model_config = ConfigDict(extra="forbid")

    max_size_kb: int = 5120


class TypeDefinition(BaseModel):
    """One ``[types.<name>]`` entry (spec §5.3); ``folder`` defaults to the name."""

    model_config = ConfigDict(extra="forbid")

    kind: Kind
    template: str
    folder: str


class CrSection(BaseModel):
    """``[cr]``: change-request settings (spec §9.1–9.3)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    template: str = "change-request"
    deciders: list[str] = Field(default_factory=list)


def default_types() -> dict[str, TypeDefinition]:
    """Shipped types of appendix B.1, in appendix B.1 order."""
    shipped: list[tuple[str, Kind, str]] = [
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
    ]
    return {
        name: TypeDefinition(kind=kind, template=template, folder=name)
        for name, kind, template in shipped
    }


class Config(BaseModel):
    """Repository configuration ``.gregraph/config.toml`` (appendix B.1).

    Field defaults match appendix B.1 exactly. A ``types`` key present in the
    file replaces the shipped set (absent key = shipped defaults).
    """

    model_config = ConfigDict(extra="forbid")

    gregraph: GregraphSection = Field(default_factory=GregraphSection)
    ids: IdsSection = Field(default_factory=IdsSection)
    git: GitSection = Field(default_factory=GitSection)
    versioning: VersioningSection = Field(default_factory=VersioningSection)
    graph: GraphSection = Field(default_factory=GraphSection)
    assets: AssetsSection = Field(default_factory=AssetsSection)
    types: dict[str, TypeDefinition] = Field(default_factory=default_types)
    cr: CrSection = Field(default_factory=CrSection)

    @field_validator("types", mode="before")
    @classmethod
    def _validate_type_names(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        checked: dict[str, object] = {}
        for name, spec in value.items():
            if not isinstance(name, str) or _TYPE_NAME_RE.fullmatch(name) is None:
                raise ValueError(f"type name must match [a-z][a-z0-9-]*, got {name!r}")
            if isinstance(spec, Mapping) and "folder" not in spec:
                spec = {**spec, "folder": name}
            checked[name] = spec
        return checked


def read_config(path: Path) -> Config:
    """Read and validate ``config.toml`` at ``path`` (spec §5.3, appendix B.1)."""
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return Config.model_validate(data)


def write_config(path: Path, config: Config) -> None:
    """Write ``config`` as TOML to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_toml(config), encoding="utf-8", newline="\n")


def dumps_toml(config: Config) -> str:
    """Serialise ``config`` to TOML text with the internal emitter (D-TOML-EMITTER).

    Sections are emitted in model field order (appendix B.1 order); ``types``
    tables keep insertion order; ``folder`` is omitted when equal to the type
    name. Comments are never written or preserved.
    """
    return _dumps_table(_omit_default_folders(config.model_dump(mode="json")))


def _omit_default_folders(data: dict[str, Any]) -> dict[str, Any]:
    types = data.get("types")
    if not isinstance(types, dict):
        return data
    pruned: dict[str, Any] = {}
    for name, spec in types.items():
        if isinstance(spec, dict) and spec.get("folder") == name:
            spec = {key: value for key, value in spec.items() if key != "folder"}
        pruned[name] = spec
    return {**data, "types": pruned}


def _dumps_table(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    scalars = [
        (key, value) for key, value in data.items() if not isinstance(value, dict)
    ]
    tables = [(key, value) for key, value in data.items() if isinstance(value, dict)]
    for key, value in scalars:
        lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    if scalars and tables:
        lines.append("")
    for key, value in tables:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(_dump_named_table(key, value))
    text = "\n".join(lines)
    return text if text.endswith("\n") else text + "\n"


def _dump_named_table(name: str, value: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not value:
        return [f"[{_toml_key(name)}]", ""]
    if all(isinstance(item, dict) for item in value.values()):
        for sub_name, sub_value in value.items():
            assert isinstance(sub_value, dict)
            lines.append(f"[{_toml_key(name)}.{_toml_key(str(sub_name))}]")
            for key, item in sub_value.items():
                lines.append(f"{_toml_key(key)} = {_toml_value(item)}")
            lines.append("")
        return lines
    lines.append(f"[{_toml_key(name)}]")
    for key, item in value.items():
        if isinstance(item, dict):
            raise TypeError(
                f"unsupported nested table {_toml_key(name)}.{_toml_key(key)}"
            )
        lines.append(f"{_toml_key(key)} = {_toml_value(item)}")
    lines.append("")
    return lines


def _toml_key(key: str) -> str:
    if _BARE_KEY_RE.fullmatch(key):
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
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")
