"""UUID → ID derivation, prefix/abbreviation rules, parsing (spec §4).

Crockford base32 body of the first 30 bits of a UUIDv4, a repository prefix and
a type abbreviation per config (``[A-Z][A-Z0-9]{0,7}`` and ``[A-Z]{3,5}``),
case-insensitive parsing and normalisation with or without prefix when
unambiguous, collision retry against a caller-supplied existing-ID set (max
``MAX_ID_ATTEMPTS``), and the id ↔ uuid derivation check used by ``validate``
(spec §4.2, §4.3, §4.5). The two-segment pre-0.2 format is deliberately
invalid: the migration is a hard cutover. Pure data/logic only — no I/O, no
printing.
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
CR_ABBREVIATION: Final = "CHG"

PREFIX_PATTERN: Final = re.compile(r"[A-Z][A-Z0-9]{0,7}")
ABBREVIATION_PATTERN: Final = re.compile(r"[A-Z]{3,5}")
ID_BODY_PATTERN: Final = re.compile(r"[0-9A-HJKMNP-TV-Z]{6}")
ID_PATTERN: Final = re.compile(r"[A-Z][A-Z0-9]{0,7}-[A-Z]{3,5}-[0-9A-HJKMNP-TV-Z]{6}")
LEGACY_ID_PATTERN: Final = re.compile(r"[A-Z][A-Z0-9]{0,7}-[0-9A-HJKMNP-TV-Z]{6}")

_BODY_MASK: Final = (1 << ID_BODY_BITS) - 1
_BODY_SHIFT_STEP: Final = 5
_DECODE: Final = {char: index for index, char in enumerate(CROCKFORD_ALPHABET)}


class IdGenerationError(RuntimeError):
    """Internal error: no free ID after ``MAX_ID_ATTEMPTS`` (spec §4.2)."""


class GeneratedId(NamedTuple):
    """A freshly generated ``(uuid, id)`` pair to store in a sidecar (spec §4.2)."""

    uuid: UUID
    id: str


class IdParts(NamedTuple):
    """The three segments of a canonical typed ID (spec §4.1)."""

    prefix: str
    abbreviation: str
    body: str


def is_valid_prefix(prefix: str) -> bool:
    """Whether ``prefix`` matches the configured prefix pattern (spec §4.1)."""
    return PREFIX_PATTERN.fullmatch(prefix) is not None


def is_valid_abbreviation(abbreviation: str) -> bool:
    """Whether ``abbreviation`` matches ``[A-Z]{3,5}`` (spec §4.1)."""
    return ABBREVIATION_PATTERN.fullmatch(abbreviation) is not None


def is_valid_id(value: str) -> bool:
    """Whether ``value`` is a canonical typed ID (spec §4.1)."""
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


def split_id(value: str) -> IdParts | None:
    """Split a canonical typed ID into its parts, or ``None`` (spec §4.1)."""
    if ID_PATTERN.fullmatch(value) is None:
        return None
    prefix, abbreviation, body = value.split("-")
    return IdParts(prefix, abbreviation, body)


def derive_id(uuid: UUID, prefix: str = DEFAULT_PREFIX, abbreviation: str = "") -> str:
    """Derive the canonical ID for ``uuid`` (spec §4.1, §4.2)."""
    if not is_valid_prefix(prefix):
        raise ValueError(f"invalid ID prefix: {prefix!r}")
    if not is_valid_abbreviation(abbreviation):
        raise ValueError(f"invalid ID abbreviation: {abbreviation!r}")
    return f"{prefix}-{abbreviation}-{encode_body(uuid.int >> (128 - ID_BODY_BITS))}"


def is_derivable_from(
    id_: str,
    uuid: UUID,
    prefix: str = DEFAULT_PREFIX,
    abbreviation: str = "",
) -> bool:
    """Whether ``id_`` equals the ID derived from ``uuid`` (spec §4.3)."""
    return id_ == derive_id(uuid, prefix, abbreviation)


def generate_id(
    existing: Collection[str],
    prefix: str = DEFAULT_PREFIX,
    abbreviation: str = "",
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
    if not is_valid_abbreviation(abbreviation):
        raise ValueError(f"invalid ID abbreviation: {abbreviation!r}")
    taken = {item.upper() for item in existing}
    for _ in range(MAX_ID_ATTEMPTS):
        candidate_uuid = uuid_factory()
        candidate = derive_id(candidate_uuid, prefix, abbreviation)
        if candidate not in taken:
            return GeneratedId(candidate_uuid, candidate)
    raise IdGenerationError(
        f"no free ID with prefix {prefix!r} and abbreviation {abbreviation!r} "
        f"after {MAX_ID_ATTEMPTS} attempts"
    )


def normalise_id(
    raw: str,
    prefix: str = DEFAULT_PREFIX,
    *,
    known: Collection[str] | None = None,
) -> str | None:
    """Normalise user input to a canonical typed ID (spec §4.5).

    Case-insensitive. Accepts the full ``PREFIX-ABBREVIATION-BODY`` form, the
    prefix-less ``ABBREVIATION-BODY`` form (completed with ``prefix``), and a
    bare 6-character body when ``known`` makes it unambiguous. The pre-0.2
    two-segment form is rejected. With ``known``, the result must resolve to
    exactly one of those IDs. Returns ``None`` when ``raw`` is not a valid ID
    or is ambiguous/unknown.
    """
    if not is_valid_prefix(prefix):
        raise ValueError(f"invalid ID prefix: {prefix!r}")
    text = raw.strip().upper()
    known_upper = {item.upper() for item in known} if known is not None else None
    if ID_PATTERN.fullmatch(text) is not None:
        if known_upper is None or text in known_upper:
            return text
        return None
    abbreviated = re.fullmatch(r"([A-Z]{3,5})-([0-9A-HJKMNP-TV-Z]{6})", text)
    if abbreviated is not None:
        candidate = f"{prefix}-{abbreviated.group(1)}-{abbreviated.group(2)}"
        if known_upper is None:
            return candidate
        if candidate in known_upper:
            return candidate
        # The prefix may differ from the configured one; accept the sole match.
        matches = [
            item
            for item in known_upper
            if item.endswith(f"-{abbreviated.group(1)}-{abbreviated.group(2)}")
        ]
        return matches[0] if len(matches) == 1 else None
    if ID_BODY_PATTERN.fullmatch(text) is not None:
        if known_upper is None:
            return None
        matches = []
        for item in known_upper:
            parts = split_id(item)
            if parts is not None and parts.body == text:
                matches.append(item)
        return matches[0] if len(matches) == 1 else None
    return None
