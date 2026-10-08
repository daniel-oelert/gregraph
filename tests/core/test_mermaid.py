"""Tests for ``gregraph.core.mermaid`` (spec §15, §16.1).

Test-first (appendix C): golden outputs frozen on the deterministic IDs of the
``sample_graph`` fixture (default scope, ``--include-superseded``, ``--root``
subgraph, ``--depth`` limit), quote escaping, the >300-node warning, direction,
and the per-kind node shapes / per-type edge styles of §15.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from gregraph.core.graph import Edge, Graph, Node
from gregraph.core.mermaid import (
    escape_label,
    export_mermaid,
    mermaid_id,
    node_label,
    render_edge,
    render_node,
)
from gregraph.core.models import LinkType
from gregraph.core.rules import EDGE_RULES, Kind

if TYPE_CHECKING:
    from conftest import SampleGraph


def test_mermaid_id_strips_hyphens() -> None:
    assert mermaid_id("RE-7F3K2Q") == "RE7F3K2Q"


def test_escape_label_escapes_quotes_and_hashes() -> None:
    assert escape_label('Say "hi" #1') == "Say #quot;hi#quot; #35;1"
    assert escape_label("plain") == "plain"


def test_node_label_truncates_title_to_40_chars() -> None:
    assert node_label("RE-111111", "X" * 50) == "RE-111111<br/>" + "X" * 40
    assert node_label("RE-111111", "short") == "RE-111111<br/>short"


def test_node_label_escapes_quotes_in_title() -> None:
    assert (
        node_label("RE-111111", 'Say "hello" #1')
        == "RE-111111<br/>Say #quot;hello#quot; #35;1"
    )


GOLDEN_ESCAPING = """\
```mermaid
flowchart TD
RE111111["RE-111111<br/>Say #quot;hello#quot; #35;1"]
RE222222(["RE-222222<br/>A #quot;quoted#quot; goal"])
RE111111 ==> RE222222
```
"""


def test_escaping_golden() -> None:
    """Escaping fixture: quotes and ``#`` in titles survive as Mermaid entity
    codes; structural ``<br/>`` and shapes are untouched (spec §15)."""
    graph = Graph(
        [
            Node(
                id="RE-111111",
                kind="requirement",
                title='Say "hello" #1',
                deprecated=False,
            ),
            Node(
                id="RE-222222",
                kind="goal",
                title='A "quoted" goal',
                deprecated=False,
            ),
        ],
        [Edge(source="RE-111111", type="depends-on", target="RE-222222")],
    )
    export = export_mermaid(graph)
    assert export.diagram == GOLDEN_ESCAPING
    assert export.findings == ()


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("goal", 'RE111111(["RE-111111<br/>Title"])'),
        ("requirement", 'RE111111["RE-111111<br/>Title"]'),
        ("design", 'RE111111[["RE-111111<br/>Title"]]'),
        ("verification", 'RE111111{{"RE-111111<br/>Title"}}'),
        ("information", 'RE111111>"RE-111111<br/>Title"]'),
    ],
)
def test_node_shapes_by_kind(kind: Kind, expected: str) -> None:
    node = Node(id="RE-111111", kind=kind, title="Title", deprecated=False)
    assert render_node(node) == expected


def test_unknown_kind_falls_back_to_rectangle() -> None:
    node = Node(id="RE-111111", kind=None, title="Title", deprecated=False)
    assert render_node(node) == 'RE111111["RE-111111<br/>Title"]'


@pytest.mark.parametrize(
    ("edge_type", "expected"),
    [
        ("refines", "RE111111 --> RE222222"),
        ("derives-from", "RE111111 -.-> RE222222"),
        ("depends-on", "RE111111 ==> RE222222"),
        ("satisfies", "RE111111 -- satisfies --> RE222222"),
        ("verifies", "RE111111 -- verifies --> RE222222"),
        ("constrains", "RE111111 -- constrains --> RE222222"),
        ("supersedes", "RE111111 -. supersedes .-> RE222222"),
        ("conflicts-with", "RE111111 -- conflicts-with --- RE222222"),
        ("relates-to", "RE111111 -- relates-to --- RE222222"),
    ],
)
def test_edge_styles_by_type(edge_type: LinkType, expected: str) -> None:
    edge = Edge(source="RE-111111", type=edge_type, target="RE-222222")
    assert render_edge(edge) == expected


def test_empty_graph_is_header_only() -> None:
    export = export_mermaid(Graph([]))
    assert export.diagram == "```mermaid\nflowchart TD\n```\n"
    assert export.findings == ()


GOLDEN_DEFAULT = """\
```mermaid
flowchart TD
RE000001(["RE-000001<br/>Increase self-service"])
RE000002(["RE-000002<br/>Meet GDPR"])
RE000003(["RE-000003<br/>Knowledge base"])
RE000004["RE-000004<br/>Upload documents"]
RE000005["RE-000005<br/>Upload from the desktop"]
RE000007["RE-000007<br/>Scan uploads for malware"]
RE000008["RE-000008<br/>Pipeline rejects infected files"]
RE000009["RE-000009<br/>P95 upload latency under 3 s"]
RE00000A[["RE-00000A<br/>Ingestion pipeline"]]
RE00000B{{"RE-00000B<br/>Upload happy path"}}
RE00000C>"RE-00000C<br/>Anna the compliance officer"]
RE00000D>"RE-00000D<br/>Users have modern browsers"]
RE000002 -- conflicts-with --- RE00000A
RE000003 --> RE000001
RE000004 --> RE000003
RE000005 --> RE000004
RE000007 -.-> RE000004
RE000008 ==> RE000005
RE000008 --> RE000007
RE000009 -- constrains --> RE000004
RE00000A -- satisfies --> RE000004
RE00000B -- verifies --> RE000005
RE00000B -- verifies --> RE00000A
linkStyle 0 stroke:#ff0000
```
"""


def test_default_scope_golden(sample_graph: SampleGraph) -> None:
    """§13.13 default scope: non-superseded, non-deprecated nodes; directed
    edges plus ``conflicts-with`` (no ``relates-to``, no stale nodes)."""
    export = export_mermaid(sample_graph.graph)
    assert export.diagram == GOLDEN_DEFAULT
    assert export.findings == ()


GOLDEN_INCLUDE_SUPERSEDED = """\
```mermaid
flowchart TD
RE000001(["RE-000001<br/>Increase self-service"])
RE000002(["RE-000002<br/>Meet GDPR"])
RE000003(["RE-000003<br/>Knowledge base"])
RE000004["RE-000004<br/>Upload documents"]
RE000005["RE-000005<br/>Upload from the desktop"]
RE000006["RE-000006<br/>Upload from the desktop (old)"]
RE000007["RE-000007<br/>Scan uploads for malware"]
RE000008["RE-000008<br/>Pipeline rejects infected files"]
RE000009["RE-000009<br/>P95 upload latency under 3 s"]
RE00000A[["RE-00000A<br/>Ingestion pipeline"]]
RE00000B{{"RE-00000B<br/>Upload happy path"}}
RE00000C>"RE-00000C<br/>Anna the compliance officer"]
RE00000D>"RE-00000D<br/>Users have modern browsers"]
RE00000E>"RE-00000E<br/>English-only is enough"]
RE000002 -- conflicts-with --- RE00000A
RE000003 --> RE000001
RE000004 --> RE000003
RE000005 --> RE000004
RE000005 -. supersedes .-> RE000006
RE000007 -.-> RE000004
RE000008 ==> RE000005
RE000008 --> RE000007
RE000009 -- constrains --> RE000004
RE00000A -- satisfies --> RE000004
RE00000B -- verifies --> RE000005
RE00000B -- verifies --> RE00000A
linkStyle 0 stroke:#ff0000
classDef stale stroke-dasharray: 5 5
class RE000006,RE00000E stale
```
"""


def test_include_superseded_golden(sample_graph: SampleGraph) -> None:
    """§15: deprecated/superseded nodes (when included) get a dashed classDef."""
    export = export_mermaid(sample_graph.graph, include_superseded=True)
    assert export.diagram == GOLDEN_INCLUDE_SUPERSEDED
    assert export.findings == ()


GOLDEN_ROOT_SUBGRAPH = """\
```mermaid
flowchart TD
RE000001(["RE-000001<br/>Increase self-service"])
RE000003(["RE-000003<br/>Knowledge base"])
RE000004["RE-000004<br/>Upload documents"]
RE000005["RE-000005<br/>Upload from the desktop"]
RE000007["RE-000007<br/>Scan uploads for malware"]
RE000008["RE-000008<br/>Pipeline rejects infected files"]
RE000009["RE-000009<br/>P95 upload latency under 3 s"]
RE00000A[["RE-00000A<br/>Ingestion pipeline"]]
RE00000B{{"RE-00000B<br/>Upload happy path"}}
RE000003 --> RE000001
RE000004 --> RE000003
RE000005 --> RE000004
RE000007 -.-> RE000004
RE000008 ==> RE000005
RE000008 --> RE000007
RE000009 -- constrains --> RE000004
RE00000A -- satisfies --> RE000004
RE00000B -- verifies --> RE000005
RE00000B -- verifies --> RE00000A
```
"""


def test_root_subgraph_golden(sample_graph: SampleGraph) -> None:
    """§15: ``--root`` limits to the downstream subgraph (nodes reaching the
    root via directed edges). The symmetric ``conflicts-with`` partner and the
    orphan fall outside it; the conflict's ``linkStyle`` goes with it."""
    export = export_mermaid(sample_graph.graph, roots=(sample_graph.ids["goal"],))
    assert export.diagram == GOLDEN_ROOT_SUBGRAPH
    assert export.findings == ()


GOLDEN_ROOT_DEPTH_ONE = """\
```mermaid
flowchart TD
RE000001(["RE-000001<br/>Increase self-service"])
RE000003(["RE-000003<br/>Knowledge base"])
RE000003 --> RE000001
```
"""


def test_root_depth_limit_golden(sample_graph: SampleGraph) -> None:
    """§15: ``--root ID --depth N`` is depth-limited (depth 1 = direct
    downstream only)."""
    export = export_mermaid(
        sample_graph.graph, roots=(sample_graph.ids["goal"],), depth=1
    )
    assert export.diagram == GOLDEN_ROOT_DEPTH_ONE
    assert export.findings == ()


def test_direction_lr(sample_graph: SampleGraph) -> None:
    export = export_mermaid(sample_graph.graph, direction="LR")
    assert export.diagram.splitlines()[1] == "flowchart LR"


def test_direction_rejects_unknown(sample_graph: SampleGraph) -> None:
    with pytest.raises(ValueError, match="direction"):
        export_mermaid(sample_graph.graph, direction="TB")  # type: ignore[arg-type]


def test_relates_to_is_drawn_undirected_when_in_scope(
    sample_graph: SampleGraph,
) -> None:
    """``relates-to`` is outside the §13.13 default edge scope but must render
    as an undirected labelled ``---`` when requested (§15)."""
    export = export_mermaid(sample_graph.graph, edge_types=frozenset(EDGE_RULES))
    assert "RE00000C -- relates-to --- RE000001" in export.diagram.splitlines()
    assert export.findings == ()


def test_unknown_root_raises(sample_graph: SampleGraph) -> None:
    with pytest.raises(ValueError, match="unknown root"):
        export_mermaid(sample_graph.graph, roots=("RE-999999",))


def test_depth_without_roots_is_ignored(sample_graph: SampleGraph) -> None:
    assert export_mermaid(sample_graph.graph, depth=1) == export_mermaid(
        sample_graph.graph
    )


def test_link_style_marks_every_conflict_edge() -> None:
    graph = Graph(
        [node("RE-111111"), node("RE-222222"), node("RE-333333")],
        [
            Edge(source="RE-111111", type="conflicts-with", target="RE-222222"),
            Edge(source="RE-111111", type="refines", target="RE-222222"),
            Edge(source="RE-222222", type="conflicts-with", target="RE-333333"),
        ],
    )
    export = export_mermaid(graph)
    lines = export.diagram.splitlines()
    assert lines[-2] == "linkStyle 0,2 stroke:#ff0000"


def test_classdef_only_when_stale_nodes_included() -> None:
    stale = Node(id="RE-111111", kind="requirement", title="Old", deprecated=True)
    live = Node(id="RE-222222", kind="requirement", title="New", deprecated=False)
    graph = Graph([stale, live])
    assert "classDef" not in export_mermaid(graph).diagram
    with_stale = export_mermaid(graph, include_superseded=True).diagram
    assert "classDef stale stroke-dasharray: 5 5" in with_stale.splitlines()
    assert "class RE111111 stale" in with_stale.splitlines()


def _big_graph(size: int) -> Graph:
    return Graph(
        [
            Node(id=f"RE-{index:06d}", kind=None, title="T", deprecated=False)
            for index in range(size)
        ]
    )


def test_warns_above_300_nodes() -> None:
    export = export_mermaid(_big_graph(301))
    assert len(export.findings) == 1
    [finding] = export.findings
    assert finding.code == "W-GRAPH-LARGE"
    assert finding.severity == "W"
    assert "301" in finding.message
    assert "--root" in finding.message
    assert "--types" in finding.message
    assert finding.fix is not None


def test_no_warning_at_300_nodes() -> None:
    export = export_mermaid(_big_graph(300))
    assert export.findings == ()


def test_warning_counts_nodes_after_root_limiting() -> None:
    nodes = [
        Node(id=f"RE-{index:06d}", kind=None, title="T", deprecated=False)
        for index in range(301)
    ]
    edges = [Edge(source="RE-000001", type="refines", target="RE-000000")]
    graph = Graph(nodes, edges)
    assert len(export_mermaid(graph).findings) == 1
    export = export_mermaid(graph, roots=("RE-000000",), depth=1)
    assert export.findings == ()


def node(node_id: str, kind: Kind | None = "requirement") -> Node:
    return Node(id=node_id, kind=kind, title="Title", deprecated=False)
