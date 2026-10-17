"""Tests for ``gregraph schema`` (AGENT_READINESS §4.1, AGENT-021).

The one-call rulebook: ``--json`` payload shape (config, types, kinds, edge
rules with descriptions, active templates with sections, CR lifecycle),
``--type`` filtering, the ``E-TYPE-UNKNOWN`` refusal (exit 4) and the human
mode's aligned sections. CLI tests invoke ``gregraph.cli.main.main([...])``
with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest
from test_hook import install_templates

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.storage import config_path


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def schema_json(root: Path, *extra: str) -> dict[str, object]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(root), "schema", "--json", *extra]) == 0
    return json.loads(buffer.getvalue())


def test_schema_json_payload_shape(repo: Path) -> None:
    payload = schema_json(repo)
    assert set(payload) == {
        "schema",
        "tool_version",
        "id_prefix",
        "baseline_branch",
        "versioning",
        "graph",
        "assets",
        "cr",
        "types",
        "kinds",
        "edge_rules",
        "templates",
        "cr_lifecycle",
    }
    assert payload["schema"] == 1
    assert payload["id_prefix"] == "RE"
    assert payload["baseline_branch"] == "main"
    assert payload["versioning"] == {
        "on_outdated_links": "block",
        "on_cr_modified": "warn",
    }
    assert payload["graph"] == {"open_conflicts": "warn"}
    assert payload["assets"] == {"max_size_kb": 5120}
    assert payload["kinds"] == [
        "goal",
        "requirement",
        "design",
        "verification",
        "information",
    ]


def test_schema_json_types_carry_template_and_prefix(repo: Path) -> None:
    payload = schema_json(repo)
    types = payload["types"]
    assert isinstance(types, dict)
    story = types["user-story"]
    assert story["kind"] == "requirement"
    assert story["folder"] == "user-story"
    assert story["template"] == "user-story"
    assert story["id_prefix"] == "RE"
    assert isinstance(story["description"], str)


def test_schema_json_edge_rules_have_descriptions(repo: Path) -> None:
    payload = schema_json(repo)
    rules = payload["edge_rules"]
    assert isinstance(rules, list)
    assert len(rules) == 9
    refines = next(r for r in rules if r["type"] == "refines")
    assert refines["direction"] == "directed"
    assert refines["hierarchical"] is True
    assert refines["acyclic"] is True
    assert refines["source_kinds"] == ["goal", "requirement"]
    assert refines["target_kinds"] == ["goal", "requirement"]
    assert refines["same_kind_only"] is False
    assert "derives-from" in refines["mutually_exclusive_with"]
    assert "depends-on" in refines["mutually_exclusive_opposite"]
    assert "decomposition" in refines["description"]


def test_schema_json_templates_list_sections(repo: Path) -> None:
    payload = schema_json(repo)
    templates = payload["templates"]
    assert isinstance(templates, dict)
    story = templates["user-story"]
    assert story["latest_version"] == 1
    assert story["versions"] == [1]
    assert story["deprecated"] is False
    headings = [section["heading"] for section in story["sections"]]
    assert "Story" in headings
    assert any(section["required"] for section in story["sections"])


def test_schema_json_cr_lifecycle(repo: Path) -> None:
    payload = schema_json(repo)
    lifecycle = payload["cr_lifecycle"]
    assert lifecycle["statuses"] == ["open", "accepted", "rejected", "implemented"]
    assert lifecycle["transitions"]["open"] == ["accepted", "rejected"]
    assert lifecycle["scope_intents"] == ["modify", "supersede", "deprecate"]


def test_schema_type_filter_narrows_types_and_templates(repo: Path) -> None:
    payload = schema_json(repo, "--type", "user-story")
    assert list(payload["types"]) == ["user-story"]
    templates = payload["templates"]
    assert isinstance(templates, dict)
    assert "user-story" in templates
    # global sections stay
    assert len(payload["edge_rules"]) == 9
    assert len(payload["kinds"]) == 5
    assert "statuses" in payload["cr_lifecycle"]


def test_schema_unknown_type_refused_exits_4(repo: Path, capsys) -> None:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        assert main(["--repo", str(repo), "schema", "--type", "no-such", "--json"]) == 4
    envelope = json.loads(buffer.getvalue())
    assert envelope["error"]["code"] == "E-TYPE-UNKNOWN"
    assert envelope["error"]["exit_code"] == 4
    assert capsys.readouterr().err == ""


def test_schema_human_mode_prints_sections(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "schema"]) == 0
    out = capsys.readouterr().out
    assert "user-story" in out
    assert "requirement" in out
    assert "refines" in out
    assert "decomposition" in out
    assert "Story" in out
    assert "accepted" in out  # CR lifecycle
    assert "open_conflicts" in out


def test_schema_human_type_filter(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "schema", "--type", "user-story"]) == 0
    out = capsys.readouterr().out
    assert "user-story" in out
    assert "epic" not in out


def test_schema_is_stable_across_calls(repo: Path) -> None:
    first = schema_json(repo)
    second = schema_json(repo)
    assert first == second


def test_schema_json_takes_precedence_over_quiet(repo: Path) -> None:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(repo), "schema", "--json", "-q"]) == 0
    assert json.loads(buffer.getvalue())["schema"] == 1
