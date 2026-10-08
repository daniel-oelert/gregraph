"""Hook script generation, install/uninstall (spec §12.3, §16.1).

``gregraph hooks install`` writes ``.git/hooks/pre-commit`` — creating the file
or appending a clearly delimited block — that runs ``gregraph hook pre-commit``
(spec §12.3). The block locates gregraph via ``python -m gregraph`` with the
interpreter recorded at install time, falling back to ``gregraph`` on ``PATH``.
``uninstall`` removes the block, deleting the file when nothing else remains;
``status`` reports whether the block is installed and up to date. This module
is only the machinery; the pre-commit operation itself lives elsewhere.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SHEBANG: Final = "#!/bin/sh"
_BLOCK_START: Final = "# >>> gregraph pre-commit hook >>>"
_BLOCK_END: Final = "# <<< gregraph pre-commit hook <<<"
_HOOK_RELPATH: Final = Path(".git") / "hooks" / "pre-commit"


@dataclass(frozen=True)
class HookStatus:
    """Whether the gregraph block is installed and current (spec §12.3)."""

    installed: bool
    up_to_date: bool


def pre_commit_script(interpreter: str | None = None) -> str:
    """Full ``pre-commit`` script text: shebang plus the managed block.

    ``interpreter`` is the Python recorded at install time; it defaults to the
    current :data:`sys.executable`. The script runs ``<interpreter> -m gregraph
    hook pre-commit``, falling back to ``gregraph hook pre-commit`` when the
    interpreter is not executable (spec §12.3).
    """
    return _SHEBANG + "\n" + _pre_commit_block(interpreter) + "\n"


def install(root: Path) -> None:
    """Write or update ``.git/hooks/pre-commit`` under ``root`` (spec §12.3).

    A missing or content-free hook file gets the full script. Otherwise the
    clearly delimited block is appended after the existing content, or
    replaced in place when a block is already present. Parent directories are
    created as needed; the file is made executable on POSIX.
    """
    hook = _hook_path(root)
    hook.parent.mkdir(parents=True, exist_ok=True)
    block = _pre_commit_block()
    existing = _read_text(hook) if hook.exists() else ""
    span = _find_block(existing.splitlines())
    if span is not None:
        lines = existing.splitlines()
        lines[span[0] : span[1] + 1] = block.split("\n")
        _write_text(hook, "\n".join(lines) + "\n")
    elif existing.strip():
        if not existing.endswith("\n"):
            existing += "\n"
        _write_text(hook, existing + block + "\n")
    else:
        _write_text(hook, pre_commit_script())
    _make_executable(hook)


def uninstall(root: Path) -> None:
    """Remove the gregraph block from ``.git/hooks/pre-commit`` (spec §12.3).

    A file that holds no content besides the block (and at most a shebang
    line) is deleted; otherwise the surrounding hook content is preserved
    untouched. Absent file or absent block: no-op.
    """
    hook = _hook_path(root)
    if not hook.exists():
        return
    lines = _read_text(hook).splitlines()
    span = _find_block(lines)
    if span is None:
        return
    remaining = lines[: span[0]] + lines[span[1] + 1 :]
    if _is_blank_or_shebang(remaining):
        hook.unlink()
    else:
        _write_text(hook, "\n".join(remaining) + "\n")


def status(root: Path) -> HookStatus:
    """Report hook installation state under ``root`` (spec §12.3).

    ``installed`` is true when the delimited block is present;
    ``up_to_date`` is true when that block matches exactly what a fresh
    :func:`install` would write today. Not installed implies not up to date.
    """
    hook = _hook_path(root)
    if not hook.exists():
        return HookStatus(installed=False, up_to_date=False)
    lines = _read_text(hook).splitlines()
    span = _find_block(lines)
    if span is None:
        return HookStatus(installed=False, up_to_date=False)
    current = "\n".join(lines[span[0] : span[1] + 1])
    return HookStatus(installed=True, up_to_date=current == _pre_commit_block())


def _pre_commit_block(interpreter: str | None = None) -> str:
    """The managed block: banner, markers, and the hook invocation."""
    exe = _shell_quote(sys.executable if interpreter is None else interpreter)
    return "\n".join(
        (
            _BLOCK_START,
            "# gregraph pre-commit hook — do not edit between the markers.",
            "# Regenerate: `gregraph hooks install`;",
            "# remove: `gregraph hooks uninstall`.",
            f"if [ -x {exe} ]; then",
            f"    {exe} -m gregraph hook pre-commit || exit $?",
            "else",
            "    gregraph hook pre-commit || exit $?",
            "fi",
            _BLOCK_END,
        )
    )


def _hook_path(root: Path) -> Path:
    return root / _HOOK_RELPATH


def _find_block(lines: list[str]) -> tuple[int, int] | None:
    """Inclusive line span of the managed block, or ``None`` when absent."""
    try:
        start = lines.index(_BLOCK_START)
    except ValueError:
        return None
    for i in range(start + 1, len(lines)):
        if lines[i] == _BLOCK_END:
            return (start, i)
    return None


def _is_blank_or_shebang(lines: list[str]) -> bool:
    """Whether every line is blank or a ``#!`` line (hook content gone)."""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#!"):
            return False
    return True


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _make_executable(path: Path) -> None:
    if os.name == "posix":
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
