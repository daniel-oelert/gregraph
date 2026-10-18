"""Tests for ``gregraph.core.graph`` (spec §6.1–6.5, §13.3, §16.1, §16.3).

Test-first (appendix C): link-time checks (``E-EDGE-RULE``, ``E-EDGE-EXCLUSIVE``,
duplicate no-op, ``E-CYCLE`` + path, target state, ``E-LINK-TARGET-MISSING``),
whole-graph Kahn cycle detection, reachability (1-level upstream over
hierarchical edges, unlimited downstream over directed edges), roots (D1),
orphans (§6.3), and the 5 000-node perf smoke test (§1.5). Hypothesis DAG
invariant tests are mandatory (S6 handoff).
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gregraph.core.graph import Edge, Graph, Node, build_graph
from gregraph.core.hashing import body_hash
from gregraph.core.models import Document, Link, LinkType, TemplateRef
from gregraph.core.rules import DIRECTED_EDGE_TYPES, EDGE_RULES, Kind
from gregraph.core.storage import document_paths, write_body, write_sidecar
from gregraph.core.workspace import load_index

if TYPE_CHECKING:
    from conftest import SampleGraph

UTC = dt.UTC
CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=UTC)
DOC_UUID = UUID(int=1 << 98)
KINDS: tuple[Kind, ...] = (
    "goal",
    "requirement",
    "design",
    "verification",
    "information",
)


def node(
    node_id: str, kind: Kind | None = "requirement", deprecated: bool = False
) -> Node:
    return Node(id=node_id, kind=kind, title=f"Title {node_id}", deprecated=deprecated)


def edge(source: str, link_type: LinkType, target: str) -> Edge:
    return Edge(source=source, type=link_type, target=target)


def graph(nodes: Iterable[Node], edges: Iterable[Edge] = ()) -> Graph:
    return Graph(nodes, edges)


def simple_graph(
    specs: dict[str, Kind],
    links: Iterable[tuple[str, str, str]],
) -> Graph:
    return graph(
        (node(nid, kind) for nid, kind in specs.items()),
        (edge(*link) for link in links),
    )


class TestConstruction:
    def test_nodes_and_edges(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "requirement"},
            [("A", "refines", "B")],
        )
        assert set(g.nodes) == {"A", "B"}
        assert g.edges == (edge("A", "refines", "B"),)
        assert g.outbound_edges("A") == (edge("A", "refines", "B"),)
        assert g.inbound_edges("B") == (edge("A", "refines", "B"),)
        assert g.inbound_edges("A") == ()
        assert g.outbound_edges("B") == ()

    def test_symmetric_edge_appears_on_both_nodes(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "relates-to", "B")],
        )
        assert g.edges_of("A") == (edge("A", "relates-to", "B"),)
        assert g.edges_of("B") == (edge("A", "relates-to", "B"),)
        assert g.inbound_edges("B") == (edge("A", "relates-to", "B"),)

    def test_duplicate_edges_collapse(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [
                ("A", "depends-on", "B"),
                ("A", "depends-on", "B"),
                ("A", "depends-on", "B"),
            ],
        )
        assert g.edges == (edge("A", "depends-on", "B"),)

    def test_symmetric_duplicates_collapse_unordered(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "relates-to", "B"), ("B", "relates-to", "A")],
        )
        assert len(g.edges) == 1
        assert g.has_edge("A", "relates-to", "B")
        assert g.has_edge("B", "relates-to", "A")

    def test_directed_reverse_is_not_a_duplicate(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "depends-on", "B"), ("B", "depends-on", "A")],
        )
        assert len(g.edges) == 2

    def test_edges_sorted_deterministically(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal"},
            [
                ("C", "depends-on", "A"),
                ("A", "relates-to", "B"),
                ("A", "depends-on", "C"),
            ],
        )
        assert g.edges == (
            edge("A", "depends-on", "C"),
            edge("A", "relates-to", "B"),
            edge("C", "depends-on", "A"),
        )

    def test_deprecated_flag(self) -> None:
        g = simple_graph({"A": "goal"}, [])
        assert not g.is_deprecated("A")
        g = graph([node("A", "goal", deprecated=True)], [])
        assert g.is_deprecated("A")

    def test_len_and_contains(self) -> None:
        g = simple_graph({"A": "goal", "B": "goal"}, [])
        assert len(g) == 2
        assert "A" in g
        assert "Z" not in g


class TestBuildGraph:
    def test_from_documents(self) -> None:
        document = Document(
            schema=1,
            uuid=DOC_UUID,
            id="RE-STORY-AAAAAA",
            type="user-story",
            title="Story",
            created=CREATED,
            created_by=None,
            template=TemplateRef(name="user-story", version=1),
            version=1,
            body_hash=body_hash("# Story\n"),
            assets=[],
            links=[
                Link(type="refines", target="RE-STORY-BBBBBB", target_version=1),
                Link(type="relates-to", target="RE-STORY-CCCCCC", target_version=1),
            ],
            deprecated=None,
            tags=[],
            extra={},
        )
        kinds: dict[str, Kind] = {"user-story": "requirement"}
        g = build_graph([document], kinds)
        assert g.kind_of("RE-STORY-AAAAAA") == "requirement"
        assert g.title_of("RE-STORY-AAAAAA") == "Story"
        assert set(g.edges) == {
            edge("RE-STORY-AAAAAA", "refines", "RE-STORY-BBBBBB"),
            edge("RE-STORY-AAAAAA", "relates-to", "RE-STORY-CCCCCC"),
        }

    def test_unknown_type_has_no_kind(self) -> None:
        document = Document(
            schema=1,
            uuid=DOC_UUID,
            id="RE-STORY-AAAAAA",
            type="mystery",
            title="Story",
            created=CREATED,
            created_by=None,
            template=TemplateRef(name="mystery", version=1),
            version=1,
            body_hash=body_hash("# Story\n"),
            assets=[],
            links=[],
            deprecated=None,
            tags=[],
            extra={},
        )
        g = build_graph([document], {})
        assert g.kind_of("RE-STORY-AAAAAA") is None


class TestCheckLinkKinds:
    @pytest.mark.parametrize("link_type", sorted(EDGE_RULES))
    @pytest.mark.parametrize("source_kind", KINDS)
    @pytest.mark.parametrize("target_kind", KINDS)
    def test_kind_rule_matrix(
        self, link_type: LinkType, source_kind: Kind, target_kind: Kind
    ) -> None:
        g = simple_graph({"A": source_kind, "B": target_kind}, [])
        check = g.check_link("A", link_type, "B")
        from gregraph.core.rules import edge_kind_allowed

        if edge_kind_allowed(link_type, source_kind, target_kind):
            assert check.outcome == "ok", check
        else:
            assert check.outcome == "refused"
            assert check.refusal is not None
            assert check.refusal.code == "E-EDGE-RULE"

    def test_rule_violation_message(self) -> None:
        g = simple_graph({"A": "information", "B": "goal"}, [])
        check = g.check_link("A", "refines", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-RULE"
        assert check.refusal.severity == "E"
        assert check.refusal.subject == "A"

    def test_unknown_kind_skips_rule_check(self) -> None:
        g = graph([node("A", kind=None), node("B", "goal")], [])
        check = g.check_link("A", "refines", "B")
        assert check.outcome == "ok"


class TestCheckLinkExclusion:
    def test_refines_excludes_derives_from_same_pair(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("A", "derives-from", "B")],
        )
        check = g.check_link("A", "refines", "B")
        assert check.outcome == "refused"
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-EXCLUSIVE"

    def test_derives_from_excludes_refines_same_pair(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("A", "refines", "B")],
        )
        check = g.check_link("A", "derives-from", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-EXCLUSIVE"

    def test_refines_vs_opposite_depends_on(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("B", "depends-on", "A")],
        )
        check = g.check_link("A", "refines", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-EXCLUSIVE"

    def test_derives_from_vs_opposite_depends_on(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("B", "depends-on", "A")],
        )
        check = g.check_link("A", "derives-from", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-EXCLUSIVE"

    def test_depends_on_vs_opposite_refines(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("B", "refines", "A")],
        )
        check = g.check_link("A", "depends-on", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-EXCLUSIVE"

    def test_depends_on_vs_opposite_derives_from(self) -> None:
        g = simple_graph(
            {"A": "design", "B": "requirement"},
            [("B", "derives-from", "A")],
        )
        check = g.check_link("A", "depends-on", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-EXCLUSIVE"

    def test_different_types_same_pair_allowed(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("A", "refines", "B")],
        )
        check = g.check_link("A", "depends-on", "B")
        assert check.outcome == "ok"

    def test_same_direction_refines_is_cycle_not_exclusion(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("B", "refines", "A")],
        )
        check = g.check_link("A", "refines", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-CYCLE"


class TestCheckLinkMultiplicity:
    def test_duplicate_directed_is_noop_notice(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "depends-on", "B")],
        )
        check = g.check_link("A", "depends-on", "B")
        assert check.outcome == "duplicate"
        assert check.accepted
        assert check.refusal is None

    def test_duplicate_symmetric_reverse_is_noop(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "relates-to", "B")],
        )
        check = g.check_link("B", "relates-to", "A")
        assert check.outcome == "duplicate"
        assert check.accepted

    def test_different_type_between_same_pair_is_not_duplicate(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "depends-on", "B")],
        )
        assert g.check_link("A", "relates-to", "B").outcome == "ok"


class TestCheckLinkCycle:
    def test_direct_cycle_has_path(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("B", "depends-on", "A")],
        )
        check = g.check_link("A", "depends-on", "B")
        assert check.outcome == "refused"
        assert check.refusal is not None
        assert check.refusal.code == "E-CYCLE"
        assert check.cycle_path == ("A", "B", "A")
        assert "A → B → A" in check.refusal.message

    def test_long_cycle_reconstructs_full_path(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal", "D": "goal"},
            [
                ("B", "depends-on", "C"),
                ("C", "depends-on", "D"),
                ("D", "depends-on", "A"),
            ],
        )
        check = g.check_link("A", "depends-on", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-CYCLE"
        assert check.cycle_path == ("A", "B", "C", "D", "A")

    def test_self_link_is_a_cycle(self) -> None:
        g = simple_graph({"A": "goal"}, [])
        check = g.check_link("A", "depends-on", "A")
        assert check.refusal is not None
        assert check.refusal.code == "E-CYCLE"
        assert check.cycle_path == ("A", "A")

    def test_acyclic_insertion_accepted(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal"},
            [("B", "depends-on", "C")],
        )
        assert g.check_link("A", "depends-on", "B").outcome == "ok"

    def test_symmetric_edges_never_cycle(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "relates-to", "B"), ("B", "relates-to", "A")],
        )
        assert g.check_link("A", "conflicts-with", "B").outcome == "ok"

    def test_cycle_detection_uses_all_directed_types(self) -> None:
        assert DIRECTED_EDGE_TYPES == {
            "refines",
            "derives-from",
            "depends-on",
            "satisfies",
            "verifies",
            "constrains",
            "supersedes",
        }
        g = simple_graph(
            {"A": "design", "B": "requirement"},
            [("B", "constrains", "A")],
        )
        check = g.check_link("A", "satisfies", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-CYCLE"


class TestCheckLinkTargetState:
    def _graph(self) -> Graph:
        return simple_graph(
            {
                "NEW": "requirement",
                "OLD": "requirement",
                "DEP": "requirement",
                "LIVE": "requirement",
            },
            [
                ("NEW", "supersedes", "OLD"),
            ],
        )

    def test_superseded_target_refused(self) -> None:
        g = self._graph()
        # mark OLD superseded via inbound supersedes from NEW (already present)
        check = g.check_link("LIVE", "depends-on", "OLD")
        assert check.refusal is not None
        assert check.refusal.code == "E-TARGET-SUPERSEDED"

    def test_deprecated_target_refused(self) -> None:
        g = graph(
            [
                node("LIVE"),
                node("DEP", deprecated=True),
            ],
            [],
        )
        check = g.check_link("LIVE", "depends-on", "DEP")
        assert check.refusal is not None
        assert check.refusal.code == "E-TARGET-DEPRECATED"

    def test_supersedes_may_target_superseded(self) -> None:
        g = simple_graph(
            {"NEWER": "requirement", "NEW": "requirement", "OLD": "requirement"},
            [("NEW", "supersedes", "OLD")],
        )
        assert g.check_link("NEWER", "supersedes", "OLD").outcome == "ok"

    def test_supersedes_may_target_deprecated(self) -> None:
        g = graph([node("NEWER"), node("DEP", deprecated=True)], [])
        assert g.check_link("NEWER", "supersedes", "DEP").outcome == "ok"

    def test_is_superseded(self) -> None:
        g = self._graph()
        assert g.is_superseded("OLD")
        assert not g.is_superseded("NEW")


class TestCheckLinkMissing:
    def test_missing_target(self) -> None:
        g = simple_graph({"A": "goal"}, [])
        check = g.check_link("A", "depends-on", "ZZZZZZ")
        assert check.refusal is not None
        assert check.refusal.code == "E-LINK-TARGET-MISSING"

    def test_missing_source_raises(self) -> None:
        g = simple_graph({"A": "goal"}, [])
        with pytest.raises(ValueError):
            g.check_link("ZZZZZZ", "depends-on", "A")


class TestCheckLinkPrecedence:
    def test_rule_beats_cycle(self) -> None:
        g = simple_graph(
            {"A": "information", "B": "goal"},
            [("B", "depends-on", "A")],
        )
        check = g.check_link("A", "refines", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-RULE"

    def test_exclusion_beats_cycle(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("B", "refines", "A")],
        )
        check = g.check_link("A", "depends-on", "B")
        assert check.refusal is not None
        assert check.refusal.code == "E-EDGE-EXCLUSIVE"

    def test_duplicate_beats_target_state(self) -> None:
        # LIVE -> OLD exists already and OLD is superseded; duplicate wins
        g = simple_graph(
            {"NEW": "requirement", "OLD": "requirement", "LIVE": "requirement"},
            [("NEW", "supersedes", "OLD"), ("LIVE", "depends-on", "OLD")],
        )
        check = g.check_link("LIVE", "depends-on", "OLD")
        assert check.outcome == "duplicate"


class TestWithLink:
    def test_ok_returns_new_graph(self) -> None:
        g = simple_graph({"A": "goal", "B": "goal"}, [])
        new_g, check = g.with_link("A", "depends-on", "B")
        assert check.outcome == "ok"
        assert new_g.has_edge("A", "depends-on", "B")
        assert not g.has_edge("A", "depends-on", "B")

    def test_duplicate_returns_same_edges(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "depends-on", "B")],
        )
        new_g, check = g.with_link("A", "depends-on", "B")
        assert check.outcome == "duplicate"
        assert new_g.edges == g.edges

    def test_refused_returns_self(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("B", "depends-on", "A")],
        )
        new_g, check = g.with_link("A", "depends-on", "B")
        assert check.outcome == "refused"
        assert new_g is g


class TestRoots:
    def test_roots_have_no_hierarchical_outbound(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "requirement", "C": "requirement", "D": "design"},
            [
                ("B", "refines", "A"),
                ("C", "derives-from", "B"),
                ("D", "satisfies", "A"),
            ],
        )
        assert set(g.roots()) == {"A", "D"}

    def test_empty_graph(self) -> None:
        assert graph([], []).roots() == ()

    def test_multiple_roots_allowed(self) -> None:
        g = simple_graph({"A": "goal", "B": "goal", "C": "goal"}, [])
        assert set(g.roots()) == {"A", "B", "C"}


class TestOrphans:
    def test_orphan_excludes_deprecated(self) -> None:
        g = graph(
            [node("A", "goal"), node("B", "goal", deprecated=True)],
            [],
        )
        assert set(g.orphans()) == {"A"}

    def test_orphan_excludes_superseded(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal"},
            [("A", "supersedes", "B")],
        )
        assert set(g.orphans()) == {"C"}

    def test_edges_of_any_type_disqualify(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal"},
            [("A", "relates-to", "B"), ("C", "depends-on", "B")],
        )
        assert g.orphans() == ()

    def test_inbound_only_is_not_orphan(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "depends-on", "B")],
        )
        assert g.orphans() == ()


class TestReachability:
    def _g(self) -> Graph:
        return simple_graph(
            {
                "goal": "goal",
                "epic": "goal",
                "feature": "requirement",
                "story": "requirement",
                "design": "design",
                "test": "verification",
                "pal": "information",
            },
            [
                ("epic", "refines", "goal"),
                ("feature", "refines", "epic"),
                ("story", "refines", "feature"),
                ("design", "satisfies", "feature"),
                ("test", "verifies", "story"),
                ("pal", "relates-to", "goal"),
            ],
        )

    def test_upstream_one_level_hierarchical_only(self) -> None:
        g = self._g()
        assert set(g.upstream("feature")) == {"epic"}
        assert set(g.upstream("goal")) == set()
        # verifies is not hierarchical
        assert set(g.upstream("test")) == set()
        assert set(g.upstream("story")) == {"feature"}

    def test_downstream_unlimited_over_directed(self) -> None:
        g = self._g()
        assert g.downstream("feature") == {
            "story": 1,
            "design": 1,
            "test": 2,
        }

    def test_downstream_depth_limit(self) -> None:
        g = self._g()
        assert g.downstream("feature", depth=1) == {"story": 1, "design": 1}
        assert g.downstream("feature", depth=0) == {}

    def test_downstream_ignores_symmetric(self) -> None:
        g = self._g()
        assert "pal" not in g.downstream("goal")
        assert "pal" not in g.downstream("goal", depth=5)

    def test_downstream_of_leaf(self) -> None:
        g = self._g()
        assert g.downstream("story") == {"test": 1}


class TestFindCycles:
    def test_acyclic_is_empty(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal"},
            [("A", "depends-on", "B"), ("B", "depends-on", "C")],
        )
        assert g.find_cycles() == []

    def test_reports_the_cycle(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal"},
            [
                ("A", "depends-on", "B"),
                ("B", "depends-on", "C"),
                ("C", "depends-on", "A"),
            ],
        )
        cycles = g.find_cycles()
        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle[0] == cycle[-1] == "A"
        assert set(cycle) == {"A", "B", "C"}

    def test_self_loop(self) -> None:
        g = simple_graph({"A": "goal"}, [("A", "depends-on", "A")])
        assert g.find_cycles() == [("A", "A")]

    def test_tail_beyond_cycle_not_reported(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "Y": "goal"},
            [
                ("A", "depends-on", "B"),
                ("B", "depends-on", "A"),
                ("Y", "depends-on", "A"),
            ],
        )
        cycles = g.find_cycles()
        assert len(cycles) == 1
        assert "Y" not in cycles[0]

    def test_two_disjoint_cycles(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal", "C": "goal", "D": "goal"},
            [
                ("A", "depends-on", "B"),
                ("B", "depends-on", "A"),
                ("C", "depends-on", "D"),
                ("D", "depends-on", "C"),
            ],
        )
        cycles = g.find_cycles()
        assert len(cycles) == 2
        merged = [frozenset(cycle[:-1]) for cycle in cycles]
        assert frozenset({"A", "B"}) in merged
        assert frozenset({"C", "D"}) in merged

    def test_mixed_edge_types_participate(self) -> None:
        g = simple_graph(
            {"A": "design", "B": "requirement", "C": "goal"},
            [
                ("A", "satisfies", "B"),
                ("B", "constrains", "C"),
                ("C", "depends-on", "A"),
            ],
        )
        assert len(g.find_cycles()) == 1

    def test_cross_type_cycle_reconstructed(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("A", "refines", "B"), ("B", "depends-on", "A")],
        )
        check = g.check_link("A", "relates-to", "B")
        assert check.outcome == "ok"  # symmetric, unrelated
        cycles = g.find_cycles()
        assert cycles and set(cycles[0]) >= {"A", "B"}


class TestValidationFindings:
    def test_clean_graph_has_none(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "requirement"},
            [("B", "refines", "A")],
        )
        assert g.validation_findings() == []

    def test_dangling_link(self) -> None:
        g = simple_graph(
            {"A": "goal"},
            [("A", "depends-on", "ZZZZZZ")],
        )
        [finding] = g.validation_findings()
        assert finding.code == "E-LINK-TARGET-MISSING"
        assert finding.subject == "A"
        assert finding.fix == "gregraph unlink A depends-on ZZZZZZ"

    def test_rule_violation(self) -> None:
        g = simple_graph(
            {"A": "information", "B": "goal"},
            [("A", "refines", "B")],
        )
        [finding] = g.validation_findings()
        assert finding.code == "E-EDGE-RULE"
        assert finding.severity == "E"

    def test_exclusive_pair(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement"},
            [("A", "refines", "B"), ("A", "derives-from", "B")],
        )
        findings = g.validation_findings()
        assert [f.code for f in findings] == ["E-EDGE-EXCLUSIVE"]

    def test_cycle_finding(self) -> None:
        g = simple_graph(
            {"A": "goal", "B": "goal"},
            [("A", "depends-on", "B"), ("B", "depends-on", "A")],
        )
        findings = g.validation_findings()
        assert [f.code for f in findings] == ["E-CYCLE"]
        assert "→" in findings[0].message

    def test_reports_all_categories(self) -> None:
        g = simple_graph(
            {"A": "requirement", "B": "requirement", "I": "information"},
            [
                ("A", "refines", "B"),
                ("A", "derives-from", "B"),
                ("I", "refines", "B"),
                ("B", "depends-on", "ZZZZZZ"),
            ],
        )
        codes = {f.code for f in g.validation_findings()}
        assert codes == {"E-EDGE-EXCLUSIVE", "E-EDGE-RULE", "E-LINK-TARGET-MISSING"}


class TestSampleGraph:
    def test_covers_all_kinds_and_edge_types(self, sample_graph: SampleGraph) -> None:
        g = sample_graph.graph
        kinds_seen = {entry.kind for entry in g.nodes.values()}
        assert kinds_seen == set(KINDS)
        types_seen = {e.type for e in g.edges}
        assert types_seen == set(EDGE_RULES)

    def test_roots_match_definition(self, sample_graph: SampleGraph) -> None:
        ids = sample_graph.ids
        roots = set(sample_graph.graph.roots())
        # §6.3/D1: no outbound refines/derives-from
        assert roots == {
            ids["goal"],
            ids["compliance"],
            ids["story_old"],
            ids["nfr"],
            ids["design"],
            ids["test"],
            ids["stakeholder"],
            ids["orphan"],
            ids["stale_note"],
        }

    def test_orphans_match_definition(self, sample_graph: SampleGraph) -> None:
        ids = sample_graph.ids
        assert set(sample_graph.graph.orphans()) == {ids["orphan"]}

    def test_superseded_and_deprecated(self, sample_graph: SampleGraph) -> None:
        g = sample_graph.graph
        ids = sample_graph.ids
        assert g.is_superseded(ids["story_old"])
        assert not g.is_superseded(ids["story"])
        assert g.is_deprecated(ids["stale_note"])
        assert not g.is_deprecated(ids["orphan"])

    def test_upstream_downstream(self, sample_graph: SampleGraph) -> None:
        g = sample_graph.graph
        ids = sample_graph.ids
        assert set(g.upstream(ids["feature"])) == {ids["epic"]}
        assert set(g.upstream(ids["fr"])) == {ids["scan_story"]}
        assert g.downstream(ids["feature"]) == {
            ids["story"]: 1,
            ids["scan_story"]: 1,
            ids["nfr"]: 1,
            ids["design"]: 1,
            ids["fr"]: 2,
            ids["test"]: 2,
        }

    def test_sample_is_valid(self, sample_graph: SampleGraph) -> None:
        assert sample_graph.graph.validation_findings() == []
        assert sample_graph.workspace.index.findings == ()


DAG_TYPES: tuple[LinkType, ...] = tuple(sorted(DIRECTED_EDGE_TYPES))
NODE_COUNT = 6


def _reachable(edges: Iterable[tuple[str, str]], start: str, goal: str) -> bool:
    succ: dict[str, set[str]] = {}
    for source, target in edges:
        succ.setdefault(source, set()).add(target)
    seen = {start}
    queue = [start]
    while queue:
        node_id = queue.pop()
        for nxt in succ.get(node_id, ()):
            if nxt == goal:
                return True
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(proposals=st.lists(st.tuples(st.integers(0, 5), st.integers(0, 5)), max_size=30))
def test_hypothesis_accepts_exactly_acyclic_insertions(
    proposals: list[tuple[int, int]],
) -> None:
    """DAG invariant (§6.2, §17): depends-on-only insertions on 6 goal nodes.

    With only ``depends-on`` between ``goal`` nodes no kind rule or exclusion
    can bind, so the tool must accept an insertion exactly when it does not
    close a cycle, report duplicates as no-ops, and never leave a cyclic graph.
    """
    nodes = [node(f"N{i}", "goal") for i in range(NODE_COUNT)]
    g = Graph(nodes, [])
    applied: list[tuple[str, str]] = []
    for source_i, target_i in proposals:
        source, target = f"N{source_i}", f"N{target_i}"
        would_cycle = source == target or _reachable(applied, target, source)
        already = (source, target) in applied
        check = g.check_link(source, "depends-on", target)
        if already:
            assert check.outcome == "duplicate", (source, target, check)
        elif would_cycle:
            assert check.outcome == "refused", (source, target, check)
            assert check.refusal is not None
            assert check.refusal.code == "E-CYCLE"
            assert check.cycle_path is not None
            assert check.cycle_path[0] == source
            assert check.cycle_path[-1] == source
        else:
            assert check.outcome == "ok", (source, target, check)
            applied.append((source, target))
            g, _ = g.with_link(source, "depends-on", target)
    assert g.find_cycles() == []
    assert not g.validation_findings()


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    proposals=st.lists(
        st.tuples(
            st.integers(0, 4),
            st.sampled_from(DAG_TYPES),
            st.integers(0, 4),
        ),
        max_size=25,
    )
)
def test_hypothesis_never_accepts_a_cycle(
    proposals: list[tuple[int, LinkType, int]],
) -> None:
    """Mixed edge types: every accepted insertion keeps the graph acyclic (§6.2)."""
    kinds: tuple[Kind, ...] = ("goal", "requirement", "design", "requirement", "goal")
    nodes = [node(f"N{i}", kinds[i]) for i in range(5)]
    g = Graph(nodes, [])
    directed_applied: list[tuple[str, str]] = []
    for source_i, link_type, target_i in proposals:
        source, target = f"N{source_i}", f"N{target_i}"
        would_cycle = link_type in DIRECTED_EDGE_TYPES and (
            source == target or _reachable(directed_applied, target, source)
        )
        check = g.check_link(source, link_type, target)
        if would_cycle:
            assert check.outcome == "refused", (source, link_type, target, check)
            assert check.refusal is not None
        if check.outcome == "refused":
            assert check.refusal is not None
            assert check.refusal.code in {
                "E-EDGE-RULE",
                "E-EDGE-EXCLUSIVE",
                "E-CYCLE",
                "E-TARGET-SUPERSEDED",
                "E-TARGET-DEPRECATED",
                "E-LINK-TARGET-MISSING",
            }
        elif check.outcome == "ok":
            g, _ = g.with_link(source, link_type, target)
            if link_type in DIRECTED_EDGE_TYPES:
                directed_applied.append((source, target))
    assert g.find_cycles() == []


@pytest.mark.slow
def test_perf_smoke_5000_nodes(tmp_path: Path) -> None:
    """Informal budget (§1.5): 5 000 sidecars load < 1.5 s; cycle check < 5 s."""
    from gregraph.core.ids import derive_id

    folder = "perf"
    n = 5000
    uuids = [UUID(int=i << 98) for i in range(1, n + 1)]
    ids = [derive_id(u, "RE", "FEAT") for u in uuids]
    assert len(set(ids)) == n
    for i, doc_id in enumerate(ids):
        links = (
            [Link(type="depends-on", target=ids[i + 1], target_version=1)]
            if i + 1 < n
            else []
        )
        document = Document(
            schema=1,
            uuid=uuids[i],
            id=doc_id,
            type="user-story",
            title=f"Perf node {i}",
            created=CREATED,
            created_by=None,
            template=TemplateRef(name="user-story", version=1),
            version=1,
            body_hash=body_hash(f"# Perf node {i}\n"),
            assets=[],
            links=links,
            deprecated=None,
            tags=[],
            extra={},
        )
        body_rel, sidecar_rel = document_paths(Path(), folder, doc_id)
        write_body(tmp_path / body_rel, f"# Perf node {i}\n")
        write_sidecar(tmp_path / sidecar_rel, document)

    start = time.perf_counter()
    index = load_index(tmp_path)
    load_seconds = time.perf_counter() - start
    assert len(index.documents) == n
    assert index.findings == ()

    kinds: dict[str, Kind] = {"user-story": "requirement"}
    start = time.perf_counter()
    g = build_graph((entry.model for entry in index.documents.values()), kinds)
    cycles = g.find_cycles()
    check_seconds = time.perf_counter() - start

    assert cycles == []
    assert load_seconds < 5.0, f"load took {load_seconds:.2f}s (budget 1.5s)"
    assert check_seconds < 5.0, f"cycle-check took {check_seconds:.2f}s (budget 5s)"
