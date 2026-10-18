"""Tests for ``gregraph.cli.prompts`` (spec §13 interactivity, §16.1).

Filtered numbered pickers accept a number, an exact ID, or a refined filter
string; ``q`` cancels; scripted stdin drives every case. Text prompts handle
defaults, required values, and EOF as cancel.
"""

from __future__ import annotations

import io

from gregraph.cli.prompts import PickRow, pick, prompt_text


class FakeTTY(io.StringIO):
    """Scripted stdin that reports itself as a terminal."""

    def isatty(self) -> bool:  # noqa: D102
        return True


ROWS = [
    PickRow(
        key="RE-STORY-AAAAAA",
        type="user-story",
        title="Upload from the desktop",
        status="active",
    ),
    PickRow(
        key="RE-FEAT-BBBBBB", type="feature", title="Upload documents", status="draft"
    ),
    PickRow(
        key="RE-ASM-CCCCCC", type="assumption", title="Modern browsers", status="active"
    ),
]


def run_pick(
    script: str, rows: list[PickRow] | None = None
) -> tuple[PickRow | None, str]:
    stdin, stdout = FakeTTY(script), io.StringIO()
    chosen = pick(
        "pick a document",
        rows if rows is not None else ROWS,
        stdin=stdin,
        stdout=stdout,
    )
    return chosen, stdout.getvalue()


# --------------------------------------------------------------------------
# pickers
# --------------------------------------------------------------------------


def test_pick_accepts_number() -> None:
    chosen, display = run_pick("2\n")
    assert chosen is not None
    assert chosen.key == "RE-FEAT-BBBBBB"
    assert "RE-STORY-AAAAAA" in display
    assert "Upload from the desktop" in display


def test_pick_accepts_exact_id_case_insensitive() -> None:
    chosen, _ = run_pick("re-asm-cccccc\n")
    assert chosen is not None
    assert chosen.key == "RE-ASM-CCCCCC"


def test_pick_filter_refines_then_number_selects() -> None:
    chosen, display = run_pick("upload\n1\n")
    assert chosen is not None
    assert chosen.key == "RE-STORY-AAAAAA"
    assert display.count("RE-FEAT-BBBBBB") == 2
    assert display.count("RE-ASM-CCCCCC") == 1


def test_pick_filter_matches_type_title_status_columns() -> None:
    chosen, _ = run_pick("draft\n1\n")
    assert chosen is not None
    assert chosen.key == "RE-FEAT-BBBBBB"


def test_pick_filter_no_matches_redisplays_full_list() -> None:
    chosen, display = run_pick("zzz\n3\n")
    assert chosen is not None
    assert chosen.key == "RE-ASM-CCCCCC"
    assert display.count("RE-STORY-AAAAAA") >= 2


def test_pick_exact_id_beats_filter_and_works_after_refining() -> None:
    chosen, _ = run_pick("upload\nRE-ASM-CCCCCC\n")
    assert chosen is not None
    assert chosen.key == "RE-ASM-CCCCCC"


def test_pick_q_cancels() -> None:
    chosen, _ = run_pick("q\n")
    assert chosen is None
    chosen, _ = run_pick("99\nQ\n")
    assert chosen is None


def test_pick_eof_cancels() -> None:
    chosen, _ = run_pick("")
    assert chosen is None


def test_pick_invalid_number_reprompts() -> None:
    chosen, display = run_pick("9\n1\n")
    assert chosen is not None
    assert chosen.key == "RE-STORY-AAAAAA"
    assert "invalid" in display


def test_pick_empty_line_reprompts() -> None:
    chosen, _ = run_pick("\n2\n")
    assert chosen is not None
    assert chosen.key == "RE-FEAT-BBBBBB"


def test_pick_displays_numbered_columns() -> None:
    _, display = run_pick("q\n")
    assert "1." in display
    assert "RE-STORY-AAAAAA" in display
    assert "user-story" in display
    assert "active" in display


def test_pick_single_row_via_number() -> None:
    chosen, _ = run_pick("1\n", rows=[ROWS[1]])
    assert chosen is not None
    assert chosen.key == "RE-FEAT-BBBBBB"


# --------------------------------------------------------------------------
# text prompts
# --------------------------------------------------------------------------


def test_prompt_text_returns_stripped_value() -> None:
    stdin, stdout = FakeTTY("  My title  \n"), io.StringIO()
    assert prompt_text("title", stdin=stdin, stdout=stdout) == "My title"
    assert "title" in stdout.getvalue()


def test_prompt_text_default_on_empty() -> None:
    stdin, stdout = FakeTTY("\n"), io.StringIO()
    assert (
        prompt_text("title", default="Fallback", stdin=stdin, stdout=stdout)
        == "Fallback"
    )


def test_prompt_text_required_reprompts_until_value() -> None:
    stdin, stdout = FakeTTY("\n\nFilled\n"), io.StringIO()
    assert prompt_text("title", required=True, stdin=stdin, stdout=stdout) == "Filled"
    assert "required" in stdout.getvalue()


def test_prompt_text_eof_cancels() -> None:
    stdin, stdout = FakeTTY(""), io.StringIO()
    assert prompt_text("title", required=True, stdin=stdin, stdout=stdout) is None
