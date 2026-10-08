"""Tests for ``gregraph.core.hashing`` (spec §7.3, §5.7)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from gregraph.core.hashing import (
    asset_hash,
    body_hash,
    effective_content_changed,
    normalise_body,
)

_SHA = re.compile(r"sha256:[0-9a-f]{64}")


def test_normalise_body_converts_crlf() -> None:
    assert normalise_body("# T\r\n\r\nBody  \r\n") == "# T\n\nBody\n"


def test_normalise_body_converts_bare_cr() -> None:
    assert normalise_body("# T\rBody\r") == "# T\nBody\n"


def test_normalise_body_decodes_utf8_bytes() -> None:
    assert normalise_body("# Ünicode\n") == "# Ünicode\n"
    assert normalise_body("# Ünicode\r\n".encode()) == "# Ünicode\n"


def test_normalise_body_strips_trailing_whitespace_per_line() -> None:
    assert normalise_body("a  \n\tb\t\n c \n") == "a\n\tb\n c\n"


def test_normalise_body_collapses_three_blanks_to_two() -> None:
    assert normalise_body("a\n\n\n\n\nb\n") == "a\n\n\nb\n"
    assert normalise_body("a\n\n\nb\n") == "a\n\n\nb\n"
    assert normalise_body("a\n\nb\n") == "a\n\nb\n"
    assert normalise_body("a\nb\n") == "a\nb\n"


def test_normalise_body_whitespace_only_lines_are_blank() -> None:
    assert normalise_body("a\n   \n\t\n\nb\n") == "a\n\n\nb\n"


def test_normalise_body_exactly_one_trailing_newline() -> None:
    assert normalise_body("a") == "a\n"
    assert normalise_body("a\n") == "a\n"
    assert normalise_body("a\n\n") == "a\n"
    assert normalise_body("a\n\n\n") == "a\n"


def test_normalise_body_empty_and_blank_only() -> None:
    assert normalise_body("") == "\n"
    assert normalise_body("\n") == "\n"
    assert normalise_body("\n\n\n") == "\n"


def test_normalise_body_keeps_h1() -> None:
    assert normalise_body("# Title\n\nBody\n") == "# Title\n\nBody\n"


@given(st.text())
def test_normalise_body_idempotent_text(body: str) -> None:
    once = normalise_body(body)
    assert normalise_body(once) == once


@given(st.binary())
def test_normalise_body_idempotent_bytes_when_decodable(data: bytes) -> None:
    try:
        body = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    once = normalise_body(body)
    assert normalise_body(once) == once


def test_body_hash_format() -> None:
    assert _SHA.fullmatch(body_hash("# T\n")) is not None


def test_body_hash_golden_value() -> None:
    expected = "sha256:" + hashlib.sha256(b"# T\n").hexdigest()
    assert body_hash("# T\n") == expected


def test_body_hash_normalises_line_endings() -> None:
    assert body_hash("# T\r\nBody\r\n") == body_hash("# T\nBody\n")


def test_body_hash_includes_h1() -> None:
    assert body_hash("# Old title\n\nBody\n") != body_hash("# New title\n\nBody\n")


def test_asset_hash_is_raw_bytes() -> None:
    data = b"\x00\r\n\xff"
    assert asset_hash(data) == "sha256:" + hashlib.sha256(data).hexdigest()


def test_asset_hash_does_not_normalise() -> None:
    assert asset_hash(b"a\r\n") != body_hash("a\r\n")


def test_effective_content_changed_unchanged() -> None:
    assets = [(Path("a.png"), "sha256:aa"), (Path("b.png"), "sha256:bb")]
    assert not effective_content_changed("sha256:x", assets, "sha256:x", list(assets))


def test_effective_content_changed_body_differs() -> None:
    assert effective_content_changed("sha256:x", [], "sha256:y", [])


def test_effective_content_changed_asset_hash_differs() -> None:
    old = [(Path("a.png"), "sha256:aa")]
    new = [(Path("a.png"), "sha256:cc")]
    assert effective_content_changed("sha256:x", old, "sha256:x", new)


def test_effective_content_changed_asset_path_differs() -> None:
    old = [(Path("a.png"), "sha256:aa")]
    new = [(Path("b.png"), "sha256:aa")]
    assert effective_content_changed("sha256:x", old, "sha256:x", new)


def test_effective_content_changed_asset_added() -> None:
    old = [(Path("a.png"), "sha256:aa")]
    new = [(Path("a.png"), "sha256:aa"), (Path("b.png"), "sha256:bb")]
    assert effective_content_changed("sha256:x", old, "sha256:x", new)


def test_effective_content_changed_ignores_asset_order() -> None:
    old = [(Path("a.png"), "sha256:aa"), (Path("b.png"), "sha256:bb")]
    new = [(Path("b.png"), "sha256:bb"), (Path("a.png"), "sha256:aa")]
    assert not effective_content_changed("sha256:x", old, "sha256:x", new)
