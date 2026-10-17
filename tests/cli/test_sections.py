"""Tests for ``gregraph.cli.commands.sections`` (AGENT_READINESS §3.4).

Pure-syntax parsing of the template-guided authoring flags: ``--section``
``HEADING=CONTENT`` pairs, ``--section-file`` ``HEADING=PATH`` pairs (files
read through ``gregraph.core.storage.read_text_file``, ``-`` reads stdin),
the whole-body ``--body``/``--body-file`` pair, the §3.4 rule-1/7 refusal
combinations (exit 2 ``UsageError``) and CRLF normalisation. Heading
resolution against the pinned template happens in core, not here.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest

from gregraph.cli.commands.sections import ParsedContentArgs, parse_content_args
from gregraph.cli.main import UsageError


def make_args(**overrides: object) -> argparse.Namespace:
    """A Namespace with the authoring flags at their parser defaults."""
    values: dict[str, object] = {
        "section": [],
        "section_file": [],
        "body": None,
        "body_file": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_no_flags_is_empty_and_unflagged() -> None:
    parsed = parse_content_args(make_args())
    assert parsed == ParsedContentArgs(
        sections=(), body_text=None, has_content_flags=False
    )


def test_section_splits_on_the_first_equals() -> None:
    parsed = parse_content_args(make_args(section=["Story=A=B"]))
    assert parsed.sections == (("Story", "A=B"),)
    assert parsed.body_text is None
    assert parsed.has_content_flags is True


def test_sections_keep_given_order_and_are_trimmed_in_heading() -> None:
    parsed = parse_content_args(make_args(section=["  Story =first", "Notes=second"]))
    assert parsed.sections == (("Story", "first"), ("Notes", "second"))


def test_section_file_reads_through_core_storage(tmp_path: Path) -> None:
    path = tmp_path / "content.md"
    path.write_text("file content\r\nsecond\r", encoding="utf-8")
    parsed = parse_content_args(make_args(section_file=[f"Story={path}"]))
    assert parsed.sections == (("Story", "file content\nsecond\n"),)


def test_section_file_dash_reads_stdin() -> None:
    parsed = parse_content_args(
        make_args(section_file=["Story=-"]),
        stdin=io.StringIO("from stdin\r\n"),
    )
    assert parsed.sections == (("Story", "from stdin\n"),)


def test_body_text_is_normalised() -> None:
    parsed = parse_content_args(make_args(body="line\r\nother\r"))
    assert parsed.body_text == "line\nother\n"
    assert parsed.sections == ()
    assert parsed.has_content_flags is True


def test_body_file_dash_reads_stdin() -> None:
    parsed = parse_content_args(
        make_args(body_file="-"), stdin=io.StringIO("whole body\n")
    )
    assert parsed.body_text == "whole body\n"


def test_body_and_body_file_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(body="text", body_file="path"))


def test_body_and_section_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(body="text", section=["H=C"]))


def test_body_file_and_section_file_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(body_file="-", section_file=["H=-"]))


def test_two_stdin_consumers_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(section_file=["A=-", "B=-"]), stdin=io.StringIO())


def test_malformed_section_without_equals_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(section=["JustHeading"]))


def test_malformed_section_with_empty_heading_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(section=["=content"]))


def test_malformed_section_file_with_empty_path_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(section_file=["Story="]))


def test_duplicate_trimmed_heading_refused() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(section=["Story=one", " Story =two"]))


def test_duplicate_heading_across_section_and_section_file_refused(
    tmp_path: Path,
) -> None:
    path = tmp_path / "c.md"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(UsageError):
        parse_content_args(
            make_args(section=["Story=one"], section_file=[f"Story={path}"])
        )


def test_section_dash_content_is_literal_not_stdin() -> None:
    parsed = parse_content_args(
        make_args(section=["Story=-"]), stdin=io.StringIO("not this")
    )
    assert parsed.sections == (("Story", "-"),)


def test_allow_body_false_refuses_body_flags() -> None:
    with pytest.raises(UsageError):
        parse_content_args(make_args(body="text"), allow_body=False)
    with pytest.raises(UsageError):
        parse_content_args(make_args(body_file="p"), allow_body=False)
    parsed = parse_content_args(
        make_args(section=["H=C"], body=None, body_file=None), allow_body=False
    )
    assert parsed.sections == (("H", "C"),)


def test_empty_stdin_section_file_gives_empty_content() -> None:
    parsed = parse_content_args(
        make_args(section_file=["Notes=-"]), stdin=io.StringIO("")
    )
    assert parsed.sections == (("Notes", ""),)
