"""Body normalisation, H1/sections, mentions, asset refs (spec §5.2, §5.6, §5.7).

Uses markdown-it-py + mdit-py-plugins (GFM tables/tasklists) (spec §16.3).
Pure functions, no I/O. Bodies are parsed in their normalised form
(``hashing.normalise_body``, spec §7.3) so line maps and content slices refer
to the canonical body.

ID pattern: ``<PREFIX>-<6 chars Crockford base32>`` (spec §4.1). Matching is
case-insensitive on input and normalised to uppercase (spec §4.5); prose
mention matching is explicit-syntax only and case-sensitive (spec §5.2,
D-AGENT-6). The canonical pattern lives in ``core/ids.py``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.tasklists import tasklists_plugin

from gregraph.core.hashing import normalise_body
from gregraph.core.ids import ID_PATTERN

MentionVia = Literal["wikilink", "link"]

# ``[[ID]]`` / ``[[ID|label]]`` — label may hold any non-``]`` text, no newline,
# and must not be empty (spec §5.2). Case-sensitive: canonical uppercase only.
_WIKILINK_CORE = rf"({ID_PATTERN.pattern})(\|[^\]\n]+)?"
_WIKILINK_RE = re.compile(rf"\[\[{_WIKILINK_CORE}\]\]")
# Link-text form of a wikilink: ``[[ID]](x)`` reaches the walker as a link
# whose text token holds the inner ``[ID]`` brackets (markdown-it nests them).
_WIKILINK_TEXT_RE = re.compile(rf"\[{_WIKILINK_CORE}\]")
_HTML_TAG_RE = re.compile(r"</?([A-Za-z][A-Za-z0-9]*)[^>]*>")
_HTML_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class Section:
    """A level-2 section: exact heading text and its body content (spec §5.2)."""

    heading: str
    content: str


@dataclass(frozen=True)
class Mention:
    """An explicit ID mention found in a body (spec §5.2). Raw match, unfiltered."""

    id: str
    via: MentionVia


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


def _html_tag_state(content: str, in_html: bool) -> bool:
    """Return the inline-HTML open state after one ``html_inline`` token.

    Opening tags switch the state on (except void and self-closing tags),
    closing tags switch it off; comments and other raw HTML leave it as it
    is. Text between inline tags is inside HTML for mention purposes
    (spec §5.2, D-AGENT-6).
    """
    if content.startswith("<!--"):
        return in_html
    match = _HTML_TAG_RE.fullmatch(content)
    if match is None:
        return in_html
    if content.startswith("</"):
        return False
    if content.rstrip().endswith("/>"):
        return in_html
    if match.group(1).lower() in _HTML_VOID_ELEMENTS:
        return in_html
    return True


def _mentions_from_link(
    children: Sequence[Token],
    start: int,
    doc_path: Path,
    record: Callable[[str, MentionVia], None],
) -> int:
    """Record mentions from one Markdown link, returning the next child index.

    The target rules run first and an asset target never counts (spec §5.2):
    a trimmed target matching the ID pattern, or a relative target resolving
    to a ``.md`` path whose stem matches the ID pattern. Then the link text:
    a bracket-wrapped ``[ID]``/``[ID|label]`` is the ``[[ID]](x)`` wikilink
    form, a whole-text ID is an ordinary link mention, and ``[[ID]]`` inside
    longer link text is a wikilink in its own right.
    """
    href_attr = children[start].attrGet("href")
    href = href_attr if isinstance(href_attr, str) else ""
    resolved = _resolve_target(href, doc_path)
    is_asset = _asset_owner(resolved) is not None
    if not is_asset:
        target = href.strip()
        if ID_PATTERN.fullmatch(target):
            record(target, "link")
        elif (
            resolved is not None
            and resolved.name.endswith(".md")
            and ID_PATTERN.fullmatch(resolved.stem)
        ):
            record(resolved.stem, "link")
    end = start + 1
    while end < len(children) and children[end].type != "link_close":
        end += 1
    link_text = "".join(
        child.content for child in children[start + 1 : end] if child.type == "text"
    )
    inner = link_text.strip()
    wrapped = _WIKILINK_TEXT_RE.fullmatch(inner)
    if wrapped is not None:
        record(wrapped.group(1), "wikilink")
    elif not is_asset and ID_PATTERN.fullmatch(inner):
        record(inner, "link")
    for child in children[start + 1 : end]:
        if child.type == "text":
            for match in _WIKILINK_RE.finditer(child.content):
                record(match.group(1), "wikilink")
    return end + 1


def find_mentions(body: str | bytes, *, doc_path: Path) -> list[Mention]:
    """Return explicit ID mentions from wikilinks and links (spec §5.2, D-AGENT-6).

    A mention is recognised only in explicit reference syntax, and only for
    canonical uppercase IDs (case-sensitive matching of ``ID_PATTERN``):

    - the wikilink ``[[ID]]`` or ``[[ID|label]]``;
    - a Markdown link ``[text](target)`` whose trimmed target matches the ID
      pattern, whose relative target resolves against ``doc_path`` to a
      ``.md`` path with an ID stem, or whose trimmed link text matches the ID
      pattern.

    ``[[ID]](x)`` is the wikilink (markdown-it nests the inner brackets into
    the link text token); the target ``x`` is not a mention. Bare ID-shaped
    tokens in prose and headings are not mentions. Code spans, fenced code,
    and HTML are excluded by the token walk; image references are asset
    references, and targets landing in ``assets/`` are asset references,
    never mention sources. Unique ``(id, via)`` matches in first-seen order.
    The caller filters CR IDs and existence (W-MENTION-UNLINKED,
    E-MENTION-UNKNOWN).
    """
    text = normalise_body(body)
    seen: dict[tuple[str, MentionVia], Mention] = {}

    def record(mention_id: str, via: MentionVia) -> None:
        seen.setdefault((mention_id, via), Mention(id=mention_id, via=via))

    for token in _parser().parse(text):
        children = token.children
        if token.type != "inline" or children is None:
            continue
        index = 0
        in_html = False
        while index < len(children):
            child = children[index]
            if child.type == "html_inline":
                in_html = _html_tag_state(child.content, in_html)
                index += 1
                continue
            if in_html:
                index += 1
                continue
            if child.type == "link_open":
                index = _mentions_from_link(children, index, doc_path, record)
                continue
            if child.type == "text":
                for match in _WIKILINK_RE.finditer(child.content):
                    record(match.group(1), "wikilink")
            index += 1
    return list(seen.values())
