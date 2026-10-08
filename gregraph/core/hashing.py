"""Body/asset hashing (spec §7.3, §5.7).

``body_hash = "sha256:" + hex`` of the normalised body; raw-byte SHA-256 for
assets; effective-content comparison. Pure functions, no I/O.

Normalisation (spec §7.3): decode UTF-8, convert CRLF/CR to LF, strip trailing
whitespace (spaces and tabs) on every line, collapse three or more consecutive
blank lines to two, ensure exactly one trailing newline. The H1 line is
included (title changes count). Exactly one trailing newline means the body
ends with a single ``\\n``: trailing blank lines are removed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path


def normalise_body(body: str | bytes) -> str:
    """Return the normalised form of ``body`` (spec §7.3)."""
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    collapsed: list[str] = []
    blanks = 0
    for line in lines:
        if line == "":
            blanks += 1
            if blanks <= 2:
                collapsed.append(line)
        else:
            blanks = 0
            collapsed.append(line)
    joined = "\n".join(collapsed)
    return joined.rstrip("\n") + "\n"


def body_hash(body: str | bytes) -> str:
    """Return ``"sha256:" + hex`` of the normalised body (spec §7.3)."""
    return "sha256:" + hashlib.sha256(normalise_body(body).encode("utf-8")).hexdigest()


def asset_hash(data: bytes) -> str:
    """Return ``"sha256:" + hex`` of the raw asset bytes (spec §5.7, §7.3)."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def effective_content_changed(
    old_body_hash: str,
    old_assets: Iterable[tuple[Path, str]],
    new_body_hash: str,
    new_assets: Iterable[tuple[Path, str]],
) -> bool:
    """Return whether effective content changed (spec §7.3).

    Effective content changed iff the body hash differs or the sorted lists of
    ``(path, hash)`` asset entries differ.
    """
    return old_body_hash != new_body_hash or sorted(old_assets) != sorted(new_assets)
