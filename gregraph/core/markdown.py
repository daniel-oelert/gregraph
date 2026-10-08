"""Body normalisation, H1/sections, mentions, asset refs (spec §5.2, §5.6, §5.7).

Uses markdown-it-py + mdit-py-plugins (GFM tables/tasklists) (spec §16.3).
Pure functions, no I/O. Bodies are parsed in their normalised form
(``hashing.normalise_body``, spec §7.3) so line maps and content slices refer
to the canonical body.

ID pattern: ``<PREFIX>-<6 chars Crockford base32>`` (spec §4.1). Matching is
case-insensitive on input and normalised to uppercase (spec §4.5). The
canonical pattern lives in ``core/ids.py``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

from gregraph.core.hashing import normalise_body
from gregraph.core.ids import ID_PATTERN

_ID_RE = re.compile(
    rf"(?<![A-Za-z0-9])({ID_PATTERN.pattern})(?![A-Za-z0-9])",
    re.IGNORECASE | re.ASCII,
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class Section:
    """A level-2 section: exact heading text and its body content (spec §5.2)."""

    heading: str
    content: str


@dataclass(frozen=True)
class Mention:
    """An ID mention found in a body (spec §5.2). Raw match, unfiltered."""

    id: str
    via: Literal["bare", "link"]


@dataclass(frozen=True)
class AssetRef:
    """A body reference landing inside ``assets/<owner>/`` (spec §5.7)."""

    raw: str
    path: Path
    owner: str
    foreign: bool


def _parser() -> MarkdownIt:
    return (
        MarkdownIt("commonmark")
        .enable("table")
        .enable("strikethrough")
        .use(tasklists_plugin)
    )


def _lines(body: str | bytes) -> list[str]:
    text = normalise_body(body)
    lines = text.split("\n")
    return lines[:-1]


def has_front_matter(body: str | bytes) -> bool:
    """Return whether the body starts with ``---`` (E-FRONTMATTER-FORBIDDEN)."""
    return normalise_body(body).startswith("---")


def extract_title(body: str | bytes) -> str | None:
    """Return the title from the first non-blank line (spec §5.6, §5.2).

    The first non-blank line must be a level-1 ATX heading; its inline content
    is the canonical title. Returns ``None`` when it is missing (setext
    headings and deeper levels do not count).
    """
    for line in _lines(body):
        if line.strip():
            break
    else:
        return None
    tokens = _parser().parse(line)
    if not tokens:
        return None
    head = tokens[0]
    if head.type != "heading_open" or head.tag != "h1" or head.markup != "#":
        return None
    for token in tokens[1:]:
        if token.type == "inline":
            return token.content.strip()
    return None


def parse_sections(body: str | bytes) -> list[Section]:
    """Return the top-level level-2 sections in order (spec §5.2, §5.5).

    Heading text is exact after trimming, case-sensitive. Section content runs
    from the heading to the next level-2 heading (level-3+ headings stay inside
    their section). Content before the first level-2 heading belongs to no
    section. Headings inside fenced code or block quotes are ignored.
    """
    lines = _lines(body)
    spans: list[tuple[int, int, str]] = []
    tokens = _parser().parse(normalise_body(body))
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag != "h2" or token.level != 0:
            continue
        if token.map is None:
            continue
        heading = ""
        if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
            heading = tokens[index + 1].content.strip()
        spans.append((token.map[0], token.map[1], heading))
    sections: list[Section] = []
    for i, (_, start, heading) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else len(lines)
        sections.append(Section(heading=heading, content="\n".join(lines[start:end])))
    return sections


def strip_html_comments(content: str) -> str:
    """Return ``content`` with HTML comments removed (spec §5.5)."""
    return _HTML_COMMENT_RE.sub("", content)


def section_is_empty(content: str, placeholder: str = "") -> bool:
    """Return whether a section is empty (spec §5.5).

    A section is empty if its content, after stripping whitespace and HTML
    comments, is empty or equals the placeholder text.
    """
    stripped = strip_html_comments(content).strip()
    return stripped == "" or stripped == placeholder.strip()


def heading_matches(
    candidate: str, heading: str, renamed_from: Sequence[str] = ()
) -> bool:
    """Return whether ``candidate`` matches a section heading or a former name.

    Exact text after trimming, case-sensitive (spec §5.5, §7.7 ``renamed_from``).
    """
    text = candidate.strip()
    return text == heading.strip() or any(text == alt.strip() for alt in renamed_from)


def find_section(
    sections: Sequence[Section], heading: str, renamed_from: Sequence[str] = ()
) -> Section | None:
    """Return the first section matching ``heading`` or a ``renamed_from`` name."""
    for section in sections:
        if heading_matches(section.heading, heading, renamed_from):
            return section
    return None


def _resolve_target(target: str, doc_path: Path) -> Path | None:
    split = urlsplit(target)
    if split.scheme or split.netloc or split.path.startswith("/"):
        return None
    rel = unquote(split.path)
    if not rel:
        return None
    parts = [p for p in doc_path.parent.parts if p not in ("", ".")]
    for part in PurePosixPath(rel).parts:
        if part == "..":
            if parts:
                parts.pop()
            else:
                parts.append("..")
        elif part != ".":
            parts.append(part)
    if not parts:
        return None
    return Path(*parts)


def _asset_owner(resolved: Path | None) -> str | None:
    if resolved is None:
        return None
    parts = resolved.parts
    if len(parts) >= 3 and parts[0] == "assets":
        return parts[1]
    return None


def resolve_asset_ref(target: str, *, doc_path: Path, doc_id: str) -> AssetRef | None:
    """Resolve one link/image target against the document (spec §5.7).

    Returns the reference if the target lands inside ``assets/<owner>/`` after
    lexical normalisation; ``foreign`` marks another document's asset folder
    (E-ASSET-FOREIGN). External, absolute, and non-asset targets return
    ``None``.
    """
    resolved = _resolve_target(target, doc_path)
    owner = _asset_owner(resolved)
    if owner is None or resolved is None:
        return None
    return AssetRef(
        raw=target,
        path=resolved,
        owner=owner,
        foreign=owner.lower() != doc_id.lower(),
    )


def find_asset_refs(
    body: str | bytes, *, doc_path: Path, doc_id: str
) -> list[AssetRef]:
    """Return asset references from images and links in document order (spec §5.7)."""
    text = normalise_body(body)
    refs: list[AssetRef] = []
    for token in _parser().parse(text):
        if token.type != "inline" or not token.children:
            continue
        for child in token.children:
            if child.type == "image":
                target = child.attrGet("src")
            elif child.type == "link_open":
                target = child.attrGet("href")
            else:
                continue
            if not isinstance(target, str) or not target:
                continue
            ref = resolve_asset_ref(target, doc_path=doc_path, doc_id=doc_id)
            if ref is not None:
                refs.append(ref)
    return refs


def find_mentions(body: str | bytes, *, doc_path: Path) -> list[Mention]:
    """Return raw ID mentions from bare text and link targets (spec §5.2).

    Unique ``(id, via)`` matches in first-seen order, IDs uppercased. Bare IDs
    in code spans, fenced code, and HTML are not mentions. Image references
    are asset references, never mentions. Targets landing in ``assets/`` are
    asset references, not mention sources. The caller filters CR IDs and
    existence (W-MENTION-UNLINKED, E-MENTION-UNKNOWN).
    """
    text = normalise_body(body)
    seen: dict[tuple[str, str], Mention] = {}
    for token in _parser().parse(text):
        if token.type != "inline" or not token.children:
            continue
        for child in token.children:
            via: Literal["bare", "link"] | None = None
            source = ""
            if child.type == "text":
                via = "bare"
                source = child.content
            elif child.type == "link_open":
                href = child.attrGet("href")
                source = href if isinstance(href, str) else ""
                if source and _asset_owner(_resolve_target(source, doc_path)) is None:
                    via = "link"
            if via is None:
                continue
            for match in _ID_RE.finditer(source):
                mention = Mention(id=match.group(1).upper(), via=via)
                seen.setdefault((mention.id, mention.via), mention)
    return list(seen.values())
