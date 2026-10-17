"""The universal ``--json`` contract matrix (AGENT_READINESS §2.1 R9, §2.5).

R9/AGENT-001: every registered command (and every subcommand of ``cr``,
``template``, ``term``, ``repair``, ``baseline``, ``hooks``, ``link``) runs
with ``--json`` and a fixed argument set in a seeded repository; each row
asserts the exit code, empty stderr, and that stdout is exactly one canonical
JSON document (``canonical_json(json.loads(stdout)) == stdout``, AGENT-102).
Every row runs against a fresh copy of a pristine seed so rows stay
independent.

The error-envelope half (§2.2, AGENT-002–006) asserts the envelope shape for
exit 2 (usage/parse/missing command/``--edit --json``/flag combinations),
exit 3 (``E-NO-REPOSITORY``/``E-ENV``), exit 4 (refusal findings with
``details``) and exit 5 (``E-INTERNAL``, with the ``GREGRAPH_DEBUG=1``
traceback escape hatch), plus ``--json --quiet`` precedence (R4) and the
exit-1 result-shaped documents (R5).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from gregraph.cli.main import main
from gregraph.cli.output import canonical_json

# --------------------------------------------------------------------------
# seed: one valid repository per git mode, copied per matrix row
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Seed:
    """IDs of the seeded entities, resolved after the seed ran."""

    root: Path
    a: str  # "Alpha story" (user-story, filled)
    b: str  # "Beta story" (user-story, filled, refines A)
    cr: str  # "Change the graph" (filled, scope: A modify)
    slug: str  # glossary term slug

    @property
    def a_md(self) -> str:
        """Repository-relative body path of document ``a``."""
        return f"documents/user-story/{self.a}.md"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _run(root: Path, *argv: str) -> int:
    return main(["--repo", str(root), *argv, "--no-input"])


def _id_by_title(root: Path, title: str) -> str:
    from gregraph.core.workspace import Workspace

    workspace = Workspace.open(root)
    return next(
        entry.model.id
        for entry in workspace.index.documents.values()
        if entry.model.title == title
    )


def _seed(root: Path, *, git_mode: bool) -> Seed:
    """Build a pristine, validation-clean repository at ``root``."""
    assert main(["init", str(root), "--no-git"]) == 0
    assert (
        _run(
            root,
            "new",
            "user-story",
            "--title",
            "Alpha story",
            "--section",
            "Story=As an agent, I want a seeded story.",
            "--section",
            "Acceptance criteria=Given the seed, When it runs, Then it passes.",
        )
        == 0
    )
    a = _id_by_title(root, "Alpha story")
    assert (
        _run(
            root,
            "new",
            "user-story",
            "--title",
            "Beta story",
            "--link",
            f"refines:{a}",
            "--section",
            "Story=As an agent, I want a second story.",
            "--section",
            "Acceptance criteria=Given Beta, When it runs, Then it passes.",
        )
        == 0
    )
    assert (
        _run(
            root,
            "cr",
            "new",
            "--title",
            "Change the graph",
            "--scope",
            f"{a}:modify",
            "--section",
            "Motivation=The seeded story needs a change.",
            "--section",
            "Proposed change=Rewrite the seeded story.",
            "--section",
            "Impact=The inbound link stays valid.",
        )
        == 0
    )
    assert (
        _run(
            root,
            "term",
            "add",
            "Knowledge base",
            "--section",
            "Definition=A store of requirement documents.",
        )
        == 0
    )
    if git_mode:
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.name", "T")
        _git(root, "config", "user.email", "t@e")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "seed")
    cr = next((root / "changes").glob("*.md")).stem
    return Seed(
        root=root,
        a=a,
        b=_id_by_title(root, "Beta story"),
        cr=cr,
        slug="knowledge-base",
    )


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> dict[bool, Seed]:
    """One pristine seed per git mode; matrix rows work on copies of it."""
    seeds: dict[bool, Seed] = {}
    for git_mode in (False, True):
        base = tmp_path_factory.mktemp("pristine-git" if git_mode else "pristine")
        seeds[git_mode] = _seed(base / "repo", git_mode=git_mode)
    return seeds


def _fresh_copy(pristine: dict[bool, Seed], git_mode: bool, name: str) -> Seed:
    """A writable copy of the pristine seed (rows must not disturb each other)."""
    source = pristine[git_mode]
    root = source.root.parent / name
    shutil.copytree(source.root, root, symlinks=True)
    return Seed(root=root, a=source.a, b=source.b, cr=source.cr, slug=source.slug)


# --------------------------------------------------------------------------
# the R9 success matrix (AGENT-001, AGENT-007, AGENT-102)
# --------------------------------------------------------------------------


#: (name, argument builder, needs git) — the builder maps the seed to argv;
#: ``--json`` is appended by the runner. Expected exit is 0 for every row:
#: the seed is validation-clean and rows run in isolated copies.
SUCCESS_CASES: list[tuple[str, Callable[[Seed], list[str]], bool]] = [
    ("init", lambda s: ["init", str(s.root / "fresh"), "--no-git"], False),
    (
        "new",
        lambda s: [
            "new",
            "user-story",
            "--title",
            "Gamma story",
            "--section",
            "Story=As an agent, I want a third story.",
            "--section",
            "Acceptance criteria=Given Gamma, When run, Then passes.",
        ],
        False,
    ),
    ("link", lambda s: ["link", s.b, "relates-to", s.a], False),
    ("link-candidates", lambda s: ["link", "--candidates", s.a], False),
    ("link-refresh", lambda s: ["link", "refresh", "--all"], False),
    ("unlink", lambda s: ["unlink", s.b, "refines", s.a], False),
    ("set", lambda s: ["set", s.a, "tags=team"], False),
    ("sync", lambda s: ["sync"], False),
    ("check", lambda s: ["check"], False),
    ("validate", lambda s: ["validate"], False),
    ("list", lambda s: ["list"], False),
    ("show", lambda s: ["show", s.a], False),
    ("edit", lambda s: ["edit", s.a, "--section", "Notes=Updated notes."], False),
    ("status", lambda s: ["status"], False),
    ("schema", lambda s: ["schema"], False),
    ("context", lambda s: ["context", s.a], False),
    ("graph", lambda s: ["graph"], False),
    (
        "supersede",
        lambda s: ["supersede", s.a, "--title", "Alpha story (v2)"],
        False,
    ),
    ("deprecate", lambda s: ["deprecate", s.a, "--reason", "obsolete"], False),
    ("undeprecate", lambda s: ["undeprecate", s.a], False),
    ("migrate", lambda s: ["migrate", "--all", "--dry-run"], False),
    ("template-list", lambda s: ["template", "list"], False),
    ("template-show", lambda s: ["template", "show", "user-story"], False),
    ("template-add", lambda s: ["template", "add", "goal"], False),
    ("template-bump", lambda s: ["template", "bump", "user-story"], False),
    (
        "cr-new",
        lambda s: [
            "cr",
            "new",
            "--title",
            "Another change",
            "--section",
            "Motivation=Because.",
            "--section",
            "Proposed change=This.",
            "--section",
            "Impact=That.",
        ],
        False,
    ),
    ("cr-scope-add", lambda s: ["cr", "scope", "add", s.cr, s.b], False),
    ("cr-scope-remove", lambda s: ["cr", "scope", "remove", s.cr, s.b], False),
    ("cr-set", lambda s: ["cr", "set", s.cr, "branch=feat/change"], False),
    ("cr-reaffirm", lambda s: ["cr", "reaffirm", s.cr], False),
    ("cr-reanalyze", lambda s: ["cr", "reanalyze", s.cr], False),
    ("cr-list", lambda s: ["cr", "list"], False),
    ("cr-show", lambda s: ["cr", "show", s.cr], False),
    (
        "term-add",
        lambda s: [
            "term",
            "add",
            "Glossary entry",
            "--section",
            "Definition=Defined here.",
        ],
        False,
    ),
    ("term-list", lambda s: ["term", "list"], False),
    ("term-show", lambda s: ["term", "show", s.slug], False),
    ("term-usage", lambda s: ["term", "usage", s.slug], False),
    ("term-rename", lambda s: ["term", "rename", s.slug, "Renamed term"], False),
    (
        "term-deprecate",
        lambda s: ["term", "deprecate", s.slug, "--reason", "obsolete"],
        False,
    ),
    ("repair-versions", lambda s: ["repair", "versions"], False),
    ("repair-cache", lambda s: ["repair", "cache"], False),
    ("repair-agents", lambda s: ["repair", "agents"], False),
    ("repair-regenerate-id", lambda s: ["repair", "regenerate-id", s.a_md], False),
    ("hook-pre-commit", lambda s: ["hook", "pre-commit"], False),
    ("hooks-status", lambda s: ["hooks", "status"], False),
    ("hooks-install", lambda s: ["hooks", "install"], True),
    ("hooks-uninstall", lambda s: ["hooks", "uninstall"], True),
    ("baseline-create", lambda s: ["baseline", "create", "v1"], True),
    ("baseline-list", lambda s: ["baseline", "list"], True),
]


@pytest.mark.parametrize("git_mode", [False, True], ids=["no-git", "git"])
def test_every_command_emits_one_canonical_json_document(
    tmp_path: Path,
    pristine: dict[bool, Seed],
    git_mode: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for index, (name, build, needs_git) in enumerate(SUCCESS_CASES):
        if needs_git and not git_mode:
            continue
        seed = _fresh_copy(pristine, git_mode, f"row{index:02d}-{name}")
        argv = build(seed)
        capsys.readouterr()
        exit_code = main(["--repo", str(seed.root), *argv, "--json"])
        out = capsys.readouterr()
        assert exit_code == 0, f"{name}: exit {exit_code}\n{out.out}{out.err}"
        assert out.err == "", f"{name}: stderr not empty: {out.err!r}"
        # Exactly one canonical JSON value on stdout (AGENT-001/102).
        assert canonical_json(json.loads(out.out)) == out.out, name


# --------------------------------------------------------------------------
# error envelopes (§2.2, AGENT-002–003) and precedence rules
# --------------------------------------------------------------------------


def _error(
    capsys: pytest.CaptureFixture[str], seed: Seed, *argv: str
) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    exit_code = main(["--repo", str(seed.root), *argv, "--json"])
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert canonical_json(payload) == out.out
    assert out.err == "", f"stderr not empty: {out.err!r}"
    assert set(payload) == {"error"}, f"unexpected payload keys: {sorted(payload)}"
    error = payload["error"]
    assert set(error) == {"code", "exit_code", "message", "finding", "details"}
    assert error["exit_code"] == exit_code
    return exit_code, payload


def test_exit_2_usage_error_envelope(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    seed = _fresh_copy(pristine, git_mode=False, name="usage")
    exit_code, payload = _error(capsys, seed, "new", "--no-input")
    assert exit_code == 2
    assert payload["error"]["code"] == "E-USAGE"
    assert payload["error"]["finding"] is None


def test_exit_2_parse_error_carries_usage(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    seed = _fresh_copy(pristine, git_mode=False, name="parse")
    exit_code, payload = _error(
        capsys, seed, "new", "user-story", "--title", "T", "--template-version", "x"
    )
    assert exit_code == 2
    assert payload["error"]["code"] == "E-USAGE"
    usage = payload["error"]["details"]["usage"]
    assert isinstance(usage, str) and "usage:" in usage


def test_exit_2_missing_command_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    capsys.readouterr()
    exit_code = main(["--json"])
    out = capsys.readouterr()
    assert exit_code == 2
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-USAGE"
    assert "gregraph" in payload["error"]["details"]["usage"]
    assert out.err == ""


def test_exit_2_edit_json_without_content_flags(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """§2.4.1: ``edit`` with ``--json`` and no content flags is refused."""
    seed = _fresh_copy(pristine, git_mode=False, name="edit-json")
    exit_code, payload = _error(capsys, seed, "edit", seed.a)
    assert exit_code == 2
    assert payload["error"]["code"] == "E-USAGE"
    assert "--body" in str(payload["error"]["message"])


def test_exit_2_edit_json_rejects_editor_flag(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """R8: ``--edit`` and ``--json`` are mutually exclusive."""
    seed = _fresh_copy(pristine, git_mode=False, name="edit-json-editor")
    exit_code, payload = _error(capsys, seed, "edit", seed.a, "--body", "x", "--edit")
    assert exit_code == 2
    assert payload["error"]["code"] == "E-USAGE"


def test_exit_2_flag_combination_is_usage(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """AGENT-020: ``--body`` with ``--section`` exits 2 and writes nothing."""
    seed = _fresh_copy(pristine, git_mode=False, name="flag-combo")
    before = sorted(path.name for path in (seed.root / "documents").rglob("*.md"))
    exit_code, payload = _error(
        capsys,
        seed,
        "new",
        "user-story",
        "--title",
        "T",
        "--body",
        "text",
        "--section",
        "Story=x",
    )
    assert exit_code == 2
    assert payload["error"]["code"] == "E-USAGE"
    after = sorted(path.name for path in (seed.root / "documents").rglob("*.md"))
    assert after == before


def test_exit_3_no_repository_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    exit_code = main(["--repo", str(tmp_path / "nowhere"), "--json", "list"])
    out = capsys.readouterr()
    assert exit_code == 3
    payload = json.loads(out.out)
    assert payload["error"]["code"] == "E-NO-REPOSITORY"
    assert canonical_json(payload) == out.out
    assert out.err == ""


def test_exit_3_env_envelope_for_invalid_config(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """§2.2: a config read failure (pydantic ``ValidationError``) is ``E-ENV``."""
    seed = _fresh_copy(pristine, git_mode=False, name="env")
    config = seed.root / ".gregraph" / "config.toml"
    original = config.read_text(encoding="utf-8")
    config.write_text("[ids]\nprefix = 5\n", encoding="utf-8")
    try:
        exit_code, payload = _error(capsys, seed, "list")
    finally:
        config.write_text(original, encoding="utf-8")
    assert exit_code == 3
    assert payload["error"]["code"] == "E-ENV"
    assert payload["error"]["finding"] is None


def test_exit_4_refusal_envelope_carries_finding_details(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """AGENT-003/017: the self-describing template refusal (exit 4)."""
    seed = _fresh_copy(pristine, git_mode=False, name="section-unknown")
    exit_code, payload = _error(
        capsys,
        seed,
        "new",
        "user-story",
        "--title",
        "T",
        "--section",
        "Bogus Heading=content",
    )
    assert exit_code == 4
    error = payload["error"]
    assert error["code"] == "E-SECTION-UNKNOWN"
    finding = error["finding"]
    assert finding["code"] == "E-SECTION-UNKNOWN"
    details = finding["details"]
    headings = [section["heading"] for section in details["template_sections"]]
    assert "Story" in headings
    assert details["given_heading"] == "Bogus Heading"
    assert error["details"] == details


def test_exit_4_cycle_refusal_envelope(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """AGENT-003: a cycle refusal carries the complete ``Finding`` in the
    envelope (its reconstructed path is in the message; ``details`` mirrors
    the finding's, ``{}`` when the refusal has none)."""
    seed = _fresh_copy(pristine, git_mode=False, name="cycle")
    exit_code, payload = _error(capsys, seed, "link", seed.a, "refines", seed.b)
    assert exit_code == 4
    error = payload["error"]
    assert error["code"] == "E-CYCLE"
    finding = error["finding"]
    assert finding["code"] == "E-CYCLE"
    assert finding["severity"] == "E"
    assert str(seed.b) in str(finding["message"])
    assert error["details"] == (finding.get("details") or {})


def test_exit_5_internal_envelope(
    pristine: dict[bool, Seed],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _fresh_copy(pristine, git_mode=False, name="internal")
    import gregraph.cli.commands.status as status_module

    def boom(args: object, app: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(status_module, "run", boom)
    exit_code, payload = _error(capsys, seed, "status")
    assert exit_code == 5
    assert payload["error"]["code"] == "E-INTERNAL"
    assert "boom" in str(payload["error"]["message"])
    assert payload["error"]["finding"] is None


def test_exit_5_debug_escape_hatch_prints_traceback(
    pristine: dict[bool, Seed],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§2.2: with ``GREGRAPH_DEBUG=1`` the traceback goes to stderr (debug
    escape hatch, not part of the contract); stdout still carries the
    envelope."""
    seed = _fresh_copy(pristine, git_mode=False, name="internal-debug")
    import gregraph.cli.commands.status as status_module

    def boom(args: object, app: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(status_module, "run", boom)
    monkeypatch.setenv("GREGRAPH_DEBUG", "1")
    capsys.readouterr()
    exit_code = main(["--repo", str(seed.root), "status", "--json"])
    out = capsys.readouterr()
    assert exit_code == 5
    assert json.loads(out.out)["error"]["code"] == "E-INTERNAL"
    assert "Traceback" in out.err


def test_json_quiet_precedence(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """R4/AGENT-006: ``--json --quiet`` still prints the payload."""
    seed = _fresh_copy(pristine, git_mode=False, name="quiet")
    capsys.readouterr()
    exit_code = main(
        [
            "--repo",
            str(seed.root),
            "new",
            "user-story",
            "--title",
            "Quiet story",
            "--section",
            "Story=As an agent, I want quiet JSON.",
            "--section",
            "Acceptance criteria=Given quiet, When run, Then prints.",
            "--no-input",
            "--json",
            "-q",
        ]
    )
    out = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(out.out)
    assert payload["id"]
    assert canonical_json(payload) == out.out


def test_exit_1_validate_is_result_shaped(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """R5/AGENT-005: exit 1 under ``--json`` is the result document, not an
    error envelope."""
    seed = _fresh_copy(pristine, git_mode=False, name="validate-strict")
    assert _run(seed.root, "new", "assumption", "--title", "Lonely assumption") == 0
    capsys.readouterr()
    exit_code = main(["--repo", str(seed.root), "validate", "--strict", "--json"])
    out = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(out.out)
    assert isinstance(payload, list)
    assert canonical_json(payload) == out.out
    assert out.err == ""


def test_exit_1_check_is_result_shaped(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    seed = _fresh_copy(pristine, git_mode=False, name="check-blocked")
    sidecar = next((seed.root / "documents").rglob(f"{seed.a}.json"))
    sidecar.write_text('{"schema": 1, "broken": true}', encoding="utf-8")
    shutil.rmtree(seed.root / ".gregraph" / "cache", ignore_errors=True)
    capsys.readouterr()
    exit_code = main(["--repo", str(seed.root), "check", "--json"])
    out = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(out.out)
    assert "error" not in payload
    assert payload["blocked"] is True
    assert canonical_json(payload) == out.out


def test_deterministic_payloads(
    pristine: dict[bool, Seed], capsys: pytest.CaptureFixture[str]
) -> None:
    """AGENT-007: identical invocations produce identical bytes."""
    seed = _fresh_copy(pristine, git_mode=False, name="determinism")
    capsys.readouterr()
    main(["--repo", str(seed.root), "schema", "--json"])
    first = capsys.readouterr().out
    main(["--repo", str(seed.root), "schema", "--json"])
    second = capsys.readouterr().out
    assert first == second
