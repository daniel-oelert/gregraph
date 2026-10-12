"""TTY prompts and pickers, stdlib only (spec §13 interactivity, §16.1).

Interactive selection happens here in ``cli`` *before* calling
``core.operations`` (spec §16.2). Every prompt has a flag equivalent (spec §13
general rules): commands pass flag values instead of prompting whenever the
flag is given. Pickers show a filtered numbered list (ID, type, title, status)
and accept a number, an exact ID, or a refined filter string; ``q`` cancels.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

CANCEL_KEY = "q"
_CANCELLED_MESSAGE = "cancelled"


@dataclass(frozen=True)
class PickRow:
    """One picker row: the identifying key plus display columns (spec §13)."""

    key: str
    type: str = ""
    title: str = ""
    status: str = ""

    def matches(self, needle: str) -> bool:
        """Whether ``needle`` occurs in any display column (case-insensitive)."""
        folded = needle.casefold()
        return any(
            folded in cell.casefold()
            for cell in (self.key, self.type, self.title, self.status)
        )


def _print_row_columns(rows: Sequence[PickRow], *, start: int, stdout: TextIO) -> None:
    keys = [f"{index}." for index in range(start, start + len(rows))]
    widths = [3, len("ID"), len("TYPE"), len("TITLE"), len("STATUS")]
    for number, row in zip(keys, rows, strict=True):
        cells = (number, row.key, row.type, row.title, row.status)
        widths = [
            max(width, len(cell)) for width, cell in zip(widths, cells, strict=True)
        ]
    for number, row in zip(keys, rows, strict=True):
        cells = (number, row.key, row.type, row.title, row.status)
        print(
            "  "
            + "  ".join(
                cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
            ),
            file=stdout,
        )


def pick(
    label: str,
    rows: Sequence[PickRow],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> PickRow | None:
    """Filtered numbered picker (spec §13 general rules).

    Shows ``label`` and a numbered list of ``rows`` (ID, type, title, status).
    Accepts the displayed number, an exact key (case-insensitive, searched in
    the full row set), or a filter string that refines the displayed list;
    ``q`` cancels and returns ``None`` (so does end-of-input).
    """
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    all_rows = list(rows)
    current = list(all_rows)
    while True:
        print(f"{label} (number, ID, filter, or q):", file=sink)
        if not current:
            print("  (no candidates)", file=sink)
        _print_row_columns(current, start=1, stdout=sink)
        print("> ", end="", file=sink)
        line = source.readline()
        if line == "":
            return None
        text = line.strip()
        if text == "":
            print("enter a number, an ID, a filter, or q", file=sink)
            continue
        if text.casefold() == CANCEL_KEY:
            print(_CANCELLED_MESSAGE, file=sink)
            return None
        if text.isdigit():
            index = int(text)
            if 1 <= index <= len(current):
                return current[index - 1]
            print(f"invalid selection: {text}", file=sink)
            continue
        for row in all_rows:
            if row.key.casefold() == text.casefold():
                return row
        refined = [row for row in current if row.matches(text)]
        if not refined:
            print(f"no matches for {text!r}", file=sink)
            continue
        current = refined


def prompt_text(
    label: str,
    *,
    default: str | None = None,
    required: bool = False,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> str | None:
    """One-line text prompt; ``None`` when input ends (caller treats as cancel).

    An empty line returns ``default`` (or ``""``); with ``required`` and no
    default the prompt repeats until a value is given.
    """
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    while True:
        hint = f" [{default}]" if default is not None else ""
        print(f"{label}{hint}: ", end="", file=sink)
        line = source.readline()
        if line == "":
            return None
        text = line.strip()
        if text:
            return text
        if default is not None:
            return default
        if not required:
            return ""
        print(f"{label} is required", file=sink)
