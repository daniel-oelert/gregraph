"""Shared parsing of the template-guided authoring flags (AGENT_READINESS §3.4).

Pure syntax, no template knowledge: split ``--section`` ``HEADING=CONTENT``
and ``--section-file`` ``HEADING=PATH`` values, read file payloads through
:func:`gregraph.core.storage.read_text_file` (``cli`` never touches the
filesystem directly; stdin is the CLI's own job), and refuse the §3.4
rule-1/rule-7 combinations and malformed values with ``UsageError`` (exit 2).
Heading resolution against the pinned template happens in core
(``resolve_section_inputs``), which turns unknown headings into the
self-describing ``E-SECTION-UNKNOWN`` refusal (exit 4).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from gregraph.cli.main import UsageError
from gregraph.core.storage import read_text_file


@dataclass(frozen=True, slots=True)
class ParsedContentArgs:
    """Parsed authoring input (AGENT_READINESS §3.4 rules 1–7).

    ``sections`` keeps the given order as ``(heading, content)`` pairs with
    the heading trimmed; ``body_text`` is the whole-body replacement (or
    ``None``); ``has_content_flags`` says whether any content flag was given.
    """

    sections: tuple[tuple[str, str], ...]
    body_text: str | None
    has_content_flags: bool


def _normalise(text: str) -> str:
    """LF normalisation (design §21.5 step 4): CRLF and CR become LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_stdin(stream: TextIO) -> str:
    return _normalise(stream.read())


def _split_pair(raw: str, option: str) -> tuple[str, str]:
    """``HEADING=VALUE`` split on the first ``=``; malformed input is usage."""
    heading, separator, value = raw.partition("=")
    if not separator or not heading.strip():
        raise UsageError(f"{option} expects <Heading>=<VALUE>, got {raw!r}")
    return heading.strip(), value


def parse_content_args(
    args: argparse.Namespace,
    *,
    allow_body: bool = True,
    stdin: TextIO | None = None,
) -> ParsedContentArgs:
    """Parse the ``--section*``/``--body*`` flags of one invocation (§3.4).

    Refusals (exit 2, nothing read or written): ``--body`` with
    ``--body-file``, any ``--body*`` with any ``--section*``, more than one
    stdin (``-``) consumer, a malformed ``HEADING=…`` value, an empty
    ``--section-file`` path, and a duplicate trimmed heading (across both
    section options — content is never silently merged). File paths are read
    via :func:`gregraph.core.storage.read_text_file`; ``-`` reads ``stdin``
    (or ``sys.stdin``), normalising CRLF/CR to LF.
    """
    section_raws = list(getattr(args, "section", []) or [])
    section_file_raws = list(getattr(args, "section_file", []) or [])
    body_text = getattr(args, "body", None)
    body_file = getattr(args, "body_file", None)
    source = stdin if stdin is not None else sys.stdin

    has_body = body_text is not None or body_file is not None
    has_sections = bool(section_raws) or bool(section_file_raws)
    has_content_flags = has_body or has_sections

    if has_body and not allow_body:
        raise UsageError("--body/--body-file are not valid for this command")
    if body_text is not None and body_file is not None:
        raise UsageError("--body and --body-file cannot be used together")
    if has_body and has_sections:
        raise UsageError(
            "--body/--body-file cannot be combined with --section/--section-file"
        )

    sections: list[tuple[str, str]] = []
    for raw in section_raws:
        heading, content = _split_pair(raw, "--section")
        if any(existing == heading for existing, _ in sections):
            raise UsageError(f"duplicate section heading: {heading!r}")
        sections.append((heading, content))

    file_entries: list[tuple[str, str]] = []
    for raw in section_file_raws:
        heading, path = _split_pair(raw, "--section-file")
        if any(existing == heading for existing, _ in sections) or any(
            existing == heading for existing, _ in file_entries
        ):
            raise UsageError(f"duplicate section heading: {heading!r}")
        if not path.strip():
            raise UsageError(f"--section-file expects a path, got {raw!r}")
        file_entries.append((heading, path))

    stdin_consumers = sum(1 for _, path in file_entries if path == "-")
    if body_file == "-":
        stdin_consumers += 1
    if stdin_consumers > 1:
        raise UsageError("only one stdin ('-') consumer is allowed per invocation")

    resolved: list[tuple[str, str]] = []
    for heading, content in sections:
        resolved.append((heading, _normalise(content)))
    for heading, path in file_entries:
        if path == "-":
            resolved.append((heading, _read_stdin(source)))
        else:
            resolved.append((heading, read_text_file(Path(path))))

    body: str | None = None
    if body_file is not None:
        if body_file == "-":
            body = _read_stdin(source)
        else:
            body = read_text_file(Path(body_file))
    elif body_text is not None:
        body = _normalise(body_text)

    return ParsedContentArgs(
        sections=tuple(resolved),
        body_text=body,
        has_content_flags=has_content_flags,
    )
