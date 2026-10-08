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

GOLDEN_ROOT_DEPTH_ONE = """\
```mermaid
flowchart TD
RE000001(["RE-000001<br/>Increase self-service"])
RE000003(["RE-000003<br/>Knowledge base"])
RE000003 --> RE000001
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
    assert "RE000001" in text
    assert "RE000002" in text
    assert "RE000004" not in text  # feature (type feature) filtered out


def test_graph_edges_filter(sample_graph: SampleGraph) -> None:
    text = graph_text(sample_graph.root, "--edges", "depends-on")
    assert "RE000008 ==> RE000005" in text
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
    assert main(["--repo", str(sample_graph.root), "graph", "--root", "RE-NOSUCH"]) == 4
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_graph_unknown_type_is_usage_error(sample_graph: SampleGraph) -> None:
    assert main(["--repo", str(sample_graph.root), "graph", "--types", "bogus"]) == 2
    assert main(["--repo", str(sample_graph.root), "graph", "--edges", "bogus"]) == 2
    assert main(["--repo", str(sample_graph.root), "graph", "--depth", "-1"]) == 2
