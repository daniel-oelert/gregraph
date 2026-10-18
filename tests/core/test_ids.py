"""Tests for ``gregraph.core.ids`` (spec §4).

Test-first for typed IDs: Crockford base32 codec, UUIDv4 → ID derivation
(first 30 bits) with a type abbreviation, collision retry, case-insensitive
parsing/normalisation with or without prefix, and the id ↔ uuid derivation
check. Legacy two-segment IDs are rejected (hard cutover, spec §4.1).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gregraph.core.ids import (
    CR_ABBREVIATION,
    CROCKFORD_ALPHABET,
    DEFAULT_PREFIX,
    ID_BODY_BITS,
    ID_BODY_LENGTH,
    MAX_ID_ATTEMPTS,
    GeneratedId,
    IdGenerationError,
    IdParts,
    decode_body,
    derive_id,
    encode_body,
    generate_id,
    is_derivable_from,
    is_valid_abbreviation,
    is_valid_id,
    is_valid_prefix,
    normalise_id,
    split_id,
)

_VALUE_MAX = (1 << ID_BODY_BITS) - 1

values_st = st.integers(min_value=0, max_value=_VALUE_MAX)
prefix_st = st.builds(
    lambda head, tail: head + tail,
    st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=0, max_size=7),
)
abbreviation_st = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=3, max_size=5)
body_st = st.text(
    alphabet=CROCKFORD_ALPHABET, min_size=ID_BODY_LENGTH, max_size=ID_BODY_LENGTH
)
ids_st = st.builds(
    lambda prefix, abbreviation, body: f"{prefix}-{abbreviation}-{body}",
    prefix_st,
    abbreviation_st,
    body_st,
)


def _uuid_with_top_value(value: int) -> UUID:
    return UUID(int=value << (128 - ID_BODY_BITS))


def _scripted_factory(uuids: list[UUID]) -> tuple[Callable[[], UUID], list[UUID]]:
    calls: list[UUID] = []
    queue = list(uuids)

    def factory() -> UUID:
        item = queue.pop(0) if queue else uuids[-1]
        calls.append(item)
        return item

    return factory, calls


def test_crockford_alphabet_is_32_unique_uppercase() -> None:
    assert len(CROCKFORD_ALPHABET) == 32
    assert len(set(CROCKFORD_ALPHABET)) == 32
    assert CROCKFORD_ALPHABET == CROCKFORD_ALPHABET.upper()


def test_crockford_alphabet_excludes_ilou() -> None:
    for char in "ILOU":
        assert char not in CROCKFORD_ALPHABET


@given(value=values_st)
def test_encode_body_length_and_charset(value: int) -> None:
    body = encode_body(value)
    assert len(body) == ID_BODY_LENGTH
    assert all(char in CROCKFORD_ALPHABET for char in body)


@given(value=values_st)
def test_encode_decode_roundtrip(value: int) -> None:
    assert decode_body(encode_body(value)) == value


@given(value=values_st)
def test_derive_id_body_holds_first_30_bits(value: int) -> None:
    uuid = _uuid_with_top_value(value)
    assert split_id(derive_id(uuid, "AB", "FEAT")) == IdParts(
        "AB", "FEAT", encode_body(value)
    )
    assert decode_body(derive_id(uuid, "AB", "FEAT").rsplit("-", 1)[1]) == value


@given(uuid=st.uuids(version=4))
def test_derive_id_format(uuid: UUID) -> None:
    id_ = derive_id(uuid, DEFAULT_PREFIX, "FEAT")
    assert is_valid_id(id_)
    assert id_.startswith(f"{DEFAULT_PREFIX}-FEAT-")
    assert split_id(id_) == IdParts(DEFAULT_PREFIX, "FEAT", id_.rsplit("-", 1)[1])


@given(uuid=st.uuids(version=4), prefix=prefix_st, abbreviation=abbreviation_st)
def test_derive_id_custom_prefix_and_abbreviation(
    uuid: UUID, prefix: str, abbreviation: str
) -> None:
    body = encode_body(uuid.int >> (128 - ID_BODY_BITS))
    assert derive_id(uuid, prefix, abbreviation) == f"{prefix}-{abbreviation}-{body}"


@pytest.mark.parametrize(
    "prefix",
    ["re", "", "9ABC", "TOOLONGPREFIX", "A-B", "-RE", "A_", "AB-c"],
)
def test_derive_id_rejects_invalid_prefix(prefix: str) -> None:
    with pytest.raises(ValueError):
        derive_id(uuid4(), prefix, "FEAT")


@pytest.mark.parametrize("prefix", ["A", "RE", "Z0", "ABCDEFGH"])
def test_derive_id_accepts_prefix_length_bounds(prefix: str) -> None:
    assert is_valid_prefix(prefix)
    assert derive_id(uuid4(), prefix, "FEAT").startswith(f"{prefix}-FEAT-")


@pytest.mark.parametrize(
    "abbreviation",
    ["", "FE", "FEATURES", "feat", "Feat", "F3AT", "FE-T", "FE T"],
)
def test_derive_id_rejects_invalid_abbreviation(abbreviation: str) -> None:
    with pytest.raises(ValueError):
        derive_id(uuid4(), "RE", abbreviation)


@pytest.mark.parametrize("abbreviation", ["ASM", "FEAT", "STORY"])
def test_derive_id_accepts_abbreviation_length_bounds(abbreviation: str) -> None:
    assert is_valid_abbreviation(abbreviation)
    assert derive_id(uuid4(), "RE", abbreviation).split("-")[1] == abbreviation


@pytest.mark.parametrize("value", [-1, 1 << ID_BODY_BITS, (1 << ID_BODY_BITS) + 5])
def test_encode_body_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValueError):
        encode_body(value)


@pytest.mark.parametrize("body", ["7F3K2I", "7F3K2L", "7F3K2O", "7F3K2U"])
def test_decode_body_rejects_ilou(body: str) -> None:
    with pytest.raises(ValueError):
        decode_body(body)


def test_decode_body_rejects_lowercase() -> None:
    with pytest.raises(ValueError):
        decode_body("7f3k2q")


@pytest.mark.parametrize("body", ["", "7F3K2", "7F3K2QQ", "7F3K2-", "7F3K2!"])
def test_decode_body_rejects_wrong_shape(body: str) -> None:
    with pytest.raises(ValueError):
        decode_body(body)


@given(uuid=st.uuids(version=4))
def test_is_derivable_from_true(uuid: UUID) -> None:
    assert is_derivable_from(derive_id(uuid, "RE", "FEAT"), uuid, "RE", "FEAT")


def test_is_derivable_from_false_wrong_body() -> None:
    uuid = uuid4()
    other = _uuid_with_top_value(decode_body("7F3K2Q") + 1)
    assert not is_derivable_from("RE-FEAT-7F3K2Q", uuid, "RE", "FEAT")
    assert not is_derivable_from("RE-FEAT-7F3K2Q", other, "RE", "FEAT")


def test_is_derivable_from_false_wrong_prefix_or_abbreviation() -> None:
    uuid = uuid4()
    id_ = derive_id(uuid, "RE", "FEAT")
    assert not is_derivable_from(id_, uuid, "XX", "FEAT")
    assert not is_derivable_from(id_, uuid, "RE", "FUNC")


@given(id_=ids_st)
def test_split_id_roundtrip(id_: str) -> None:
    parts = split_id(id_)
    assert parts is not None
    assert f"{parts.prefix}-{parts.abbreviation}-{parts.body}" == id_


@pytest.mark.parametrize(
    "value",
    [
        "re-feat-7f3k2q",
        "RE-FEAT-7F3K2",
        "RE-FEAT-7F3K2QQ",
        "REF EAT7F3K2Q",
        "RE-7F3K2Q",  # legacy two-segment form: rejected
        "7F3K2Q",
        "RE-FEAT-UUUUUU",
        "RE-FEAT-7F3K2I",
        "RE-FEAT-7F3K2!",
    ],
)
def test_split_id_rejects_invalid(value: str) -> None:
    assert split_id(value) is None


def test_split_id_returns_parts() -> None:
    assert split_id("RE-FEAT-7F3K2Q") == IdParts("RE", "FEAT", "7F3K2Q")
    assert split_id("RE-CHG-7F3K2Q") == IdParts("RE", CR_ABBREVIATION, "7F3K2Q")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("RE-FEAT-7F3K2Q", True),
        ("A-ABC-000000", True),
        ("ABCDEFGH-STORY-ZZZZZZ", True),
        ("RE-CHG-7F3K2Q", True),
        ("re-feat-7f3k2q", False),
        ("RE-FEAT-7F3K2I", False),
        ("9A-FEAT-7F3K2Q", False),
        ("RE-FEAT-7F3K2Q ", False),
        ("RE-7F3K2Q", False),
    ],
)
def test_is_valid_id(value: str, expected: bool) -> None:
    assert is_valid_id(value) is expected


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("RE", True),
        ("A", True),
        ("ABCDEFGH", True),
        ("re", False),
        ("", False),
        ("ABCDEFGHI", False),
    ],
)
def test_is_valid_prefix(prefix: str, expected: bool) -> None:
    assert is_valid_prefix(prefix) is expected


@pytest.mark.parametrize(
    ("abbreviation", "expected"),
    [
        ("ASM", True),
        ("FEAT", True),
        ("STORY", True),
        ("FE", False),
        ("FEATURES", False),
        ("feat", False),
        ("F3AT", False),
    ],
)
def test_is_valid_abbreviation(abbreviation: str, expected: bool) -> None:
    assert is_valid_abbreviation(abbreviation) is expected


def test_generate_id_uses_first_uuid() -> None:
    uuid = uuid4()
    factory, calls = _scripted_factory([uuid])
    generated = generate_id(set(), "RE", "FEAT", uuid_factory=factory)
    assert generated == GeneratedId(uuid, derive_id(uuid, "RE", "FEAT"))
    assert calls == [uuid]


def test_generate_id_retries_on_collision() -> None:
    colliding = uuid4()
    fresh = uuid4()
    existing = {derive_id(colliding, "RE", "FEAT")}
    factory, calls = _scripted_factory([colliding, colliding, fresh])
    generated = generate_id(existing, "RE", "FEAT", uuid_factory=factory)
    assert generated.uuid == fresh
    assert calls == [colliding, colliding, fresh]


def test_generate_id_succeeds_on_attempt_100() -> None:
    colliding = uuid4()
    fresh = uuid4()
    existing = {derive_id(colliding, "RE", "FEAT")}
    factory, calls = _scripted_factory([colliding] * 99 + [fresh])
    generated = generate_id(existing, "RE", "FEAT", uuid_factory=factory)
    assert generated.uuid == fresh
    assert len(calls) == MAX_ID_ATTEMPTS


def test_generate_id_fails_after_max_attempts() -> None:
    colliding = uuid4()
    existing = {derive_id(colliding, "RE", "FEAT")}
    factory, calls = _scripted_factory([colliding])
    with pytest.raises(IdGenerationError):
        generate_id(existing, "RE", "FEAT", uuid_factory=factory)
    assert len(calls) == MAX_ID_ATTEMPTS
    assert MAX_ID_ATTEMPTS == 100


def test_generate_id_collision_check_case_insensitive() -> None:
    colliding = uuid4()
    fresh = uuid4()
    existing = {derive_id(colliding, "RE", "FEAT").lower()}
    factory, calls = _scripted_factory([colliding, fresh])
    generated = generate_id(existing, "RE", "FEAT", uuid_factory=factory)
    assert generated.uuid == fresh
    assert len(calls) == 2


def test_generate_id_rejects_invalid_prefix_or_abbreviation() -> None:
    with pytest.raises(ValueError):
        generate_id(set(), "re", "FEAT")
    with pytest.raises(ValueError):
        generate_id(set(), "RE", "feat")


@given(data=st.data())
def test_normalise_id_case_insensitive(data: st.DataObject) -> None:
    canonical = data.draw(ids_st)
    flips = data.draw(
        st.lists(st.booleans(), min_size=len(canonical), max_size=len(canonical))
    )
    raw = "".join(
        char.lower() if flip else char
        for char, flip in zip(canonical, flips, strict=True)
    )
    assert normalise_id(raw, DEFAULT_PREFIX) == canonical


def test_normalise_id_full_form_without_known() -> None:
    assert normalise_id("re-feat-7f3k2q", "RE") == "RE-FEAT-7F3K2Q"
    assert normalise_id("xx-func-7f3k2q", "RE") == "XX-FUNC-7F3K2Q"


def test_normalise_id_abbreviated_form_without_known_completes_prefix() -> None:
    assert normalise_id("feat-7f3k2q", "RE") == "RE-FEAT-7F3K2Q"


def test_normalise_id_bare_body_without_known_is_rejected() -> None:
    assert normalise_id("7f3k2q", "RE") is None


def test_normalise_id_bare_body_with_known() -> None:
    known = {"RE-FEAT-7F3K2Q", "RE-FUNC-2K7QMB"}
    assert normalise_id("7f3k2q", "RE", known=known) == "RE-FEAT-7F3K2Q"
    assert normalise_id("2k7qmb", "RE", known=known) == "RE-FUNC-2K7QMB"


def test_normalise_id_bare_body_ambiguous() -> None:
    known = {"RE-FEAT-7F3K2Q", "RE-FUNC-7F3K2Q"}
    assert normalise_id("7f3k2q", "RE", known=known) is None


def test_normalise_id_abbreviated_form_with_known() -> None:
    known = {"RE-FEAT-7F3K2Q", "XX-FEAT-7F3K2Q", "RE-FUNC-2K7QMB"}
    assert normalise_id("feat-7f3k2q", "RE", known=known) == "RE-FEAT-7F3K2Q"
    assert normalise_id("func-2k7qmb", "RE", known=known) == "RE-FUNC-2K7QMB"
    assert normalise_id("feat-2k7qmb", "RE", known=known) is None


def test_normalise_id_full_form_must_be_known() -> None:
    known = {"RE-FEAT-7F3K2Q"}
    assert normalise_id("RE-FEAT-7F3K2Q", "RE", known=known) == "RE-FEAT-7F3K2Q"
    assert normalise_id("RE-FUNC-2K7QMB", "RE", known=known) is None


def test_normalise_id_body_only_empty_known() -> None:
    assert normalise_id("7f3k2q", "RE", known=set()) is None


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not an id",
        "RE-ABC",
        "RE-FEAT-UUUUUU",
        "RE-FEAT-7F3K2!",
        "RE--FEAT-7F3K2Q",
        "RE-7F3K2Q",  # legacy form
        "7F3K2Q",
    ],
)
def test_normalise_id_rejects_invalid(raw: str) -> None:
    assert normalise_id(raw, "RE") is None


def test_normalise_id_strips_whitespace() -> None:
    assert normalise_id("  RE-FEAT-7F3K2Q\n", "RE") == "RE-FEAT-7F3K2Q"


def test_normalise_id_rejects_invalid_prefix_arg() -> None:
    with pytest.raises(ValueError):
        normalise_id("7F3K2Q", "re")
