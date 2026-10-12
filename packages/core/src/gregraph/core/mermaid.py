"""Mermaid export (spec §15, §16.1, §13.13).

Pure string generation from the :class:`~gregraph.core.graph.Graph` model — no
I/O, no printing; the caller writes the returned fenced block (spec §16.2).
:func:`export_mermaid` renders a ``flowchart TD``/``LR`` diagram:

- node id: the document ID with ``-`` removed (Mermaid dislikes hyphens);
  label ``RE-XXXXXX<br/>title`` with the title truncated to 40 chars and
  Mermaid-escaped (``#`` → ``#35;`` then ``"`` → ``#quot;``);
- node shape by kind: goal stadium ``(["…"])``, requirement rectangle
  ``["…"]``, design subroutine ``[["…"]]``, verification hexagon ``{{"…"}}``,
  information flag ``>"…"]`` (an unknown kind falls back to rectangle);
- edge style by type: ``refines`` ``-->``, ``derives-from`` ``-.->``,
  ``depends-on`` ``==>``, ``satisfies``/``verifies``/``constrains`` solid with
  a typed label, ``supersedes`` dotted with a label, ``conflicts-with``/
  ``relates-to`` undirected ``---`` with a label; conflict edges are drawn in
  red via ``linkStyle``;
- deprecated/superseded nodes that are included get a dashed ``classDef``.

Scope (spec §13.13 default scope): all non-superseded, non-deprecated nodes
and all directed edges plus ``conflicts-with``. ``include_superseded`` widens
the node scope to deprecated and superseded nodes (the only widening flag of
§13.13; see docs/backlog.md); ``edge_types`` overrides the default edge scope
(``--edges``). ``--types`` filtering is the caller's job: the ``Graph`` carries
kinds, not type names, so the caller subsets the graph before exporting.
``roots``/``depth`` limit to the downstream subgraph of the given roots
(nodes that reach a root via directed edges, depth-limited); ``depth`` without
``roots`` is ignored. Diagrams above 300 nodes get a warning finding.

Judgement calls (docs/decisions.md ``D-S16-MERMAID``): red is
``stroke:#ff0000``; the dashed class is named ``stale`` (``stroke-dasharray:
5 5``); truncation is plain ``title[:40]`` without an ellipsis marker; the
>300-node warning is a ``Finding`` with the invented code ``W-GRAPH-LARGE``.
"""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from gregraph.core.graph import Edge, Graph, Node
from gregraph.core.models import Finding, LinkType
from gregraph.core.rules import DIRECTED_EDGE_TYPES, Kind

Direction = Literal["TD", "LR"]

#: §13.13 default edge scope: all directed edges plus ``conflicts-with``.
DEFAULT_EDGE_TYPES: Final[frozenset[LinkType]] = DIRECTED_EDGE_TYPES | frozenset(
    {"conflicts-with"}
)

#: §15: titles are truncated to this many characters in the label.
TITLE_LIMIT: Final = 40

#: §15: warn above this many nodes ("Mermaid has practical limits").
NODE_WARN_THRESHOLD: Final = 300

#: §15: classDef name for deprecated/superseded nodes (dashed border).
STALE_CLASS: Final = "stale"

_SHAPES: Final[dict[Kind | None, tuple[str, str]]] = {
    "goal": ('(["', '"])'),
    "requirement": ('["', '"]'),
    "design": ('[["', '"]]'),
    "verification": ('{{"', '"}}'),
    "information": ('>"', '"]'),
    None: ('["', '"]'),
}

_EDGE_TEMPLATES: Final[dict[LinkType, str]] = {
    "refines": "{s} --> {t}",
    "derives-from": "{s} -.-> {t}",
    "depends-on": "{s} ==> {t}",
    "satisfies": "{s} -- satisfies --> {t}",
    "verifies": "{s} -- verifies --> {t}",
    "constrains": "{s} -- constrains --> {t}",
    "supersedes": "{s} -. supersedes .-> {t}",
    "conflicts-with": "{s} -- conflicts-with --- {t}",
    "relates-to": "{s} -- relates-to --- {t}",
}


@dataclass(frozen=True, slots=True)
class MermaidExport:
    """Rendered diagram plus findings (spec §16.2: core returns data).

    ``diagram`` is the complete fenced `` ```mermaid `` block, trailing
    newline included; ``findings`` carries the §15 >300-node warning.
    """

    diagram: str
    findings: tuple[Finding, ...] = ()


def mermaid_id(doc_id: str) -> str:
    """Mermaid node id: the document ID with ``-`` removed (spec §15)."""
    return doc_id.replace("-", "")


def escape_label(text: str) -> str:
    """Mermaid-escape a label fragment (spec §15).

    ``#`` must be escaped first so the ``#…;`` entity codes introduced for
    quotes cannot be re-interpreted in a second pass.
    """
    return text.replace("#", "#35;").replace('"', "#quot;")


def node_label(doc_id: str, title: str) -> str:
    """``RE-XXXXXX<br/>title`` with the title truncated to 40 chars (spec §15)."""
    return f"{doc_id}<br/>{escape_label(title[:TITLE_LIMIT])}"


def render_node(node: Node) -> str:
    """One node statement, shape by kind (spec §15)."""
    open_bracket, close_bracket = _SHAPES[node.kind]
    label = node_label(node.id, node.title)
    return f"{mermaid_id(node.id)}{open_bracket}{label}{close_bracket}"


def render_edge(edge: Edge) -> str:
    """One edge statement, style by type (spec §15)."""
    template = _EDGE_TEMPLATES[edge.type]
    return template.format(s=mermaid_id(edge.source), t=mermaid_id(edge.target))


def export_mermaid(
    graph: Graph,
    *,
    direction: Direction = "TD",
    roots: Sequence[str] = (),
    depth: int | None = None,
    include_superseded: bool = False,
    edge_types: Set[LinkType] | None = None,
) -> MermaidExport:
    """Render ``graph`` as a fenced Mermaid flowchart (spec §15, §13.13).

    Raises ``ValueError`` for an unknown root (the CLI resolves user IDs
    first) or an unknown ``direction``.
    """
    if direction not in ("TD", "LR"):
        raise ValueError(f"direction must be 'TD' or 'LR', got {direction!r}")
    if depth is not None and not roots:
        depth = None
    scope = _root_scope(graph, roots, depth) if roots else set(graph.nodes)
    selected = {
        node_id
        for node_id in scope
        if include_superseded
        or not (graph.is_deprecated(node_id) or graph.is_superseded(node_id))
    }
    allowed = DEFAULT_EDGE_TYPES if edge_types is None else frozenset(edge_types)
    edges = [
        edge
        for edge in graph.edges
        if edge.type in allowed and edge.source in selected and edge.target in selected
    ]
    lines: list[str] = [f"flowchart {direction}"]
    for node_id in sorted(selected):
        lines.append(render_node(graph.nodes[node_id]))
    conflict_indices: list[int] = []
    for index, edge in enumerate(edges):
        if edge.type == "conflicts-with":
            conflict_indices.append(index)
        lines.append(render_edge(edge))
    if conflict_indices:
        joined = ",".join(str(index) for index in conflict_indices)
        lines.append(f"linkStyle {joined} stroke:#ff0000")
    stale = [
        node_id
        for node_id in sorted(selected)
        if graph.is_deprecated(node_id) or graph.is_superseded(node_id)
    ]
    if stale:
        lines.append(f"classDef {STALE_CLASS} stroke-dasharray: 5 5")
        class_ids = ",".join(mermaid_id(node_id) for node_id in stale)
        lines.append(f"class {class_ids} {STALE_CLASS}")
    diagram = "```mermaid\n" + "\n".join(lines) + "\n```\n"
    return MermaidExport(diagram=diagram, findings=_size_findings(len(selected)))


def _root_scope(graph: Graph, roots: Sequence[str], depth: int | None) -> set[str]:
    """The roots plus every node reaching one via directed edges (spec §15)."""
    wanted: set[str] = set()
    for root in roots:
        if root not in graph:
            raise ValueError(f"unknown root node: {root!r}")
        wanted.add(root)
        wanted.update(graph.downstream(root, depth))
    return wanted


def _size_findings(node_count: int) -> tuple[Finding, ...]:
    """The §15 >300-node warning. Code/subject are a documented gap
    (docs/backlog.md: no §14 code exists for this command-level warning)."""
    if node_count <= NODE_WARN_THRESHOLD:
        return ()
    return (
        Finding(
            code="W-GRAPH-LARGE",
            severity="W",
            subject=Path("graph"),
            message=(
                f"mermaid diagram has {node_count} nodes "
                f"(above {NODE_WARN_THRESHOLD}); rendering degrades — "
                "narrow the view with --root/--types"
            ),
            fix="gregraph graph --root <ID>",
        ),
    )
