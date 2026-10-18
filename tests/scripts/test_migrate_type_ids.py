"""Tests for ``scripts/migrate_type_ids.py`` (typed IDs, config schema 2).

The script is standalone, so most tests exercise it through a subprocess.
Tests may import ``gregraph`` to compute expected hashes and IDs.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from gregraph.core.hashing import body_hash
from gregraph.core.versioning import scope_hash

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "migrate_type_ids.py"

UUID_A = UUID(int=1 << 98)
UUID_B = UUID(int=2 << 98)
UUID_C = UUID(int=3 << 98)
UUID_D = UUID(int=4 << 98)

OLD_A = "RE-000001"
OLD_B = "RE-000002"
OLD_C = "RE-000003"
OLD_CR = "RE-000004"

NEW_A = "RE-FEAT-000001"
NEW_B = "RE-STORY-000002"
NEW_C = "RE-FEAT-000003"
NEW_CR = "RE-CHG-000004"

BODY_A = f"""\
# Feature {OLD_B}

See [[{OLD_B}]] and [[{OLD_B.lower()}]].

Link: [story]({OLD_B})
Asset: ![diagram](assets/{OLD_A}/diagram.png)
Boundary: {OLD_B}0 and X{OLD_B} must not change.
"""
BODY_B = f"""\
# Story {OLD_A}

Depends on {OLD_A}.
"""
BODY_C = f"""\
# Another feature

Refines {OLD_B}.
"""
BODY_CR = f"""\
# Change {OLD_A}

Touches {OLD_A} and {OLD_B}.
"""
BODY_TERM = f"""\
# Typed IDs

See [[{OLD_A}]] and `{OLD_B}` in prose.
"""

CONFIG_WITHOUT_TYPES = """\
[gregraph]
config_schema = 1
tool_version = "0.1.0"

[ids]
prefix = "RE"

[git]
baseline_branch = "main"

[versioning]
on_outdated_links = "block"  # block | warn
on_cr_modified = "warn"

[graph]
open_conflicts = "warn"

[assets]
max_size_kb = 5120

[cr]
enabled = true
template = "change-request"
deciders = []
"""


def run(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(repo), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_body(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def document_payload(
    *,
    uuid: UUID,
    id_: str,
    type_: str,
    title: str,
    body: str,
    version: int = 1,
    links: Iterable[dict[str, Any]] = (),
    origin_cr: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": 1,
        "uuid": str(uuid),
        "id": id_,
        "type": type_,
        "title": title,
        "created": "2026-09-10T09:00:00Z",
        "created_by": {"name": "Test Author", "email": "test@example.org"},
        "template": {"name": type_, "version": 1},
        "version": version,
        "body_hash": body_hash(body),
        "assets": [],
        "links": list(links),
        "deprecated": None,
        "tags": [],
        "extra": {},
        "origin_cr": origin_cr,
    }


def cr_payload(*, uuid: UUID, id_: str, title: str, body: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "uuid": str(uuid),
        "id": id_,
        "title": title,
        "created": "2026-09-10T09:00:00Z",
        "created_by": {"name": "Test Author", "email": "test@example.org"},
        "template": {"name": "change-request", "version": 1},
        "version": 4,
        "body_hash": body_hash(body),
        "scope_hash": scope_hash([{"id": OLD_A}, {"id": OLD_C}]),
        "scope": [
            {"id": OLD_C, "intent": "supersede", "base_version": 2},
            {"id": OLD_A, "intent": "modify", "base_version": 7},
        ],
        "introduces": [OLD_B],
        "status": "accepted",
        "decisions": [
            {
                "status": "open",
                "at": "2026-09-10T09:00:00Z",
                "by": None,
                "at_version": 1,
            }
        ],
        "branch": OLD_A,
        "external_ref": OLD_B,
        "tags": [],
        "extra": {},
    }


def term_payload(*, slug: str, body: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "term": "Typed IDs",
        "slug": slug,
        "aliases": [],
        "created": "2026-09-10T09:00:00Z",
        "created_by": None,
        "template": {"name": "term", "version": 1},
        "version": 2,
        "body_hash": body_hash(body),
        "deprecated": None,
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small schema-1 repository with documents, a CR, a term and assets."""
    (tmp_path / ".gregraph").mkdir()
    (tmp_path / ".gregraph" / "config.toml").write_text(
        CONFIG_WITHOUT_TYPES, encoding="utf-8"
    )
    cache = tmp_path / ".gregraph" / "cache"
    cache.mkdir()
    (cache / "index.json").write_text('{"schema": 1, "files": {}}\n', encoding="utf-8")

    links_a = [
        {"type": "refines", "target": OLD_B, "target_version": 2},
        {"type": "depends-on", "target": OLD_C, "target_version": 1},
    ]
    write_body(tmp_path / "documents" / "feature" / f"{OLD_A}.md", BODY_A)
    write_json(
        tmp_path / "documents" / "feature" / f"{OLD_A}.json",
        document_payload(
            uuid=UUID_A,
            id_=OLD_A,
            type_="feature",
            title=f"Feature {OLD_B}",
            body=BODY_A,
            version=3,
            links=links_a,
            origin_cr=OLD_CR,
        ),
    )
    write_body(tmp_path / "documents" / "user-story" / f"{OLD_B}.md", BODY_B)
    write_json(
        tmp_path / "documents" / "user-story" / f"{OLD_B}.json",
        document_payload(
            uuid=UUID_B,
            id_=OLD_B,
            type_="user-story",
            title="Story",
            body=BODY_B,
            version=5,
        ),
    )
    write_body(tmp_path / "documents" / "feature" / f"{OLD_C}.md", BODY_C)
    write_json(
        tmp_path / "documents" / "feature" / f"{OLD_C}.json",
        document_payload(
            uuid=UUID_C,
            id_=OLD_C,
            type_="feature",
            title="Another feature",
            body=BODY_C,
            version=2,
        ),
    )

    write_body(tmp_path / "changes" / f"{OLD_CR}.md", BODY_CR)
    write_json(
        tmp_path / "changes" / f"{OLD_CR}.json",
        cr_payload(
            uuid=UUID_D,
            id_=OLD_CR,
            title=f"Change {OLD_A}",
            body=BODY_CR,
        ),
    )

    write_body(tmp_path / "glossary" / "typed-ids.md", BODY_TERM)
    write_json(
        tmp_path / "glossary" / "typed-ids.json",
        term_payload(slug="typed-ids", body=BODY_TERM),
    )

    asset = tmp_path / "assets" / OLD_A / "diagram.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"png")

    return tmp_path


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_dry_run_writes_nothing(repo: Path) -> None:
    before = snapshot(repo)
    result = run(repo, "--dry-run", "--map-out", str(repo / "mapping.json"))
    assert result.returncode == 0, result.stderr
    assert "dry run: nothing written" in result.stdout
    assert "not written during a dry run" in result.stdout
    assert snapshot(repo) == before
    assert not (repo / "mapping.json").exists()
    assert (
        tomllib.loads((repo / ".gregraph" / "config.toml").read_text())["gregraph"][
            "config_schema"
        ]
        == 1
    )


def test_full_migration(repo: Path) -> None:
    result = run(repo, "--apply")
    assert result.returncode == 0, result.stderr
    assert "comments in .gregraph/config.toml are not preserved" in result.stdout

    feature = read_json(repo / "documents" / "feature" / f"{NEW_A}.json")
    story = read_json(repo / "documents" / "user-story" / f"{NEW_B}.json")
    other = read_json(repo / "documents" / "feature" / f"{NEW_C}.json")
    change = read_json(repo / "changes" / f"{NEW_CR}.json")

    assert feature["id"] == NEW_A
    assert story["id"] == NEW_B
    assert other["id"] == NEW_C
    assert change["id"] == NEW_CR
    assert feature["title"] == f"Feature {NEW_B}"
    assert feature["origin_cr"] == NEW_CR
    assert [link["target"] for link in feature["links"]] == [NEW_C, NEW_B]
    assert [link["type"] for link in feature["links"]] == ["depends-on", "refines"]
    assert change["title"] == f"Change {NEW_A}"
    assert change["branch"] == NEW_A
    assert change["external_ref"] == NEW_B
    assert [entry["id"] for entry in change["scope"]] == [NEW_A, NEW_C]
    assert change["introduces"] == [NEW_B]
    assert change["version"] == 4
    assert [entry["base_version"] for entry in change["scope"]] == [7, 2]
    assert feature["version"] == 3
    assert story["version"] == 5
    assert [link["target_version"] for link in feature["links"]] == [1, 2]

    feature_body = (repo / "documents" / "feature" / f"{NEW_A}.md").read_text()
    assert f"[[{NEW_B}]]" in feature_body
    assert f"[[{NEW_B.lower()}]]" not in feature_body
    assert f"[story]({NEW_B})" in feature_body
    assert f"assets/{NEW_A}/diagram.png" in feature_body
    assert f"{OLD_B}0" in feature_body
    assert f"X{OLD_B}" in feature_body
    change_body = (repo / "changes" / f"{NEW_CR}.md").read_text()
    assert NEW_A in change_body
    assert NEW_B in change_body
    term_body = (repo / "glossary" / "typed-ids.md").read_text()
    assert f"[[{NEW_A}]]" in term_body
    assert f"`{NEW_B}`" in term_body

    assert feature["body_hash"] == body_hash(feature_body)
    assert change["body_hash"] == body_hash(
        (repo / "changes" / f"{NEW_CR}.md").read_text()
    )
    assert change["scope_hash"] == scope_hash([{"id": NEW_A}, {"id": NEW_C}])
    term = read_json(repo / "glossary" / "typed-ids.json")
    assert term["body_hash"] == body_hash(term_body)
    assert term["version"] == 2

    assert not (repo / "documents" / "feature" / f"{OLD_A}.json").exists()
    assert not (repo / "changes" / f"{OLD_CR}.md").exists()
    assert not (repo / "assets" / OLD_A).exists()
    assert (repo / "assets" / NEW_A / "diagram.png").read_bytes() == b"png"
    assert not (repo / ".gregraph" / "cache" / "index.json").exists()

    for path in [
        repo / "documents" / "feature" / f"{NEW_A}.json",
        repo / "documents" / "user-story" / f"{NEW_B}.json",
        repo / "changes" / f"{NEW_CR}.json",
    ]:
        text = path.read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert text == (
            json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )

    config = tomllib.loads((repo / ".gregraph" / "config.toml").read_text())
    assert config["gregraph"]["config_schema"] == 2
    assert config["types"]["feature"]["abbreviation"] == "FEAT"
    assert config["types"]["feature"]["kind"] == "requirement"
    assert config["types"]["feature"]["template"] == "feature"
    assert config["types"]["user-story"]["abbreviation"] == "STORY"
    assert config["types"]["functional-requirement"]["abbreviation"] == "FUNC"
    assert config["ids"]["prefix"] == "RE"
    assert config["versioning"]["on_outdated_links"] == "block"
    assert config["cr"]["deciders"] == []
    assert "#" not in (repo / ".gregraph" / "config.toml").read_text()


def test_idempotent(repo: Path) -> None:
    assert run(repo, "--apply").returncode == 0
    after_first = snapshot(repo)
    second = run(repo, "--apply")
    assert second.returncode == 0, second.stderr
    assert "nothing to do" in second.stdout
    assert snapshot(repo) == after_first


def test_partial_migration_completes(repo: Path) -> None:
    """A crash may leave one document typed and the config still at schema 1."""
    old_json = repo / "documents" / "feature" / f"{OLD_A}.json"
    old_md = repo / "documents" / "feature" / f"{OLD_A}.md"
    new_json = old_json.with_name(f"{NEW_A}.json")
    old_json.rename(new_json)
    old_md.rename(new_json.with_suffix(".md"))
    payload = read_json(new_json)
    payload["id"] = NEW_A
    write_json(new_json, payload)

    result = run(repo, "--apply")
    assert result.returncode == 0, result.stderr
    assert (repo / "documents" / "feature" / f"{NEW_A}.json").exists()
    assert (repo / "documents" / "user-story" / f"{NEW_B}.json").exists()
    assert (repo / "changes" / f"{NEW_CR}.json").exists()
    config = tomllib.loads((repo / ".gregraph" / "config.toml").read_text())
    assert config["gregraph"]["config_schema"] == 2


def test_schema_2_typed_ids_nothing_to_do(tmp_path: Path) -> None:
    (tmp_path / ".gregraph").mkdir()
    (tmp_path / ".gregraph" / "config.toml").write_text(
        """\
[gregraph]
config_schema = 2

[ids]
prefix = "RE"

[types.feature]
kind = "requirement"
template = "feature"
abbreviation = "FEAT"
""",
        encoding="utf-8",
    )
    body = "# Feature\n"
    payload = document_payload(
        uuid=UUID_A,
        id_=NEW_A,
        type_="feature",
        title="Feature",
        body=body,
    )
    write_body(tmp_path / "documents" / "feature" / f"{NEW_A}.md", body)
    sidecar = tmp_path / "documents" / "feature" / f"{NEW_A}.json"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    before = snapshot(tmp_path)

    result = run(tmp_path, "--apply")
    assert result.returncode == 0, result.stderr
    assert "nothing to do" in result.stdout
    assert snapshot(tmp_path) == before


def _init_git(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test Author",
            "-c",
            "user.email=test@example.org",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_dirty_tree_refused(repo: Path) -> None:
    _init_git(repo)
    (repo / "glossary" / "typed-ids.md").write_text("dirty\n", encoding="utf-8")
    before = snapshot(repo)
    result = run(repo, "--apply")
    assert result.returncode == 1
    assert "dirty" in result.stderr
    assert snapshot(repo) == before

    allowed = run(repo, "--apply", "--allow-dirty")
    assert allowed.returncode == 0, allowed.stderr


def test_custom_type_requires_abbreviation(tmp_path: Path) -> None:
    (tmp_path / ".gregraph").mkdir()
    (tmp_path / ".gregraph" / "config.toml").write_text(
        """\
[gregraph]
config_schema = 1

[ids]
prefix = "RE"

[types.feature]
kind = "requirement"
template = "feature"

[types.widget]
kind = "requirement"
template = "feature"
""",
        encoding="utf-8",
    )
    write_body(tmp_path / "documents" / "widget" / f"{OLD_A}.md", "# Widget\n")
    write_json(
        tmp_path / "documents" / "widget" / f"{OLD_A}.json",
        document_payload(
            uuid=UUID_A,
            id_=OLD_A,
            type_="widget",
            title="Widget",
            body="# Widget\n",
        ),
    )

    refused = run(tmp_path, "--apply")
    assert refused.returncode == 1
    assert "widget" in refused.stderr
    assert "--abbreviation widget=ABBR" in refused.stderr

    applied = run(tmp_path, "--apply", "--abbreviation", "widget=WGT")
    assert applied.returncode == 0, applied.stderr
    sidecar = read_json(tmp_path / "documents" / "widget" / "RE-WGT-000001.json")
    assert sidecar["id"] == "RE-WGT-000001"
    config = tomllib.loads((tmp_path / ".gregraph" / "config.toml").read_text())
    assert config["types"]["widget"]["abbreviation"] == "WGT"


@pytest.mark.parametrize(
    ("argument", "message"),
    [
        ("feature=feat", "expected [A-Z]{3,5}"),
        ("feature=CHG", "reserved"),
        ("feature=NFR", "duplicate abbreviation"),
    ],
)
def test_invalid_abbreviations_abort(repo: Path, argument: str, message: str) -> None:
    before = snapshot(repo)
    result = run(repo, "--apply", "--abbreviation", argument)
    assert result.returncode == 1
    assert message in result.stderr
    assert snapshot(repo) == before


def test_map_out(repo: Path) -> None:
    mapping_path = repo / "mapping.json"
    result = run(repo, "--apply", "--map-out", str(mapping_path))
    assert result.returncode == 0, result.stderr
    mapping = read_json(mapping_path)
    assert mapping["documents"] == {
        OLD_A: NEW_A,
        OLD_B: NEW_B,
        OLD_C: NEW_C,
    }
    assert mapping["changes"] == {OLD_CR: NEW_CR}
    assert mapping["abbreviations"]["feature"] == "FEAT"
    assert mapping["abbreviations"]["user-story"] == "STORY"
    assert mapping["abbreviations"]["test-case"] == "TEST"
