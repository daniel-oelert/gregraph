"""Tests for ``gregraph.core.markdown`` (spec §5.2, §5.5, §5.6, §5.7)."""

from __future__ import annotations

from pathlib import Path

from gregraph.core.markdown import (
    AssetRef,
    Mention,
    extract_title,
    find_asset_refs,
    find_mentions,
    find_section,
    has_front_matter,
    heading_matches,
    parse_sections,
    resolve_asset_ref,
    section_is_empty,
    strip_html_comments,
)

DOC = Path("documents/user-stories/RE-7F3K2Q.md")
DOC_ID = "RE-7F3K2Q"


def test_extract_title_simple() -> None:
    assert extract_title("# Upload the knowledge base\n\nBody\n") == (
        "Upload the knowledge base"
    )


def test_extract_title_blank_lines_before_h1() -> None:
    assert extract_title("\n\n# Title\nBody\n") == "Title"


def test_extract_title_missing_h1() -> None:
    assert extract_title("Body first\n# Title\n") is None
    assert extract_title("## Sub\n") is None
    assert extract_title("") is None


def test_extract_title_front_matter_start() -> None:
    assert extract_title("---\ntitle: x\n---\n# Title\n") is None


def test_extract_title_closing_sequence() -> None:
    assert extract_title("# Title #\n") == "Title"
    assert extract_title("# Title ###\n") == "Title"
    assert extract_title("# C# idiom\n") == "C# idiom"


def test_extract_title_requires_space_after_hash() -> None:
    assert extract_title("#Title\n") is None


def test_extract_title_setext_not_atx() -> None:
    assert extract_title("Title\n=====\n") is None


def test_extract_title_empty_atx_h1() -> None:
    assert extract_title("#\n") == ""
    assert extract_title("# \n") == ""


def test_extract_title_bytes_crlf() -> None:
    assert extract_title(b"# Title\r\nBody\r\n") == "Title"


def test_extract_title_trims_whitespace() -> None:
    assert extract_title("#   Title  \n") == "Title"


def test_has_front_matter() -> None:
    assert has_front_matter("---\ntitle: x\n---\n")
    assert has_front_matter("---foo\n")
    assert has_front_matter(b"---\r\n")


def test_has_front_matter_false() -> None:
    assert not has_front_matter("# T\n")
    assert not has_front_matter("\n---\n")
    assert not has_front_matter("# T\n\n---\n")


BODY = """# Title

Intro text.

## Story

As a user...

### Sub note

More.

## Acceptance criteria

Given ...
"""


def test_parse_sections_order_and_headings() -> None:
    sections = parse_sections(BODY)
    assert [s.heading for s in sections] == ["Story", "Acceptance criteria"]


def test_parse_sections_content_spans_to_next_heading() -> None:
    sections = parse_sections(BODY)
    assert "As a user..." in sections[0].content
    assert "### Sub note" in sections[0].content
    assert "More." in sections[0].content
    assert "Given ..." in sections[1].content
    assert "As a user..." not in sections[1].content
    assert "Intro text." not in sections[0].content


def test_parse_sections_trims_heading_text() -> None:
    sections = parse_sections("# T\n\n##   Spaced   ##\n\ntext\n")
    assert [s.heading for s in sections] == ["Spaced"]


def test_parse_sections_ignores_fenced_code() -> None:
    body = "# T\n\n```\n## not a section\n```\n\n## Real\n\ntext\n"
    assert [s.heading for s in parse_sections(body)] == ["Real"]


def test_parse_sections_case_sensitive_headings() -> None:
    sections = parse_sections("# T\n\n## story\n\ntext\n")
    assert sections[0].heading == "story"
    assert not heading_matches(sections[0].heading, "Story")


def test_parse_sections_setext_h2_counted() -> None:
    sections = parse_sections("# T\n\nIntro\n------\n\ntext\n")
    assert [s.heading for s in sections] == ["Intro"]


def test_parse_sections_empty_list_without_h2() -> None:
    assert parse_sections("# T\n\nJust text\n") == []


def test_strip_html_comments() -> None:
    assert strip_html_comments("a <!-- x --> b\n<!-- multi\nline -->c") == "a  b\nc"


def test_section_is_empty_whitespace_only() -> None:
    assert section_is_empty("", "placeholder")
    assert section_is_empty("  \n\t\n", "placeholder")


def test_section_is_empty_comments_only() -> None:
    assert section_is_empty("<!-- note -->\n", "placeholder")
    assert section_is_empty("<!-- one -->\n\n<!-- two -->", "placeholder")


def test_section_is_empty_placeholder_only() -> None:
    placeholder = "As a <role>, I want <capability>, so that <benefit>."
    assert section_is_empty(f"  {placeholder}  \n", placeholder)
    assert section_is_empty(f"{placeholder}\n\n<!-- todo -->", placeholder)


def test_section_is_empty_filled() -> None:
    placeholder = "As a <role>, I want <capability>, so that <benefit>."
    assert not section_is_empty("Real content", placeholder)
    assert not section_is_empty(f"{placeholder} plus more", placeholder)
    assert not section_is_empty("x", "")


def test_heading_matches_current_and_renamed() -> None:
    assert heading_matches("Rationale", "Rationale")
    assert heading_matches(" Motivation ", "Rationale", ["Motivation"])
    assert not heading_matches("motivation", "Rationale", ["Motivation"])
    assert not heading_matches("Other", "Rationale", ["Motivation"])


def test_find_section_by_renamed_heading() -> None:
    sections = parse_sections("# T\n\n## Motivation\n\nwhy\n")
    found = find_section(sections, "Rationale", ["Motivation"])
    assert found is not None
    assert found.content.strip() == "why"
    assert find_section(sections, "Notes") is None


def test_find_mentions_bare_id() -> None:
    mentions = find_mentions("See RE-7F3K2Q for details.", doc_path=DOC)
    assert mentions == [Mention("RE-7F3K2Q", "bare")]


def test_find_mentions_case_insensitive_normalised() -> None:
    mentions = find_mentions("see re-7f3k2q now", doc_path=DOC)
    assert mentions == [Mention("RE-7F3K2Q", "bare")]


def test_find_mentions_prefix_length_variants() -> None:
    body = "A-7F3K2Q AB-7F3K2Q ABCDEF-7F3K2Q"
    assert [m.id for m in find_mentions(body, doc_path=DOC)] == [
        "A-7F3K2Q",
        "AB-7F3K2Q",
        "ABCDEF-7F3K2Q",
    ]


def test_find_mentions_ignores_code_span_and_fence() -> None:
    assert find_mentions("`RE-7F3K2Q`", doc_path=DOC) == []
    assert find_mentions("```\nRE-7F3K2Q\n```\n", doc_path=DOC) == []


def test_find_mentions_markdown_link_to_id() -> None:
    mentions = find_mentions("[x](../features/RE-2K7QMB.md)", doc_path=DOC)
    assert mentions == [Mention("RE-2K7QMB", "link")]


def test_find_mentions_link_text_and_href() -> None:
    body = "[RE-7F3K2Q](../features/RE-2K7QMB.md)"
    assert set(find_mentions(body, doc_path=DOC)) == {
        Mention("RE-7F3K2Q", "bare"),
        Mention("RE-2K7QMB", "link"),
    }


def test_find_mentions_link_href_lowercase() -> None:
    body = "[see](../features/re-2k7qmb.md)"
    assert find_mentions(body, doc_path=DOC) == [Mention("RE-2K7QMB", "link")]


def test_find_mentions_deduplicates() -> None:
    body = "RE-7F3K2Q and RE-7F3K2Q again"
    assert find_mentions(body, doc_path=DOC) == [Mention("RE-7F3K2Q", "bare")]


def test_find_mentions_returns_cr_ids_raw() -> None:
    body = "RE-3M9XA1 and RE-7F3K2Q"
    assert [m.id for m in find_mentions(body, doc_path=DOC)] == [
        "RE-3M9XA1",
        "RE-7F3K2Q",
    ]


def test_find_mentions_image_assets_do_not_mention() -> None:
    body = "![a](../../assets/RE-7F3K2Q/f.png) and [d](../../assets/RE-2K7QMB/g.png)"
    assert find_mentions(body, doc_path=DOC) == []


def test_find_mentions_rejects_non_ids() -> None:
    assert find_mentions("7F3K2Q", doc_path=DOC) == []
    assert find_mentions("RE-7F3K2", doc_path=DOC) == []
    assert find_mentions("RE-7F3K2QX", doc_path=DOC) == []
    assert find_mentions("RE-7F3K2I", doc_path=DOC) == []
    assert find_mentions("RE-7F3K2U", doc_path=DOC) == []
    assert find_mentions("RE-7F3K2O", doc_path=DOC) == []


def test_find_mentions_boundaries() -> None:
    body = "(RE-7F3K2Q) and RE-7F3K2Q.md"
    assert find_mentions(body, doc_path=DOC) == [Mention("RE-7F3K2Q", "bare")]


def test_find_mentions_glued_word_is_raw_match() -> None:
    body = "seeRE-7F3K2Q"
    assert find_mentions(body, doc_path=DOC) == [Mention("SEERE-7F3K2Q", "bare")]


def test_find_mentions_in_heading() -> None:
    body = "## See RE-7F3K2Q\n\ntext\n"
    assert [m.id for m in find_mentions(body, doc_path=DOC)] == ["RE-7F3K2Q"]


def test_resolve_asset_ref_own_folder() -> None:
    ref = resolve_asset_ref(
        "../../assets/RE-7F3K2Q/file.png", doc_path=DOC, doc_id=DOC_ID
    )
    assert ref == AssetRef(
        raw="../../assets/RE-7F3K2Q/file.png",
        path=Path("assets/RE-7F3K2Q/file.png"),
        owner="RE-7F3K2Q",
        foreign=False,
    )


def test_resolve_asset_ref_foreign_folder() -> None:
    ref = resolve_asset_ref(
        "../../assets/RE-2K7QMB/file.png", doc_path=DOC, doc_id=DOC_ID
    )
    assert ref is not None
    assert ref.owner == "RE-2K7QMB"
    assert ref.foreign


def test_resolve_asset_ref_owner_case_insensitive() -> None:
    ref = resolve_asset_ref(
        "../../assets/re-7f3k2q/file.png", doc_path=DOC, doc_id=DOC_ID
    )
    assert ref is not None
    assert not ref.foreign


def test_resolve_asset_ref_nested_dotdot_normalisation() -> None:
    ref = resolve_asset_ref(
        "../../documents/../assets/RE-7F3K2Q/./sub/../file.png",
        doc_path=DOC,
        doc_id=DOC_ID,
    )
    assert ref is not None
    assert ref.path == Path("assets/RE-7F3K2Q/file.png")


def test_resolve_asset_ref_nested_path_kept() -> None:
    ref = resolve_asset_ref(
        "../../assets/RE-7F3K2Q/nested/dir/file.png",
        doc_path=DOC,
        doc_id=DOC_ID,
    )
    assert ref is not None
    assert ref.path == Path("assets/RE-7F3K2Q/nested/dir/file.png")


def test_resolve_asset_ref_non_asset_targets() -> None:
    assert (
        resolve_asset_ref("https://example.com/a.png", doc_path=DOC, doc_id=DOC_ID)
        is None
    )
    assert (
        resolve_asset_ref("/assets/RE-7F3K2Q/f.png", doc_path=DOC, doc_id=DOC_ID)
        is None
    )
    assert (
        resolve_asset_ref("../../assets/file.png", doc_path=DOC, doc_id=DOC_ID) is None
    )
    assert resolve_asset_ref("../RE-2K7QMB.png", doc_path=DOC, doc_id=DOC_ID) is None
    assert (
        resolve_asset_ref(
            "../../../assets/RE-7F3K2Q/file.png", doc_path=DOC, doc_id=DOC_ID
        )
        is None
    )


def test_find_asset_refs_images_and_links() -> None:
    body = (
        "# T\n\n"
        "![a](../../assets/RE-7F3K2Q/f.png)\n\n"
        "[diagram](../../assets/RE-7F3K2Q/g.png)\n\n"
        "![ext](https://example.com/x.png)\n"
    )
    refs = find_asset_refs(body, doc_path=DOC, doc_id=DOC_ID)
    assert [r.path for r in refs] == [
        Path("assets/RE-7F3K2Q/f.png"),
        Path("assets/RE-7F3K2Q/g.png"),
    ]
    assert all(not r.foreign for r in refs)


def test_find_asset_refs_foreign_flagged() -> None:
    body = "![a](../../assets/RE-2K7QMB/f.png)\n"
    refs = find_asset_refs(body, doc_path=DOC, doc_id=DOC_ID)
    assert len(refs) == 1
    assert refs[0].foreign


def test_find_asset_refs_ignores_fenced_code() -> None:
    body = "```\n![a](../../assets/RE-7F3K2Q/f.png)\n```\n"
    assert find_asset_refs(body, doc_path=DOC, doc_id=DOC_ID) == []
