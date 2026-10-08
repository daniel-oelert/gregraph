"""Tests for ``gregraph.core.rules`` (spec §6.1–6.4).

Test-first for S1: the edge-type table as data, kind set, directed-edge set
for cycle detection, same-kind rule for ``supersedes``, and the mutual-exclusion
pairs of §6.4.
"""

from __future__ import annotations

from typing import get_args

import pytest

from gregraph.core.models import LinkType
from gregraph.core.rules import (
    DIRECTED_EDGE_TYPES,
    EDGE_RULES,
    KINDS,
    MUTUALLY_EXCLUSIVE_OPPOSITE,
    MUTUALLY_EXCLUSIVE_SAME_PAIR,
    SYMMETRIC_EDGE_TYPES,
    EdgeRule,
    Kind,
    edge_kind_allowed,
    is_mutually_exclusive,
)

ALL_KINDS: frozenset[Kind] = frozenset(get_args(Kind))

EXPECTED_TABLE: dict[str, EdgeRule] = {
    "refines": EdgeRule(
        direction="directed",
        hierarchical=True,
        source_kinds=frozenset({"goal", "requirement"}),
        target_kinds=frozenset({"goal", "requirement"}),
    ),
    "derives-from": EdgeRule(
        direction="directed",
        hierarchical=True,
        source_kinds=frozenset({"requirement", "design"}),
        target_kinds=frozenset({"goal", "requirement", "design"}),
    ),
    "depends-on": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=frozenset({"goal", "requirement", "design"}),
        target_kinds=frozenset({"goal", "requirement", "design"}),
    ),
    "satisfies": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=frozenset({"design"}),
        target_kinds=frozenset({"goal", "requirement"}),
    ),
    "verifies": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=frozenset({"verification"}),
        target_kinds=frozenset({"requirement", "design"}),
    ),
    "constrains": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=frozenset({"requirement"}),
        target_kinds=frozenset({"goal", "requirement", "design"}),
    ),
    "supersedes": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=ALL_KINDS,
        target_kinds=ALL_KINDS,
        same_kind_only=True,
    ),
    "conflicts-with": EdgeRule(
        direction="symmetric",
        hierarchical=False,
        source_kinds=frozenset({"goal", "requirement", "design"}),
        target_kinds=frozenset({"goal", "requirement", "design"}),
    ),
    "relates-to": EdgeRule(
        direction="symmetric",
        hierarchical=False,
        source_kinds=ALL_KINDS,
        target_kinds=ALL_KINDS,
    ),
}

EXPECTED_DIRECTED = frozenset(
    {
        "refines",
        "derives-from",
        "depends-on",
        "satisfies",
        "verifies",
        "constrains",
        "supersedes",
    }
)
EXPECTED_SYMMETRIC = frozenset({"conflicts-with", "relates-to"})


def test_edge_table_matches_spec_table() -> None:
    assert dict(EDGE_RULES) == EXPECTED_TABLE


def test_every_link_type_has_rule() -> None:
    assert set(EDGE_RULES) == set(get_args(LinkType))


def test_kind_set_matches_spec() -> None:
    assert KINDS == frozenset(
        {"goal", "requirement", "design", "verification", "information"}
    )


def test_directed_edge_set_matches_spec() -> None:
    assert DIRECTED_EDGE_TYPES == EXPECTED_DIRECTED
    assert DIRECTED_EDGE_TYPES == frozenset(
        name for name, rule in EDGE_RULES.items() if rule.direction == "directed"
    )


def test_symmetric_edge_set() -> None:
    assert SYMMETRIC_EDGE_TYPES == EXPECTED_SYMMETRIC


def test_symmetric_types_not_in_directed_set() -> None:
    assert not (SYMMETRIC_EDGE_TYPES & DIRECTED_EDGE_TYPES)


def test_directed_and_symmetric_partition_all_types() -> None:
    assert DIRECTED_EDGE_TYPES | SYMMETRIC_EDGE_TYPES == set(get_args(LinkType))


def test_rule_kind_sets_within_kind_set() -> None:
    for rule in EDGE_RULES.values():
        assert rule.source_kinds <= KINDS
        assert rule.target_kinds <= KINDS
        assert rule.source_kinds
        assert rule.target_kinds


def test_symmetric_rules_have_equal_kind_sets() -> None:
    for name in SYMMETRIC_EDGE_TYPES:
        rule = EDGE_RULES[name]
        assert rule.source_kinds == rule.target_kinds


def test_hierarchical_types_are_refines_and_derives_from() -> None:
    hierarchical = {name for name, rule in EDGE_RULES.items() if rule.hierarchical}
    assert hierarchical == {"refines", "derives-from"}


@pytest.mark.parametrize(
    ("edge_type", "source", "target", "expected"),
    [
        ("refines", "requirement", "goal", True),
        ("refines", "goal", "requirement", True),
        ("refines", "design", "requirement", False),
        ("refines", "verification", "goal", False),
        ("derives-from", "design", "design", True),
        ("derives-from", "goal", "goal", False),
        ("derives-from", "requirement", "design", True),
        ("depends-on", "design", "goal", True),
        ("depends-on", "verification", "design", False),
        ("satisfies", "design", "requirement", True),
        ("satisfies", "design", "design", False),
        ("satisfies", "requirement", "goal", False),
        ("verifies", "verification", "design", True),
        ("verifies", "verification", "goal", False),
        ("verifies", "requirement", "requirement", False),
        ("constrains", "requirement", "design", True),
        ("constrains", "design", "requirement", False),
        ("constrains", "goal", "goal", False),
        ("supersedes", "requirement", "requirement", True),
        ("supersedes", "goal", "requirement", False),
        ("supersedes", "information", "information", True),
        ("conflicts-with", "goal", "design", True),
        ("conflicts-with", "verification", "requirement", False),
        ("relates-to", "verification", "information", True),
        ("relates-to", "goal", "goal", True),
    ],
)
def test_edge_kind_allowed(
    edge_type: LinkType, source: Kind, target: Kind, expected: bool
) -> None:
    assert edge_kind_allowed(edge_type, source, target) is expected


@pytest.mark.parametrize(
    ("first", "second", "opposite_direction", "expected"),
    [
        ("refines", "derives-from", False, True),
        ("derives-from", "refines", False, True),
        ("refines", "depends-on", True, True),
        ("depends-on", "refines", True, True),
        ("derives-from", "depends-on", True, True),
        ("depends-on", "derives-from", True, True),
        ("refines", "depends-on", False, False),
        ("derives-from", "depends-on", False, False),
        ("refines", "derives-from", True, False),
        ("refines", "refines", False, False),
        ("refines", "relates-to", False, False),
        ("conflicts-with", "relates-to", True, False),
        ("depends-on", "satisfies", True, False),
    ],
)
def test_is_mutually_exclusive(
    first: LinkType, second: LinkType, opposite_direction: bool, expected: bool
) -> None:
    actual = is_mutually_exclusive(first, second, opposite_direction=opposite_direction)
    assert actual is expected


def test_mutually_exclusive_tables_are_disjoint() -> None:
    assert not (MUTUALLY_EXCLUSIVE_SAME_PAIR & MUTUALLY_EXCLUSIVE_OPPOSITE)


def test_mutually_exclusive_tables_use_known_types() -> None:
    for table in (MUTUALLY_EXCLUSIVE_SAME_PAIR, MUTUALLY_EXCLUSIVE_OPPOSITE):
        for pair in table:
            assert len(pair) == 2
            assert pair <= set(get_args(LinkType))


def test_edge_rule_is_frozen() -> None:
    rule = EDGE_RULES["refines"]
    with pytest.raises((AttributeError, TypeError)):
        rule.hierarchical = False  # type: ignore[misc]
