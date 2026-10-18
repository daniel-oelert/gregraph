"""Tests for ``gregraph graph`` (spec §13.13, §15).

Golden Mermaid output for the default scope (non-superseded/non-deprecated
nodes, directed edges plus ``conflicts-with``), ``--root/--depth`` scoping,
``--types/--edges`` filters, ``--include-superseded``, ``--direction``,
``-o FILE`` and ``--json``. CLI tests invoke ``gregraph.cli.main.main([...])``
with the ``sample_graph`` fixture.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gregraph.cli.main import main

if TYPE_CHECKING:
    from conftest import SampleGraph


GOLDEN_DEFAULT = """\
```mermaid
flowchart TD
REASM00000D>"RE-ASM-00000D<br/>Users have modern browsers"]
REDSGN00000A[["RE-DSGN-00000A<br/>Ingestion pipeline"]]
REEPIC000003(["RE-EPIC-000003<br/>Knowledge base"])
REFEAT000004["RE-FEAT-000004<br/>Upload documents"]
REFUNC000008["RE-FUNC-000008<br/>Pipeline rejects infected files"]
REGOAL000001(["RE-GOAL-000001<br/>Increase self-service"])
REGOAL000002(["RE-GOAL-000002<br/>Meet GDPR"])
RENFR000009["RE-NFR-000009<br/>P95 upload latency under 3 s"]
RESTKH00000C>"RE-STKH-00000C<br/>Anna the compliance officer"]
RESTORY000005["RE-STORY-000005<br/>Upload from the desktop"]
RESTORY000007["RE-STORY-000007<br/>Scan uploads for malware"]
RETEST00000B{{"RE-TEST-00000B<br/>Upload happy path"}}
REDSGN00000A -- satisfies --> REFEAT000004
REEPIC000003 --> REGOAL000001
REFEAT000004 --> REEPIC000003
REFUNC000008 ==> RESTORY000005
REFUNC000008 --> RESTORY000007
REGOAL000002 -- conflicts-with --- REDSGN00000A
RENFR000009 -- constrains --> REFEAT000004
RESTORY000005 --> REFEAT000004
RESTORY000007 -.-> REFEAT000004
RETEST00000B -- verifies --> REDSGN00000A
RETEST00000B -- verifies --> RESTORY000005
linkStyle 5 stroke:#ff0000
```
"""

GOLDEN_ROOT_DEPTH_ONE = """\
```mermaid
flowchart TD
REEPIC000003(["RE-EPIC-000003<br/>Knowledge base"])
REGOAL000001(["RE-GOAL-000001<br/>Increase self-service"])
REEPIC000003 --> REGOAL000001
```
"""


def graph_text(root: Path, *extra: str) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "graph", *extra]) == 0
    return buffer.getvalue()


def graph_json(root: Path, *extra: str) -> dict[str, object]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "graph", "--json", *extra]) == 0
    return json.loads(buffer.getvalue())


def test_graph_default_golden(sample_graph: SampleGraph) -> None:
    assert graph_text(sample_graph.root) == GOLDEN_DEFAULT


def test_graph_root_depth_golden(sample_graph: SampleGraph) -> None:
    goal = sample_graph.ids["goal"]
    assert (
        graph_text(sample_graph.root, "--root", goal, "--depth", "1")
        == GOLDEN_ROOT_DEPTH_ONE
    )


def test_graph_include_superseded_draws_stale_class(sample_graph: SampleGraph) -> None:
    text = graph_text(sample_graph.root, "--include-superseded")
    assert "classDef stale stroke-dasharray: 5 5" in text
    assert sample_graph.ids["story_old"].replace("-", "") in text
    assert sample_graph.ids["stale_note"].replace("-", "") in text


def test_graph_types_filter(sample_graph: SampleGraph) -> None:
    text = graph_text(sample_graph.root, "--types", "goal")
    assert "REGOAL000001" in text
    assert "REGOAL000002" in text
    assert "REFEAT000004" not in text  # feature (type feature) filtered out


def test_graph_edges_filter(sample_graph: SampleGraph) -> None:
    text = graph_text(sample_graph.root, "--edges", "depends-on")
    assert "REFUNC000008 ==> RESTORY000005" in text
    assert "-->" not in text
    assert "conflicts-with" not in text


def test_graph_direction_lr(sample_graph: SampleGraph) -> None:
    text = graph_text(sample_graph.root, "--direction", "LR")
    assert text.splitlines()[1] == "flowchart LR"


def test_graph_output_file(
    sample_graph: SampleGraph, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "graph.md"
    assert main(["--repo", str(sample_graph.root), "graph", "-o", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == GOLDEN_DEFAULT
    assert "wrote" in capsys.readouterr().out


def test_graph_json_payload(sample_graph: SampleGraph) -> None:
    payload = graph_json(sample_graph.root)
    assert payload["diagram"] == GOLDEN_DEFAULT
    assert payload["findings"] == []


def test_graph_unknown_root_refused_exits_4(
    sample_graph: SampleGraph, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(["--repo", str(sample_graph.root), "graph", "--root", "RE-STORY-ZZZZZZ"])
        == 4
    )
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_graph_unknown_type_is_usage_error(sample_graph: SampleGraph) -> None:
    assert main(["--repo", str(sample_graph.root), "graph", "--types", "bogus"]) == 2
    assert main(["--repo", str(sample_graph.root), "graph", "--edges", "bogus"]) == 2
    assert main(["--repo", str(sample_graph.root), "graph", "--depth", "-1"]) == 2
