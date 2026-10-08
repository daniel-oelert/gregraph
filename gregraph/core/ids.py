"""UUID → ID derivation, prefix rules, parsing (spec §4).

Crockford base32 body of the first 30 bits of a UUIDv4, prefix per config
(pattern ``[A-Z][A-Z0-9]{0,7}``), case-insensitive parsing and normalisation
with or without prefix when unambiguous, collision retry against a
caller-supplied existing-ID set (max ``MAX_ID_ATTEMPTS``), and the
id ↔ uuid derivation check used by ``validate`` (spec §4.2, §4.3, §4.5).
Pure data/logic only — no I/O, no printing.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from typing import Final, NamedTuple
from uuid import UUID, uuid4

CROCKFORD_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ID_BODY_LENGTH: Final = 6
ID_BODY_BITS: Final = 30
MAX_ID_ATTEMPTS: Final = 100
DEFAULT_PREFIX: Final = "RE"

PREFIX_PATTERN: Final = re.compile(r"[A-Z][A-Z0-9]{0,7}")
ID_BODY_PATTERN: Final = re.compile(r"[0-9A-HJKMNP-TV-Z]{6}")
ID_PATTERN: Final = re.compile(r"[A-Z][A-Z0-9]{0,7}-[0-9A-HJKMNP-TV-Z]{6}")

_BODY_MASK: Final = (1 << ID_BODY_BITS) - 1
_BODY_SHIFT_STEP: Final = 5
_DECODE: Final = {char: index for index, char in enumerate(CROCKFORD_ALPHABET)}


class IdGenerationError(RuntimeError):
    """Internal error: no free ID after ``MAX_ID_ATTEMPTS`` (spec §4.2)."""


class GeneratedId(NamedTuple):
    """A freshly generated ``(uuid, id)`` pair to store in a sidecar (spec §4.2)."""

    uuid: UUID
    id: str


def is_valid_prefix(prefix: str) -> bool:
    """Whether ``prefix`` matches the configured prefix pattern (spec §4.1)."""
    return PREFIX_PATTERN.fullmatch(prefix) is not None


def is_valid_id(value: str) -> bool:
    """Whether ``value`` is a canonical ID (spec §4.1)."""
    return ID_PATTERN.fullmatch(value) is not None


def encode_body(value: int) -> str:
    """Encode a 30-bit value as 6 Crockford base32 characters (spec §4.1)."""
    if not 0 <= value <= _BODY_MASK:
        raise ValueError(f"ID body value out of range for {ID_BODY_BITS} bits: {value}")
    chars = []
    for shift in range((ID_BODY_LENGTH - 1) * _BODY_SHIFT_STEP, -1, -_BODY_SHIFT_STEP):
        chars.append(CROCKFORD_ALPHABET[(value >> shift) & 0x1F])
    return "".join(chars)


def decode_body(body: str) -> int:
    """Decode a canonical 6-character body back to its 30-bit value (spec §4.1).

    Strict codec: uppercase Crockford alphabet only (no I, L, O, U). Lenient
    user input goes through :func:`normalise_id`.
    """
    if ID_BODY_PATTERN.fullmatch(body) is None:
        raise ValueError(f"invalid ID body: {body!r}")
    value = 0
    for char in body:
        value = (value << _BODY_SHIFT_STEP) | _DECODE[char]
    return value


def split_id(value: str) -> tuple[str, str] | None:
    """Split a canonical ID into ``(prefix, body)``, or ``None`` (spec §4.1)."""
    if ID_PATTERN.fullmatch(value) is None:
        return None
    prefix, _, body = value.partition("-")
    return prefix, body


def derive_id(uuid: UUID, prefix: str = DEFAULT_PREFIX) -> str:
    """Derive the canonical ID for ``uuid`` with ``prefix`` (spec §4.1, §4.2)."""
    if not is_valid_prefix(prefix):
        raise ValueError(f"invalid ID prefix: {prefix!r}")
    return f"{prefix}-{encode_body(uuid.int >> (128 - ID_BODY_BITS))}"


def is_derivable_from(id_: str, uuid: UUID, prefix: str = DEFAULT_PREFIX) -> bool:
    """Whether ``id_`` equals the ID derived from ``uuid`` with ``prefix`` (spec §4.3).

    The ``validate`` derivation check (``E-ID-DERIVATION``) is this comparison
    with the configured prefix.
    """
    return id_ == derive_id(uuid, prefix)


def generate_id(
    existing: Collection[str],
    prefix: str = DEFAULT_PREFIX,
    *,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> GeneratedId:
    """Generate a fresh ``(uuid, id)`` pair avoiding ``existing`` (spec §4.2).

    The candidate ID is the derivation of a new UUIDv4; on collision with any
    ID in ``existing`` (case-insensitive) the UUID is discarded and retried, at
    most ``MAX_ID_ATTEMPTS`` times. Raises :class:`IdGenerationError` after
    that.
    """
    if not is_valid_prefix(prefix):
        raise ValueError(f"invalid ID prefix: {prefix!r}")
    taken = {item.upper() for item in existing}
    for _ in range(MAX_ID_ATTEMPTS):
        candidate_uuid = uuid_factory()
        candidate = derive_id(candidate_uuid, prefix)
        if candidate not in taken:
            return GeneratedId(candidate_uuid, candidate)
    raise IdGenerationError(
        f"no free ID with prefix {prefix!r} after {MAX_ID_ATTEMPTS} attempts"
    )


def normalise_id(
    raw: str,
    prefix: str = DEFAULT_PREFIX,
    *,
    known: Collection[str] | None = None,
) -> str | None:
    """Normalise user input to a canonical ID (spec §4.5).

    Case-insensitive; accepts the 6-character body without prefix when that is
    unambiguous. With ``known``, the result must resolve to exactly one of those
    IDs; without it, a bare body is completed with ``prefix``. Returns ``None``
    when ``raw`` is not a valid ID or is ambiguous/unknown.
    """
    if not is_valid_prefix(prefix):
        raise ValueError(f"invalid ID prefix: {prefix!r}")
    text = raw.strip().upper()
    known_upper = {item.upper() for item in known} if known is not None else None
    if ID_PATTERN.fullmatch(text) is not None:
        if known_upper is None or text in known_upper:
            return text
        return None
    if ID_BODY_PATTERN.fullmatch(text) is not None:
        if known_upper is None:
            return f"{prefix}-{text}"
        matches = []
        for item in known_upper:
            parts = split_id(item)
            if parts is not None and parts[1] == text:
                matches.append(item)
        return matches[0] if len(matches) == 1 else None
    return None
