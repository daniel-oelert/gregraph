"""In-memory graph: nodes, edges, inbound index, cycles (spec §6, §16.1, §16.3).

Built from document sidecars: outbound edges as stored, computed inbound index
(§6.5 — symmetric edges appear on both nodes). Link-time checks of §13.3
(classified refusals: ``E-EDGE-RULE``, ``E-EDGE-EXCLUSIVE``, duplicate no-op
notice, ``E-TARGET-SUPERSEDED``/``E-TARGET-DEPRECATED`` except for
``supersedes``, ``E-CYCLE`` with reconstructed path, ``E-LINK-TARGET-MISSING``)
compose :func:`Graph.check_link`. Whole-graph cycle detection uses Kahn's
algorithm with concrete cycle extraction (§6.2); reachability helpers implement
the §13.11 up/down view (1-level upstream over hierarchical edges, unlimited
downstream over directed edges). Roots (§6.3/D1) and orphans (§6.3) are queries.
DFS/BFS/Kahn are iterative — no recursion limits at 10 000 nodes (§1.5).
No networkx (spec §16.3). Pure data/logic only — no I/O, no printing.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from gregraph.core.models import Document, Finding, LinkType
from gregraph.core.rules import (
    DIRECTED_EDGE_TYPES,
    EDGE_RULES,
    Kind,
    edge_kind_allowed,
    is_mutually_exclusive,
)

CheckOutcome = Literal["ok", "duplicate", "refused"]

_HIERARCHICAL_TYPES: Final[frozenset[LinkType]] = frozenset(
    name for name, rule in EDGE_RULES.items() if rule.hierarchical
)


def _edge_key(source: str, edge_type: LinkType, target: str) -> tuple[str, str, str]:
    """De-duplication key: directed edges by ordered pair, symmetric unordered."""
    if EDGE_RULES[edge_type].direction == "symmetric":
        low, high = sorted((source, target))
        return (low, high, edge_type)
    return (source, target, edge_type)


@dataclass(frozen=True, slots=True)
class Edge:
    """One graph edge as stored on ``source`` (spec §6.1)."""

    source: str
    type: LinkType
    target: str


@dataclass(frozen=True, slots=True)
class Node:
    """One graph node (spec §5.1). ``kind`` is ``None`` for unknown types."""

    id: str
    kind: Kind | None
    title: str
    deprecated: bool


@dataclass(frozen=True, slots=True)
class LinkCheck:
    """Outcome of :meth:`Graph.check_link` (spec §6.4, §13.3).

    ``duplicate`` is the §6.4 no-op notice (accepted, nothing to write);
    ``refused`` carries the refusal ``Finding`` and, for ``E-CYCLE``, the
    reconstructed closed ``cycle_path``.
    """

    outcome: CheckOutcome
    refusal: Finding | None = None
    cycle_path: tuple[str, ...] | None = None

    @property
    def accepted(self) -> bool:
        """Whether the insertion is allowed (``ok`` or ``duplicate`` no-op)."""
        return self.outcome != "refused"


class Graph:
    """Directed/symmetric edge set with inbound index (spec §6).

    Constructed from nodes and edges (duplicates collapsed: at most one edge of
    a given type per ordered pair — unordered for symmetric types, §6.4).
    ``build_graph`` maps document sidecars onto this. The graph *holds* whatever
    the files say; :meth:`validation_findings` reports the violations and
    :meth:`check_link` prevents creating new ones.
    """

    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge] = ()) -> None:
        self._nodes: dict[str, Node] = {}
        for entry in nodes:
            self._nodes.setdefault(entry.id, entry)
        self._edge_keys: set[tuple[str, str, str]] = set()
        unique: list[Edge] = []
        for edge in edges:
            key = _edge_key(edge.source, edge.type, edge.target)
            if key in self._edge_keys:
                continue
            self._edge_keys.add(key)
            unique.append(edge)
        self._edges: tuple[Edge, ...] = tuple(
            sorted(unique, key=lambda e: (e.source, e.type, e.target))
        )
        self._outbound: dict[str, dict[LinkType, set[str]]] = {}
        self._inbound: dict[str, dict[LinkType, set[str]]] = {}
        out_lists: dict[str, list[Edge]] = {}
        in_lists: dict[str, list[Edge]] = {}
        for edge in self._edges:
            self._outbound.setdefault(edge.source, {}).setdefault(edge.type, set()).add(
                edge.target
            )
            self._inbound.setdefault(edge.target, {}).setdefault(edge.type, set()).add(
                edge.source
            )
            out_lists.setdefault(edge.source, []).append(edge)
            in_lists.setdefault(edge.target, []).append(edge)
        self._out_lists: dict[str, tuple[Edge, ...]] = {
            key: tuple(value) for key, value in out_lists.items()
        }
        self._in_lists: dict[str, tuple[Edge, ...]] = {
            key: tuple(value) for key, value in in_lists.items()
        }

    @property
    def nodes(self) -> Mapping[str, Node]:
        """Nodes keyed by document ID (insertion order = build order)."""
        return self._nodes

    @property
    def edges(self) -> tuple[Edge, ...]:
        """All edges, sorted by ``(source, type, target)``."""
        return self._edges

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def kind_of(self, node_id: str) -> Kind | None:
        entry = self._nodes.get(node_id)
        return entry.kind if entry is not None else None

    def title_of(self, node_id: str) -> str | None:
        entry = self._nodes.get(node_id)
        return entry.title if entry is not None else None

    def is_deprecated(self, node_id: str) -> bool:
        entry = self._nodes.get(node_id)
        return entry.deprecated if entry is not None else False

    def is_superseded(self, node_id: str) -> bool:
        """Whether any ``supersedes`` edge points at ``node_id`` (spec §7.6)."""
        return bool(self._inbound.get(node_id, {}).get("supersedes"))

    def has_edge(self, source: str, edge_type: LinkType, target: str) -> bool:
        """Whether the edge exists; symmetric edges match either orientation."""
        return _edge_key(source, edge_type, target) in self._edge_keys

    def outbound_edges(self, node_id: str) -> tuple[Edge, ...]:
        """Edges stored on ``node_id`` (spec §5.4 stores outbound links)."""
        return self._out_lists.get(node_id, ())

    def inbound_edges(self, node_id: str) -> tuple[Edge, ...]:
        """Computed inbound edges (spec §6.5); symmetric edges appear here too."""
        return self._in_lists.get(node_id, ())

    def edges_of(self, node_id: str) -> tuple[Edge, ...]:
        """All edges touching ``node_id`` in either role (deduplicated)."""
        seen: dict[Edge, None] = {}
        touching = (
            *self._out_lists.get(node_id, ()),
            *self._in_lists.get(node_id, ()),
        )
        for edge in touching:
            seen.setdefault(edge, None)
        return tuple(seen)

    def upstream(self, node_id: str) -> tuple[str, ...]:
        """One level upstream: targets of outbound hierarchical edges (§13.11)."""
        targets: set[str] = set()
        for link_type, ends in self._outbound.get(node_id, {}).items():
            if link_type in _HIERARCHICAL_TYPES:
                targets.update(end for end in ends if end in self._nodes)
        return tuple(sorted(targets))

    def downstream(self, node_id: str, depth: int | None = None) -> dict[str, int]:
        """Nodes that link to ``node_id``, transitively over directed edges (§13.11).

        Returns ``{id: minimum depth}`` excluding ``node_id`` itself; ``depth``
        limits how many levels are followed (``None`` = unlimited).
        """
        if node_id not in self._nodes or (depth is not None and depth <= 0):
            return {}
        result: dict[str, int] = {}
        frontier: set[str] = {node_id}
        distance = 0
        while frontier and (depth is None or distance < depth):
            distance += 1
            next_frontier: set[str] = set()
            for current in frontier:
                for pred in self._directed_predecessors(current):
                    if pred == node_id or pred in result or pred not in self._nodes:
                        continue
                    result[pred] = distance
                    next_frontier.add(pred)
            frontier = next_frontier
        return result

    def roots(self) -> tuple[str, ...]:
        """Nodes with no outbound ``refines``/``derives-from`` edge (§6.3/D1)."""
        result: list[str] = []
        for node_id in self._nodes:
            outbound = self._outbound.get(node_id, {})
            has_hierarchical = any(
                link_type in _HIERARCHICAL_TYPES and ends
                for link_type, ends in outbound.items()
            )
            if not has_hierarchical:
                result.append(node_id)
        return tuple(sorted(result))

    def orphans(self) -> tuple[str, ...]:
        """Nodes with no edges in either direction, excluding deprecated and
        superseded nodes (spec §6.3)."""
        result: list[str] = []
        for node_id in self._nodes:
            if self.is_deprecated(node_id) or self.is_superseded(node_id):
                continue
            if self._outbound.get(node_id) or self._inbound.get(node_id):
                continue
            result.append(node_id)
        return tuple(sorted(result))

    def check_link(self, source: str, edge_type: LinkType, target: str) -> LinkCheck:
        """Classify adding ``source --edge_type--> target`` (spec §6.4, §13.3).

        Check order (deterministic precedence): missing target → kind rule →
        mutual exclusion → duplicate no-op → target state → cycle. Raises
        ``ValueError`` for an unknown ``source`` (caller bug).
        """
        if source not in self._nodes:
            raise ValueError(f"unknown source node: {source!r}")
        if target not in self._nodes:
            return LinkCheck(
                outcome="refused",
                refusal=Finding(
                    code="E-LINK-TARGET-MISSING",
                    severity="E",
                    subject=source,
                    message=f"edge {edge_type} → {target}: target does not exist",
                ),
            )
        source_kind = self._nodes[source].kind
        target_kind = self._nodes[target].kind
        if source_kind is not None and target_kind is not None:
            if not edge_kind_allowed(edge_type, source_kind, target_kind):
                return LinkCheck(
                    outcome="refused",
                    refusal=Finding(
                        code="E-EDGE-RULE",
                        severity="E",
                        subject=source,
                        message=(
                            f"{source} ({source_kind}) cannot {edge_type} "
                            f"{target} ({target_kind})"
                        ),
                    ),
                )
        exclusion = self._exclusion_conflict(source, edge_type, target)
        if exclusion is not None:
            return LinkCheck(
                outcome="refused",
                refusal=self._exclusion_finding(source, edge_type, target, exclusion),
            )
        if self.has_edge(source, edge_type, target):
            return LinkCheck(outcome="duplicate")
        if edge_type != "supersedes":
            if self.is_superseded(target):
                return LinkCheck(
                    outcome="refused",
                    refusal=Finding(
                        code="E-TARGET-SUPERSEDED",
                        severity="E",
                        subject=source,
                        message=f"target {target} is superseded",
                    ),
                )
            if self.is_deprecated(target):
                return LinkCheck(
                    outcome="refused",
                    refusal=Finding(
                        code="E-TARGET-DEPRECATED",
                        severity="E",
                        subject=source,
                        message=f"target {target} is deprecated",
                    ),
                )
        if edge_type in DIRECTED_EDGE_TYPES:
            cycle_path = self._cycle_if_added(source, target)
            if cycle_path is not None:
                rendered = " → ".join(cycle_path)
                return LinkCheck(
                    outcome="refused",
                    refusal=Finding(
                        code="E-CYCLE",
                        severity="E",
                        subject=source,
                        message=(
                            f"linking {source} {edge_type} {target} "
                            f"would create a cycle: {rendered}"
                        ),
                    ),
                    cycle_path=cycle_path,
                )
        return LinkCheck(outcome="ok")

    def with_link(
        self, source: str, edge_type: LinkType, target: str
    ) -> tuple[Graph, LinkCheck]:
        """``(graph, check)``: a new graph with the edge on ``ok``, else unchanged."""
        check = self.check_link(source, edge_type, target)
        if check.outcome != "ok":
            return self, check
        added = Edge(source=source, type=edge_type, target=target)
        return Graph(self._nodes.values(), (*self._edges, added)), check

    def find_cycles(self) -> list[tuple[str, ...]]:
        """All concrete cycles among directed edges as closed paths (§6.2).

        Kahn's algorithm over the whole graph first (nodes it cannot process
        are the only possible cycle members and their tails); within that
        residual set one concrete cycle is extracted per remaining cycle region.
        Symmetric edges never participate (spec §6.2).
        """
        residual = self._kahn_residual()
        if not residual:
            return []
        cycles: list[tuple[str, ...]] = []
        remaining = set(residual)
        while remaining:
            start = min(remaining)
            cycle = self._cycle_through(start, remaining)
            if cycle is None:
                remaining.discard(start)
            else:
                cycles.append(cycle)
                remaining.difference_update(cycle[:-1])
        return sorted(cycles)

    def validation_findings(self) -> list[Finding]:
        """Whole-graph findings for files edited outside the tool (spec §14).

        ``E-LINK-TARGET-MISSING``, ``E-EDGE-RULE``, ``E-EDGE-EXCLUSIVE`` and
        ``E-CYCLE`` (Kahn, §6.2). ``W-ORPHAN`` and ``W-CONFLICT-OPEN`` are left
        to the validate layer via :meth:`orphans` and :meth:`edges`.
        """
        findings: list[Finding] = []
        pair_map: dict[tuple[str, str], list[Edge]] = {}
        for edge in self._edges:
            pair_map.setdefault((edge.source, edge.target), []).append(edge)
            if edge.target not in self._nodes:
                findings.append(
                    Finding(
                        code="E-LINK-TARGET-MISSING",
                        severity="E",
                        subject=edge.source,
                        message=(
                            f"edge {edge.type} → {edge.target}: target does not exist"
                        ),
                        fix=f"gregraph unlink {edge.source} {edge.type} {edge.target}",
                    )
                )
                continue
            source_kind = self._nodes[edge.source].kind
            target_kind = self._nodes[edge.target].kind
            if source_kind is not None and target_kind is not None:
                if not edge_kind_allowed(edge.type, source_kind, target_kind):
                    findings.append(
                        Finding(
                            code="E-EDGE-RULE",
                            severity="E",
                            subject=edge.source,
                            message=(
                                f"{edge.source} ({source_kind}) cannot {edge.type} "
                                f"{edge.target} ({target_kind})"
                            ),
                            fix=(
                                f"gregraph unlink {edge.source} "
                                f"{edge.type} {edge.target}"
                            ),
                        )
                    )
        findings.extend(self._exclusion_findings(pair_map))
        for cycle in self.find_cycles():
            rendered = " → ".join(cycle)
            findings.append(
                Finding(
                    code="E-CYCLE",
                    severity="E",
                    subject=cycle[0],
                    message=f"directed cycle: {rendered}",
                )
            )
        findings.sort(key=lambda item: (item.code, str(item.subject), item.message))
        return findings

    def _exclusion_conflict(
        self, source: str, edge_type: LinkType, target: str
    ) -> tuple[LinkType, bool] | None:
        """Existing conflicting edge as ``(its type, opposite direction)``, or None."""
        for other_type, ends in self._outbound.get(source, {}).items():
            if target in ends and is_mutually_exclusive(
                edge_type, other_type, opposite_direction=False
            ):
                return other_type, False
        if source != target:
            for other_type, ends in self._outbound.get(target, {}).items():
                if source in ends and is_mutually_exclusive(
                    edge_type, other_type, opposite_direction=True
                ):
                    return other_type, True
        return None

    def _exclusion_finding(
        self,
        source: str,
        edge_type: LinkType,
        target: str,
        conflict: tuple[LinkType, bool],
        *,
        fix: str | None = None,
    ) -> Finding:
        other, opposite = conflict
        if opposite:
            message = (
                f"{edge_type} from {source} to {target} is mutually exclusive "
                f"with {other} from {target} to {source}"
            )
            unlink = f"gregraph unlink {target} {other} {source}"
        else:
            message = (
                f"{edge_type} is mutually exclusive with {other} "
                f"between {source} and {target}"
            )
            unlink = f"gregraph unlink {source} {other} {target}"
        return Finding(
            code="E-EDGE-EXCLUSIVE",
            severity="E",
            subject=source,
            message=message,
            fix=fix if fix is not None else unlink,
        )

    def _exclusion_findings(
        self, pair_map: dict[tuple[str, str], list[Edge]]
    ) -> list[Finding]:
        findings: list[Finding] = []
        reported: set[frozenset[Edge]] = set()
        for edge in self._edges:
            if edge.type not in DIRECTED_EDGE_TYPES:
                continue
            same = pair_map.get((edge.source, edge.target), [])
            opposite = pair_map.get((edge.target, edge.source), [])
            for other in (*same, *opposite):
                if other == edge:
                    continue
                reversed_direction = (
                    edge.source != edge.target
                    and other.source == edge.target
                    and other.target == edge.source
                )
                if not is_mutually_exclusive(
                    edge.type, other.type, opposite_direction=reversed_direction
                ):
                    continue
                key = frozenset({edge, other})
                if key in reported:
                    continue
                reported.add(key)
                first, second = sorted((edge, other), key=lambda e: (e.source, e.type))
                second_reversed = (
                    first.source != first.target
                    and second.source == first.target
                    and second.target == first.source
                )
                findings.append(
                    self._exclusion_finding(
                        first.source,
                        first.type,
                        first.target,
                        (second.type, second_reversed),
                    )
                )
        return findings

    def _directed_successors(self, node_id: str) -> set[str]:
        successors: set[str] = set()
        for link_type, ends in self._outbound.get(node_id, {}).items():
            if link_type in DIRECTED_EDGE_TYPES:
                successors.update(ends)
        return successors

    def _directed_predecessors(self, node_id: str) -> set[str]:
        predecessors: set[str] = set()
        for link_type, sources in self._inbound.get(node_id, {}).items():
            if link_type in DIRECTED_EDGE_TYPES:
                predecessors.update(sources)
        return predecessors

    def _directed_path(self, start: str, goal: str) -> tuple[str, ...] | None:
        """Shortest directed path ``start → … → goal`` (inclusive), or ``None``."""
        if start == goal:
            return (start,)
        parents: dict[str, str] = {}
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nxt in sorted(self._directed_successors(current)):
                if nxt == goal:
                    chain = [goal, current]
                    cursor = current
                    while cursor != start:
                        cursor = parents[cursor]
                        chain.append(cursor)
                    chain.reverse()
                    return tuple(chain)
                if nxt not in seen:
                    seen.add(nxt)
                    parents[nxt] = current
                    queue.append(nxt)
        return None

    def _cycle_if_added(self, source: str, target: str) -> tuple[str, ...] | None:
        """Closed path ``source → target → … → source`` the new edge would close."""
        if source == target:
            return (source, source)
        path = self._directed_path(target, source)
        if path is None:
            return None
        return (source,) + path

    def _cycle_through(self, start: str, allowed: set[str]) -> tuple[str, ...] | None:
        """One closed directed path through ``start``, confined to ``allowed``."""
        parents: dict[str, str] = {}
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nxt in sorted(self._directed_successors(current)):
                if nxt not in allowed:
                    continue
                if nxt == start:
                    chain = [current]
                    cursor = current
                    while cursor != start:
                        cursor = parents[cursor]
                        chain.append(cursor)
                    chain.reverse()
                    return tuple(chain) + (start,)
                if nxt not in seen:
                    seen.add(nxt)
                    parents[nxt] = current
                    queue.append(nxt)
        return None

    def _kahn_residual(self) -> set[str]:
        """Nodes Kahn's algorithm cannot peel off — the only cycle candidates."""
        successors: dict[str, set[str]] = {node_id: set() for node_id in self._nodes}
        indegree: dict[str, int] = {node_id: 0 for node_id in self._nodes}
        for edge in self._edges:
            if edge.type not in DIRECTED_EDGE_TYPES:
                continue
            if edge.source not in self._nodes or edge.target not in self._nodes:
                continue
            if edge.target in successors[edge.source]:
                continue
            successors[edge.source].add(edge.target)
            indegree[edge.target] += 1
        queue = deque(sorted(n for n, d in indegree.items() if d == 0))
        done: set[str] = set()
        while queue:
            current = queue.popleft()
            done.add(current)
            for nxt in sorted(successors[current]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        return set(self._nodes) - done


def build_graph(documents: Iterable[Document], kinds: Mapping[str, Kind]) -> Graph:
    """Build the graph from document sidecars (spec §6.1, §16.1).

    ``kinds`` maps configured type names to kinds; a document whose type is not
    present gets ``kind=None`` and skips kind-rule checks (``E-TYPE-UNKNOWN`` is
    the validate layer's report).
    """
    nodes: list[Node] = []
    edges: list[Edge] = []
    for document in documents:
        nodes.append(
            Node(
                id=document.id,
                kind=kinds.get(document.type),
                title=document.title,
                deprecated=document.deprecated is not None,
            )
        )
        for link in document.links:
            edges.append(Edge(source=document.id, type=link.type, target=link.target))
    return Graph(nodes, edges)
