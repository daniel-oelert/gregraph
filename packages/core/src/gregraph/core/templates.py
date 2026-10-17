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

from gregraph.core.markdown import (
    Section,
    find_section,
    heading_matches,
    parse_sections,
    section_is_empty,
    strip_html_comments,
)
from gregraph.core.models import (
    Finding,
    OperationRefused,
    TemplateDescriptor,
    TemplateSection,
)

__all__ = [
    "LoadedTemplate",
    "MigrationPlan",
    "assemble_sections",
    "check_deprecated",
    "check_required_sections",
    "is_section_unfilled",
    "load_template_dir",
    "match_template_section",
    "plan_migration",
    "prepare_whole_body",
    "render_template",
    "resolve_section_inputs",
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


# --------------------------------------------------------------------------
# agent authoring: template-guided sections and whole-body (§3.4)
# --------------------------------------------------------------------------


def is_section_unfilled(content: str, placeholder: str = "") -> bool:
    """Whether section ``content`` is empty or only its placeholder (§5.5).

    Skeletons wrap the descriptor placeholder in emphasis (``*…*``), so the
    bare, italic and bold spellings all count as untouched — the same rule
    as ``validation._is_unfilled`` and ``changes._is_unfilled``.
    """
    if section_is_empty(content, placeholder):
        return True
    stripped = placeholder.strip()
    if not stripped:
        return False
    return section_is_empty(content, f"*{stripped}*") or section_is_empty(
        content, f"**{stripped}**"
    )


def match_template_section(
    descriptor: TemplateDescriptor, given_heading: str
) -> TemplateSection:
    """Resolve one ``--section`` heading to its template section (§3.4 rule 2).

    Exact, trimmed, case-sensitive: ``heading`` first, then any
    ``renamed_from`` alias; if a heading could match two template sections,
    the first match in template order wins.  Raises ``OperationRefused``
    (``E-SECTION-UNKNOWN``) with the full section specification in
    ``details`` so an agent can self-correct without a template lookup
    (AGENT-017, appendix C).
    """
    given = given_heading.strip()
    for section in descriptor.sections:
        if given == section.heading.strip():
            return section
    for section in descriptor.sections:
        if any(given == alt.strip() for alt in section.renamed_from):
            return section
    raise OperationRefused(
        Finding(
            code="E-SECTION-UNKNOWN",
            severity="E",
            subject=f"{descriptor.name}/v{descriptor.version}",
            message=(
                f"section {given_heading!r} is not a section of template "
                f"{descriptor.name!r} v{descriptor.version} "
                "(exact, case-sensitive; see details.template_sections)"
            ),
            details={
                "given_heading": given_heading,
                "template": {"name": descriptor.name, "version": descriptor.version},
                "template_sections": [
                    sec.model_dump(mode="json") for sec in descriptor.sections
                ],
            },
        )
    )


def resolve_section_inputs(
    descriptor: TemplateDescriptor, entries: Sequence[tuple[str, str]]
) -> dict[str, str]:
    """Resolve ``(given_heading, content)`` pairs to canonical headings.

    Each heading goes through :func:`match_template_section`; two entries
    resolving to the same canonical heading raise ``ValueError`` — the CLI
    maps that to a usage error (exit 2); content is never silently merged
    (AGENT_READINESS §3.4 rule 1).  Contents are LF-normalised.
    """
    resolved: dict[str, str] = {}
    for given_heading, entry_content in entries:
        section = match_template_section(descriptor, given_heading)
        if section.heading in resolved:
            raise ValueError(f"duplicate section heading {section.heading!r}")
        resolved[section.heading] = entry_content.replace("\r\n", "\n").replace(
            "\r", "\n"
        )
    return resolved


def _is_atx_h1(line: str) -> bool:
    """Whether ``line`` is an ATX level-1 heading (AGENT_READINESS §3.4 rule 4)."""
    return line == "#" or line.startswith("# ") or line.startswith("#\t")


def _placeholder_block(section: TemplateSection) -> str:
    """Level-2 block for an unmentioned section: heading plus placeholder."""
    if section.placeholder:
        return f"## {section.heading}\n\n*{section.placeholder}*"
    return f"## {section.heading}"


def _body_preamble(base_body: str) -> str:
    """``base_body``'s text between the H1 line and the first ``##`` heading.

    Content before the first level-2 heading (rare) is preserved before the
    first assembled section on edits (AGENT_READINESS §3.4 rule 3); the H1
    line itself is not part of it — the assembled body starts with the
    canonical ``# {title}`` line.
    """
    preamble, _sections = _split_body(base_body)
    lines = preamble.split("\n")
    for index, line in enumerate(lines):
        if line.strip():
            if _is_atx_h1(line.lstrip()):
                lines = lines[index + 1 :]
            break
    return "\n".join(lines).strip()


def assemble_sections(
    descriptor: TemplateDescriptor,
    *,
    title: str,
    content: Mapping[str, str],
    base_body: str | None = None,
    preserve_existing: bool = False,
) -> str:
    """Assemble a full body in canonical template order (§3.4 rule 3, AGENT-015).

    ``# {title}`` first, then one level-2 block per section of
    ``descriptor.sections``.  Sections provided in ``content`` win.  With
    ``preserve_existing`` (``edit``, ``supersede --copy-body``) unmentioned
    sections keep their ``base_body`` content verbatim and extra level-2
    sections unknown to the template are kept at the end (AGENT-016);
    otherwise unmentioned sections emit the template placeholder.  Prose
    between the H1 and the first ``##`` heading is preserved before the
    first section on edits.
    """
    blocks: list[str] = [f"# {title}"]
    base_sections: list[Section] = []
    if base_body is not None:
        base_sections = parse_sections(base_body)
        if preserve_existing:
            preamble = _body_preamble(base_body)
            if preamble:
                blocks.append(preamble)
    for section in descriptor.sections:
        if section.heading in content:
            value = content[section.heading].strip("\n")
            if value:
                blocks.append(f"## {section.heading}\n\n{value}")
            else:
                blocks.append(f"## {section.heading}")
            continue
        existing = find_section(base_sections, section.heading, section.renamed_from)
        if preserve_existing:
            if existing is None:
                blocks.append(_placeholder_block(section))
            else:
                # Verbatim content; only block-boundary newlines are trimmed —
                # the ``"\n\n"`` join re-supplies the section separator, which
                # keeps repeated edits idempotent (AGENT-016).
                blocks.append(f"## {section.heading}\n{existing.content}".rstrip("\n"))
        elif (
            base_body is not None
            and existing is not None
            and existing.content.strip("\n")
        ):
            blocks.append(f"## {section.heading}\n\n{existing.content.strip(chr(10))}")
        else:
            blocks.append(_placeholder_block(section))
    if preserve_existing and base_body is not None:
        for extra in base_sections:
            if not any(
                heading_matches(extra.heading, sec.heading, sec.renamed_from)
                for sec in descriptor.sections
            ):
                blocks.append(f"## {extra.heading}\n{extra.content}".rstrip("\n"))
    return "\n\n".join(blocks).rstrip("\n") + "\n"


def check_required_sections(
    descriptor: TemplateDescriptor,
    body: str,
    *,
    provided_headings: set[str] | None = None,
    require_provided: bool = False,
    subject: str | None = None,
) -> None:
    """Refuse when a template-required section is missing or empty (AGENT-018).

    AGENT_READINESS §3.4 rules 5–6.  With ``require_provided`` (``--section*``
    authoring) a required section without a provided entry is a refusal; the
    body check still applies to the entries that were provided.  Without it
    (``--strict``) every required section must be filled in the assembled
    ``body`` — empty, whitespace-only, HTML-comment-only or placeholder-only
    counts as unfilled (:func:`is_section_unfilled`).  Raises
    ``OperationRefused`` (``E-SECTION-REQUIRED-EMPTY``) and writes nothing;
    ``details`` carries ``missing_required`` plus the template's section
    specification so agents can self-correct.
    """
    sections = parse_sections(body)
    missing: list[str] = []
    for section in descriptor.sections:
        if not section.required:
            continue
        if (
            require_provided
            and provided_headings is not None
            and section.heading not in provided_headings
        ):
            missing.append(section.heading)
            continue
        found = find_section(sections, section.heading, section.renamed_from)
        if found is None or is_section_unfilled(found.content, section.placeholder):
            missing.append(section.heading)
    if not missing:
        return
    raise OperationRefused(
        Finding(
            code="E-SECTION-REQUIRED-EMPTY",
            severity="E",
            subject=subject or f"{descriptor.name}/v{descriptor.version}",
            message=(
                f"required section(s) {', '.join(repr(h) for h in missing)} "
                f"of template {descriptor.name!r} v{descriptor.version} "
                "are missing or empty"
            ),
            details={
                "missing_required": missing,
                "template": {"name": descriptor.name, "version": descriptor.version},
                "template_sections": [
                    sec.model_dump(mode="json") for sec in descriptor.sections
                ],
            },
        )
    )


def prepare_whole_body(raw_body: str, *, title: str) -> tuple[str, list[str]]:
    """Prepare whole-body input for ``--body``/``--body-file`` (AGENT-019).

    AGENT_READINESS §3.4 rule 4.  LF normalisation only — the prose is stored
    as sent (§21.5 step 4).  The tool owns the H1 (§5.6): when the first
    non-blank line is an ATX level-1 heading it is replaced by ``# {title}``
    — with a notice when the heading text differed — otherwise ``# {title}``
    is prepended.  The returned text always ends with a newline.
    """
    text = raw_body.replace("\r\n", "\n").replace("\r", "\n")
    notices: list[str] = []
    lines = text.split("\n")
    first = -1
    for index, line in enumerate(lines):
        if line.strip():
            first = index
            break
    if first >= 0 and _is_atx_h1(lines[first]):
        old_title = lines[first][1:].strip()
        lines[first] = f"# {title}"
        if old_title != title:
            notices.append(f"replaced H1 {old_title!r} with {title!r}")
        body = "\n".join(lines)
    else:
        rest = text.lstrip("\n")
        body = f"# {title}\n\n{rest}" if rest else f"# {title}\n"
    if not body.endswith("\n"):
        body = f"{body}\n"
    return body, notices
