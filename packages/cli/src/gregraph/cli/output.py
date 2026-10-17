"""Text/JSON formatters and colour handling (spec §13 output rules, §16.1).

Plain text: one finding per line, prefixed by code (``E-…``/``W-…``) and the
affected ID/path (spec §13). Tables align columns for ``list`` (spec §13.10).
JSON output is the canonical shape (indent 2, sorted keys, trailing newline;
spec §5.4). Colours only when stdout is a TTY and ``NO_COLOR`` is unset —
plain ``\033`` codes, no third-party terminal library (spec §13).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TextIO

from gregraph.core.models import Document, Finding

_RESET = "\033[0m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def colour_enabled(stream: TextIO) -> bool:
    """Colours only when ``stream`` is a TTY and ``NO_COLOR`` is unset (spec §13)."""
    if "NO_COLOR" in os.environ:
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


@dataclass(frozen=True)
class Palette:
    """Severity-aware colouring; a disabled palette passes text through."""

    enabled: bool = False

    def paint(self, text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if self.enabled else text

    def error(self, text: str) -> str:
        return self.paint(text, _RED)

    def warn(self, text: str) -> str:
        return self.paint(text, _YELLOW)

    def ok(self, text: str) -> str:
        return self.paint(text, _GREEN)

    def key(self, text: str) -> str:
        return self.paint(text, _BOLD)

    def dim(self, text: str) -> str:
        return self.paint(text, _DIM)


def format_finding(finding: Finding, *, palette: Palette | None = None) -> str:
    """One finding per line: ``E-CODE subject: message`` (spec §13).

    ``subject`` is the document/CR ID or repository-relative path of the
    finding; an optional suggested ``fix`` command is appended in parentheses.
    """
    paint = palette or Palette(enabled=False)
    code = (
        paint.error(finding.code)
        if finding.severity == "E"
        else paint.warn(finding.code)
    )
    text = f"{code} {finding.subject}: {finding.message}"
    if finding.fix:
        text += f" (fix: {finding.fix})"
    return text


def canonical_json(payload: object) -> str:
    """Canonical JSON text (spec §5.4 style): indent 2, sorted keys, newline."""
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def document_payload(document: Document, **derived: object) -> dict[str, Any]:
    """The ``list``/``show --json`` shape: sidecar fields plus derived fields.

    Serialises exactly like the on-disk sidecar (``mode="json"``, ``by_alias``)
    so ``--json`` output is machine-comparable with the files.
    """
    data: dict[str, Any] = document.model_dump(mode="json", by_alias=True)
    for key, value in derived.items():
        data[key] = value
    return data


def error_envelope(
    code: str,
    exit_code: int,
    message: str,
    *,
    finding: Finding | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The ``--json`` error envelope for exits 2/3/4/5 (AGENT_READINESS §2.2).

    ``error.details`` is always present: it mirrors ``finding.details`` unless
    ``details`` is given explicitly (``{}`` when neither is set). ``finding``
    is the complete §14 report shape (including ``details``) or ``null``.
    """
    resolved_details: dict[str, Any]
    if details is not None:
        resolved_details = dict(details)
    elif finding is not None and finding.details is not None:
        resolved_details = dict(finding.details)
    else:
        resolved_details = {}
    return {
        "error": {
            "code": code,
            "exit_code": exit_code,
            "message": message,
            "finding": (
                finding.model_dump(mode="json") if finding is not None else None
            ),
            "details": resolved_details,
        }
    }


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Space-aligned columns; the header row is not padded past its own width."""
    columns = list(headers)
    widths = [len(header) for header in columns]
    for row in rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))
    lines: list[str] = []
    header_line = "  ".join(
        header.ljust(widths[index]) for index, header in enumerate(columns)
    )
    lines.append(header_line.rstrip())
    for row in rows:
        lines.append(
            "  ".join(
                cell.ljust(widths[index]) for index, cell in enumerate(row)
            ).rstrip()
        )
    return "\n".join(lines) + "\n"


@dataclass
class Output:
    """All command output flows through here (spec §13 output rules).

    ``json_mode`` silences human ``line`` output so stdout stays a single JSON
    document; ``quiet`` drops non-essential lines; ``verbose`` adds ``detail``
    lines. Errors always print to stderr. Colours follow stdout.
    """

    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    json_mode: bool = False
    quiet: bool = False
    verbose: bool = False

    @property
    def palette(self) -> Palette:
        return Palette(enabled=colour_enabled(self.stdout))

    def line(self, text: str = "") -> None:
        """Human output on stdout; suppressed by ``--quiet`` and ``--json``."""
        if self.quiet or self.json_mode:
            return
        print(text, file=self.stdout)

    def announce(self, text: str) -> None:
        """Essential stdout line: never suppressed, flushed before returning.

        For lifecycle output a user must see whatever the flags, such as the
        ``serve`` URL banner (spec §21.3). Use ``line`` for ordinary output.
        """
        print(text, file=self.stdout, flush=True)

    def detail(self, text: str) -> None:
        """Extra output only with ``--verbose``."""
        if self.quiet or self.json_mode or not self.verbose:
            return
        print(text, file=self.stdout)

    def warn(self, text: str) -> None:
        """Warning on stderr; suppressed by ``--quiet`` and ``--json``.

        Under ``--json`` warnings travel inside the payload as ``notices``
        instead (AGENT_READINESS §2.1 R3).
        """
        if self.quiet or self.json_mode:
            return
        print(self.palette.warn(f"warning: {text}"), file=self.stderr)

    def note(self, text: str) -> None:
        """Degraded-mode note on stderr; suppressed by ``--quiet`` and ``--json``.

        Under ``--json`` notes travel inside the payload as ``notices``
        instead (AGENT_READINESS §2.1 R3).
        """
        if self.quiet or self.json_mode:
            return
        print(self.palette.dim(f"note: {text}"), file=self.stderr)

    def error(self, text: str) -> None:
        """Error on stderr; never suppressed."""
        print(self.palette.error(f"error: {text}"), file=self.stderr)

    def finding(self, finding: Finding) -> None:
        """One refusal/validation finding on stderr.

        Under ``--json`` the finding travels inside the error envelope or
        payload instead, so stderr stays empty (AGENT_READINESS §2.1 R3).
        """
        if self.json_mode:
            return
        print(format_finding(finding, palette=self.palette), file=self.stderr)

    def report(self, findings: Iterable[Finding]) -> None:
        """The validation-style report on stdout, one per line."""
        palette = self.palette
        for finding in findings:
            print(format_finding(finding, palette=palette), file=self.stdout)

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        """Aligned table on stdout (``list``)."""
        text = format_table(headers, rows)
        if self.palette.enabled:
            first, _, rest = text.partition("\n")
            text = self.palette.key(first) + ("\n" + rest if rest else "")
        print(text, end="", file=self.stdout)

    def json(self, payload: object) -> None:
        """Canonical JSON payload on stdout (``--json`` modes)."""
        print(canonical_json(payload), end="", file=self.stdout)

    def mapping_lines(self, items: Mapping[str, str]) -> None:
        """``key: value`` lines indented two spaces, keys padded (``show``)."""
        if not items:
            return
        width = max(len(key) for key in items)
        for key, value in items.items():
            self.line(f"  {key.ljust(width)}  {value}")
