"""Tests for ``gregraph template`` (spec §13.17, §7.7): template management.

``list``/``add``/``bump``/``show`` via the CLI, refusal of unknown templates,
and the subcommand requirement. CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

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


def test_template_list_shows_names_and_versions(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "list"]) == 0
    captured = capsys.readouterr().out
    assert "user-story" in captured
    assert "v1" in captured
    assert "change-request" in captured


def test_template_add_copies_builtin_as_next_version(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "add", "user-story"]) == 0
    assert "added user-story v2" in capsys.readouterr().out
    descriptor = json.loads(
        (
            repo / ".gregraph" / "templates" / "user-story" / "v2" / "template.json"
        ).read_text(encoding="utf-8")
    )
    assert descriptor["version"] == 2


def test_template_add_unknown_builtin_refused(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "add", "no-such"]) == 4
    assert "E-TEMPLATE-UNKNOWN" in capsys.readouterr().err


def test_template_bump_marks_breaking(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "template", "bump", "user-story", "--breaking"]) == 0
    )
    captured = capsys.readouterr().out
    assert "bumped user-story to v2" in captured
    assert "edit the new version's files" in captured
    descriptor = json.loads(
        (
            repo / ".gregraph" / "templates" / "user-story" / "v2" / "template.json"
        ).read_text(encoding="utf-8")
    )
    assert descriptor["breaking"] is True


def test_template_show_prints_descriptor_and_skeleton(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "show", "user-story"]) == 0
    captured = capsys.readouterr().out
    assert "user-story v1" in captured
    assert "description" in captured
    assert "# {{ title }}" in captured
    assert "## Story" in captured


def test_template_show_unknown_version_refused(repo: Path, capsys) -> None:
    assert (
        main(["--repo", str(repo), "template", "show", "user-story", "--version", "9"])
        == 4
    )
    assert "E-TEMPLATE-UNKNOWN" in capsys.readouterr().err


def test_template_unknown_name_refused(repo: Path, capsys) -> None:
    assert main(["--repo", str(repo), "template", "show", "no-such"]) == 4
    assert "E-TEMPLATE-UNKNOWN" in capsys.readouterr().err


def test_template_without_subcommand_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "template"]) == 2


# --------------------------------------------------------------------------
# --json payloads (AGENT_READINESS §2.4.4, §4.2, AGENT-022)
# --------------------------------------------------------------------------


def template_json(repo: Path, *extra: str) -> dict[str, object]:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main(["--repo", str(repo), "template", *extra]) == 0
    return json.loads(buffer.getvalue())


def test_template_list_json_payload(repo: Path) -> None:
    payload = template_json(repo, "list", "--json")
    templates = payload["templates"]
    assert isinstance(templates, list)
    story = next(t for t in templates if t["name"] == "user-story")
    assert story["latest_version"] == 1
    assert story["versions"] == [
        {"version": 1, "deprecated": False, "breaking": False, "documents": 0}
    ]
    assert isinstance(story["description"], str)


def test_template_list_json_counts_documents(repo: Path) -> None:
    import datetime as dt
    from uuid import UUID

    from gregraph.core.hashing import body_hash
    from gregraph.core.ids import derive_id
    from gregraph.core.models import Document, TemplateRef
    from gregraph.core.storage import document_paths, write_body, write_sidecar

    config = Config()
    spec = config.types["user-story"]
    generated = UUID(int=7 << 98)
    doc_id = derive_id(generated, config.ids.prefix, spec.abbreviation)
    body = "# T\n\n## Story\n\nx\n"
    document = Document(
        schema=1,
        uuid=generated,
        id=doc_id,
        type="user-story",
        title="T",
        created=dt.datetime(2026, 9, 10, tzinfo=dt.UTC),
        created_by=None,
        template=TemplateRef(name="user-story", version=1),
        version=1,
        body_hash=body_hash(body),
        assets=[],
        links=[],
        deprecated=None,
        tags=[],
        extra={},
    )
    body_abs, sidecar_abs = document_paths(repo, spec.folder, doc_id)
    write_body(body_abs, body)
    write_sidecar(sidecar_abs, document)
    payload = template_json(repo, "list", "--json")
    templates = payload["templates"]
    assert isinstance(templates, list)
    story = next(t for t in templates if t["name"] == "user-story")
    versions = story["versions"]
    assert isinstance(versions, list)
    assert versions[0]["documents"] == 1


def test_template_add_json_payload(repo: Path) -> None:
    payload = template_json(repo, "add", "user-story", "--json")
    assert payload["name"] == "user-story"
    assert payload["version"] == 2
    assert payload["path"] == ".gregraph/templates/user-story/v2"
    assert payload["findings"] == []
    assert payload["notices"] == []


def test_template_bump_json_payload(repo: Path) -> None:
    payload = template_json(repo, "bump", "user-story", "--breaking", "--json")
    assert payload["name"] == "user-story"
    assert payload["version"] == 2
    assert payload["breaking"] is True
    assert payload["path"] == ".gregraph/templates/user-story/v2"
    assert payload["findings"] == []
    assert payload["notices"] == []


def test_template_show_json_payload(repo: Path) -> None:
    payload = template_json(repo, "show", "user-story", "--json")
    assert payload["name"] == "user-story"
    assert payload["version"] == 1
    assert isinstance(payload["description"], str)
    assert payload["deprecated"] is False
    assert payload["breaking"] is False
    sections = payload["sections"]
    assert isinstance(sections, list)
    headings = [s["heading"] for s in sections]
    assert "Story" in headings
    assert any(s["required"] for s in sections)
    assert "# {{ title }}" in str(payload["skeleton"])
    assert payload["path"] == ".gregraph/templates/user-story/v1/template.md"
    assert payload["findings"] == []
    assert payload["notices"] == []


def test_template_show_json_unknown_version_envelope(repo: Path) -> None:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        argv = [
            "--repo",
            str(repo),
            "template",
            "show",
            "user-story",
            "--version",
            "9",
            "--json",
        ]
        assert main(argv) == 4
    envelope = json.loads(buffer.getvalue())
    assert envelope["error"]["code"] == "E-TEMPLATE-UNKNOWN"
    assert envelope["error"]["exit_code"] == 4
