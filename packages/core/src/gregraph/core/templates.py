"""Template loading, rendering (jinja2), versions, migration (spec §5.5, §7.7).

Templates live at ``.gregraph/templates/<name>/v<N>/`` with ``template.md`` and
``template.json``; shipped ones are copied from ``gregraph.builtin_templates``
by ``init`` (spec §16.1, §13.1).

Pure functions and data only — the migration planner returns a plan; writing
migrated files is the job of the ``migrate`` operation (S15).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from gregraph.core.markdown import parse_sections, strip_html_comments
from gregraph.core.models import Finding, TemplateDescriptor, TemplateSection

__all__ = [
    "LoadedTemplate",
    "MigrationPlan",
    "check_deprecated",
    "load_template_dir",
    "plan_migration",
    "render_template",
    "resolve_template",
    "sections_hash",
]

_VERSION_DIR_RE = re.compile(r"^v(\d+)$")


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadedTemplate:
    """One template version: descriptor plus the ``template.md`` source."""

    descriptor: TemplateDescriptor
    body: str

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def version(self) -> int:
        return self.descriptor.version


@dataclass(frozen=True)
class MigrationPlan:
    """Result of :func:`plan_migration` — pure data, no side effects."""

    kind: Literal["in-place", "superseding"]
    from_version: int
    to_version: int
    new_body: str
    renamed: list[tuple[str, str]] = field(default_factory=list)
    inserted: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    manual_attention: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# loading and resolution
# --------------------------------------------------------------------------


def load_template_dir(directory: Path) -> dict[str, list[LoadedTemplate]]:
    """Load every template under ``directory`` as ``<name>/v<N>/`` pairs.

    Versions are returned sorted ascending and must be contiguous from ``v1``
    (spec §5.5). Raises :class:`ValueError` on a gap or a missing ``v1``.
    """
    result: dict[str, list[LoadedTemplate]] = {}
    if not directory.is_dir():
        return result
    for name_dir in sorted(directory.iterdir()):
        if not name_dir.is_dir():
            continue
        versions: dict[int, LoadedTemplate] = {}
        for version_dir in sorted(name_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            match = _VERSION_DIR_RE.match(version_dir.name)
            if match is None:
                continue
            number = int(match.group(1))
            descriptor = _read_descriptor(version_dir)
            body = (version_dir / "template.md").read_text(encoding="utf-8")
            versions[number] = LoadedTemplate(descriptor=descriptor, body=body)
        if not versions:
            continue
        _check_contiguity(name_dir.name, sorted(versions))
        result[name_dir.name] = [versions[n] for n in sorted(versions)]
    return result


def _read_descriptor(version_dir: Path) -> TemplateDescriptor:
    import json

    data = json.loads((version_dir / "template.json").read_text(encoding="utf-8"))
    return TemplateDescriptor.model_validate(data)


def _check_contiguity(name: str, numbers: Sequence[int]) -> None:
    expected = list(range(1, len(numbers) + 1))
    if list(numbers) != expected:
        raise ValueError(
            f"template {name!r}: version directories must be contiguous from v1, "
            f"got {list(numbers)}"
        )


def resolve_template(
    versions: Sequence[LoadedTemplate],
    *,
    version: int | None = None,
    allow_deprecated: bool = False,
) -> LoadedTemplate:
    """Pick the template version to use (spec §5.5).

    With ``version`` given, that exact version is returned. Otherwise the
    latest non-deprecated version wins. A deprecated version is only returned
    when it was requested explicitly **and** ``allow_deprecated`` is set —
    callers turn the refusal into a :class:`~gregraph.core.models.Finding`.
    """
    if not versions:
        raise ValueError("no template versions available")
    if version is not None:
        for candidate in versions:
            if candidate.version == version:
                return candidate
        raise ValueError(f"template version v{version} not found")
    for candidate in reversed(versions):
        if not candidate.descriptor.deprecated:
            return candidate
    raise ValueError("all template versions are deprecated")


# --------------------------------------------------------------------------
# rendering and deprecation
# --------------------------------------------------------------------------


def render_template(template: LoadedTemplate, /, **variables: object) -> str:
    """Render ``template.md`` with jinja2 (spec §5.5).

    Uses :class:`~jinja2.StrictUndefined` and ``keep_trailing_newline=True``
    so a missing variable is an error and the body's trailing newline survives
    ``hashing.normalise_body``.
    """
    env = SandboxedEnvironment(undefined=StrictUndefined, keep_trailing_newline=True)
    return env.from_string(template.body).render(**variables)


def check_deprecated(
    template: LoadedTemplate,
    *,
    version_pinned: bool,
    allow_deprecated: bool,
) -> Finding | None:
    """Return a refusal finding when a deprecated version would be used.

    Spec §5.5: ``new`` refuses a deprecated template version unless
    ``--template-version`` is given explicitly together with
    ``--allow-deprecated``.  The finding is data; raising is the caller's job.
    """
    if not template.descriptor.deprecated:
        return None
    if version_pinned and allow_deprecated:
        return None
    return Finding(
        code="W-TEMPLATE-DEPRECATED",
        severity="E",
        subject=template.name,
        message=(
            f"template {template.name!r} v{template.version} is deprecated"
            + (
                "; pass --template-version with --allow-deprecated to use it"
                if not version_pinned
                else "; pass --allow-deprecated to use it"
            )
        ),
        fix="gregraph template list",
    )


def sections_hash(descriptor: TemplateDescriptor) -> str:
    """Stable hash of a template's section heading list (spec §5.5, §16.5).

    Used for the ``E-TEMPLATE-MUTATED`` cache check: the cache stores
    ``<name>/v<N> → sections-hash`` and validate compares.
    """
    joined = "\n".join(s.heading for s in descriptor.sections)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# --------------------------------------------------------------------------
# migration planner (pure)
# --------------------------------------------------------------------------

_UNMAPPED_HEADING = "Unmapped content (migration)"


def plan_migration(
    *,
    current: LoadedTemplate,
    target: LoadedTemplate,
    body: str,
    chain: Sequence[LoadedTemplate],
    supersede: bool = False,
) -> MigrationPlan:
    """Plan the migration of one body from ``current`` to ``target`` (spec §7.7).

    ``chain`` lists every intermediate template version from ``current.version
    + 1`` up to and including ``target``.  In-place migration is possible iff
    every step in the chain has ``breaking: false`` and ``supersede`` is not
    forced.  The function is pure — it never touches the filesystem.
    """
    breaking_steps = [t for t in chain if t.descriptor.breaking]
    if supersede or breaking_steps:
        return _plan_superseding(current, target, body, breaking_steps)
    return _plan_in_place(current, target, body)


def _split_body(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(preamble, [(heading, content), …])`` for a Markdown body.

    The preamble is everything up to (but excluding) the first level-2 heading,
    including the H1 title line.
    """
    sections = parse_sections(body)
    if not sections:
        return body, []
    # Locate the first h2 line to split the preamble off.
    lines = body.split("\n")
    first_heading = f"## {sections[0].heading}"
    cut = 0
    for index, line in enumerate(lines):
        if line.strip() == first_heading.strip():
            cut = index
            break
    preamble = "\n".join(lines[:cut]).rstrip("\n")
    return preamble, [(s.heading, s.content) for s in sections]


def _find_body_section(
    body_sections: Sequence[tuple[str, str]],
    section: TemplateSection,
) -> int | None:
    for index, (heading, _content) in enumerate(body_sections):
        text = heading.strip()
        if text == section.heading.strip():
            return index
        if any(text == alt.strip() for alt in section.renamed_from):
            return index
    return None


def _plan_in_place(
    current: LoadedTemplate, target: LoadedTemplate, body: str
) -> MigrationPlan:
    preamble, body_sections = _split_body(body)
    renamed: list[tuple[str, str]] = []
    inserted: list[str] = []
    unknown: list[str] = []
    findings: list[Finding] = []

    # Map body section index -> target section (None = unknown).
    matched: dict[int, TemplateSection] = {}
    for section in target.descriptor.sections:
        found = _find_body_section(body_sections, section)
        if found is not None:
            matched[found] = section
            old_heading = body_sections[found][0]
            if old_heading.strip() != section.heading.strip():
                renamed.append((old_heading.strip(), section.heading))
        else:
            inserted.append(section.heading)

    for index, (heading, _content) in enumerate(body_sections):
        if index not in matched:
            unknown.append(heading.strip())
            findings.append(
                Finding(
                    code="W-SECTION-UNKNOWN",
                    severity="W",
                    subject=target.name,
                    message=f"section {heading.strip()!r} is not in template "
                    f"{target.name!r} v{target.version}",
                )
            )

    # Rebuild: walk body sections in order, inserting missing target sections
    # after the nearest preceding known section (spec §7.7).
    target_order = {s.heading: i for i, s in enumerate(target.descriptor.sections)}
    blocks: list[str] = []
    if preamble:
        blocks.append(preamble)

    emitted: set[str] = set()
    for index, (heading, content) in enumerate(body_sections):
        hit = matched.get(index)
        if hit is None:
            # Unknown section: left in place, but first emit any target
            # sections that belong before it and are still missing.
            position = _insertion_point(body_sections, matched, index, target_order)
            for pending in target.descriptor.sections:
                if pending.heading in inserted and pending.heading not in emitted:
                    if _is_before(pending, position, target_order):
                        blocks.append(_new_section_block(pending))
                        emitted.add(pending.heading)
            blocks.append(_section_block(heading, content))
        else:
            # Emit any missing target sections that come before this one.
            for pending in target.descriptor.sections:
                if pending.heading in inserted and pending.heading not in emitted:
                    if target_order[pending.heading] < target_order[hit.heading]:
                        blocks.append(_new_section_block(pending))
                        emitted.add(pending.heading)
            blocks.append(_section_block(hit.heading, content))

    for pending in target.descriptor.sections:
        if pending.heading in inserted and pending.heading not in emitted:
            blocks.append(_new_section_block(pending))
            emitted.add(pending.heading)

    return MigrationPlan(
        kind="in-place",
        from_version=current.version,
        to_version=target.version,
        new_body="\n\n".join(b for b in blocks if b) + "\n",
        renamed=renamed,
        inserted=inserted,
        unknown=unknown,
        findings=findings,
    )


def _insertion_point(
    body_sections: Sequence[tuple[str, str]],
    matched: Mapping[int, TemplateSection],
    before_index: int,
    target_order: Mapping[str, int],
) -> int:
    """Return the target-order position that ``before_index`` belongs after."""
    best = -1
    for index in range(before_index):
        section = matched.get(index)
        if section is not None:
            best = max(best, target_order.get(section.heading, -1))
    return best


def _is_before(
    section: TemplateSection, position: int, target_order: Mapping[str, int]
) -> bool:
    return target_order.get(section.heading, 1 << 30) <= position + 1


def _section_block(heading: str, content: str) -> str:
    text = strip_html_comments(content).strip()
    if text:
        return f"## {heading}\n{text}"
    return f"## {heading}"


def _new_section_block(section: TemplateSection) -> str:
    if section.placeholder:
        return f"## {section.heading}\n*{section.placeholder}*"
    return f"## {section.heading}"


def _plan_superseding(
    current: LoadedTemplate,
    target: LoadedTemplate,
    body: str,
    breaking_steps: Sequence[LoadedTemplate],
) -> MigrationPlan:
    preamble, body_sections = _split_body(body)
    renamed: list[tuple[str, str]] = []
    unmapped: list[str] = []
    manual: list[str] = []

    used: set[int] = set()
    copied: list[str] = []
    for section in target.descriptor.sections:
        found = _find_body_section(body_sections, section)
        if found is None:
            copied.append(_new_section_block(section))
            continue
        used.add(found)
        old_heading, content = body_sections[found]
        if old_heading.strip() != section.heading.strip():
            renamed.append((old_heading.strip(), section.heading))
        copied.append(_section_block(section.heading, content))

    leftovers: list[str] = []
    for index, (heading, content) in enumerate(body_sections):
        if index not in used:
            unmapped.append(heading.strip())
            leftovers.append(_section_block(heading, content))
            manual.append(
                f"section {heading.strip()!r} has no match in the new template"
            )

    if leftovers:
        copied.append(f"## {_UNMAPPED_HEADING}\n" + "\n\n".join(leftovers))

    title_line = "# {{ title }}"
    if preamble:
        for line in preamble.split("\n"):
            if line.startswith("# ") and not line.startswith("## "):
                title_line = line
                break

    if breaking_steps:
        names = ", ".join(f"v{t.version}" for t in breaking_steps)
        manual.insert(0, f"breaking template step(s): {names}")

    return MigrationPlan(
        kind="superseding",
        from_version=current.version,
        to_version=target.version,
        new_body=title_line + "\n\n" + "\n\n".join(copied) + "\n",
        renamed=renamed,
        unmapped=unmapped,
        manual_attention=manual,
    )
