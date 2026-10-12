"""Edge-type table and kind rules as data, not logic (spec §6.1–6.4, §16.1–16.2).

For each of the 9 edge types: direction (directed/symmetric), allowed source
kinds, allowed target kinds; kind set; mutual-exclusion pairs (``refines``/
``derives-from``, §6.4); directed-edge set used for cycle detection (§6.2).
Data only, so a later plugin system can extend it. Pure data/logic only —
no I/O, no printing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

from gregraph.core.models import LinkType

Kind = Literal["goal", "requirement", "design", "verification", "information"]
EdgeDirection = Literal["directed", "symmetric"]

KINDS: Final[frozenset[Kind]] = frozenset(get_args(Kind))


@dataclass(frozen=True, slots=True)
class EdgeRule:
    """Per-type rule row of the §6.1 table.

    ``same_kind_only`` encodes ``supersedes`` ("same kind → same kind");
    ``hierarchical`` marks the decomposition edges of §6.1 (used for roots,
    §6.3).
    """

    direction: EdgeDirection
    hierarchical: bool
    source_kinds: frozenset[Kind]
    target_kinds: frozenset[Kind]
    same_kind_only: bool = False


def _kinds(*values: Kind) -> frozenset[Kind]:
    return frozenset(values)


def _pair(*values: LinkType) -> frozenset[LinkType]:
    return frozenset(values)


_ALL_KINDS: Final[frozenset[Kind]] = KINDS
_GOAL_REQUIREMENT: Final[frozenset[Kind]] = _kinds("goal", "requirement")
_GOAL_REQUIREMENT_DESIGN: Final[frozenset[Kind]] = _kinds(
    "goal", "requirement", "design"
)
_REQUIREMENT_DESIGN: Final[frozenset[Kind]] = _kinds("requirement", "design")

EDGE_RULES: Final[dict[LinkType, EdgeRule]] = {
    "refines": EdgeRule(
        direction="directed",
        hierarchical=True,
        source_kinds=_GOAL_REQUIREMENT,
        target_kinds=_GOAL_REQUIREMENT,
    ),
    "derives-from": EdgeRule(
        direction="directed",
        hierarchical=True,
        source_kinds=_REQUIREMENT_DESIGN,
        target_kinds=_GOAL_REQUIREMENT_DESIGN,
    ),
    "depends-on": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=_GOAL_REQUIREMENT_DESIGN,
        target_kinds=_GOAL_REQUIREMENT_DESIGN,
    ),
    "satisfies": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=_kinds("design"),
        target_kinds=_GOAL_REQUIREMENT,
    ),
    "verifies": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=_kinds("verification"),
        target_kinds=_REQUIREMENT_DESIGN,
    ),
    "constrains": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=_kinds("requirement"),
        target_kinds=_GOAL_REQUIREMENT_DESIGN,
    ),
    "supersedes": EdgeRule(
        direction="directed",
        hierarchical=False,
        source_kinds=_ALL_KINDS,
        target_kinds=_ALL_KINDS,
        same_kind_only=True,
    ),
    "conflicts-with": EdgeRule(
        direction="symmetric",
        hierarchical=False,
        source_kinds=_GOAL_REQUIREMENT_DESIGN,
        target_kinds=_GOAL_REQUIREMENT_DESIGN,
    ),
    "relates-to": EdgeRule(
        direction="symmetric",
        hierarchical=False,
        source_kinds=_ALL_KINDS,
        target_kinds=_ALL_KINDS,
    ),
}

DIRECTED_EDGE_TYPES: Final[frozenset[LinkType]] = frozenset(
    name for name, rule in EDGE_RULES.items() if rule.direction == "directed"
)
SYMMETRIC_EDGE_TYPES: Final[frozenset[LinkType]] = frozenset(
    name for name, rule in EDGE_RULES.items() if rule.direction == "symmetric"
)

MUTUALLY_EXCLUSIVE_SAME_PAIR: Final[frozenset[frozenset[LinkType]]] = frozenset(
    {_pair("refines", "derives-from")}
)
MUTUALLY_EXCLUSIVE_OPPOSITE: Final[frozenset[frozenset[LinkType]]] = frozenset(
    {_pair("refines", "depends-on"), _pair("derives-from", "depends-on")}
)


def edge_kind_allowed(edge_type: LinkType, source: Kind, target: Kind) -> bool:
    """Whether a ``source`` → ``target`` edge of ``edge_type`` passes §6.1."""
    rule = EDGE_RULES[edge_type]
    if source not in rule.source_kinds or target not in rule.target_kinds:
        return False
    return not (rule.same_kind_only and source != target)


def is_mutually_exclusive(
    first: LinkType, second: LinkType, *, opposite_direction: bool = False
) -> bool:
    """Whether two edge types may not coexist between one pair (spec §6.4).

    ``opposite_direction=False``: both edges share one ordered pair (A→B).
    ``opposite_direction=True``: the edges run in opposite directions (A→B
    and B→A).
    """
    pair = _pair(first, second)
    if opposite_direction:
        return pair in MUTUALLY_EXCLUSIVE_OPPOSITE
    return pair in MUTUALLY_EXCLUSIVE_SAME_PAIR
