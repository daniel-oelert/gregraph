"""Shared pytest fixtures (spec §17, §3).

Test scaffolding may shell out to ``git`` directly to set up fixtures; all
*product* Git access goes through ``gregraph.core.git`` (spec §12.1).
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

import pytest

from gregraph.core.config import Config, write_config
from gregraph.core.graph import Graph
from gregraph.core.hashing import body_hash
from gregraph.core.ids import derive_id
from gregraph.core.models import (
    Deprecation,
    Document,
    Link,
    LinkType,
    TemplateRef,
)
from gregraph.core.storage import config_path, write_body, write_sidecar
from gregraph.core.workspace import Workspace


class GitIdentity(NamedTuple):
    """Configured Git identity (spec §12.2)."""

    name: str
    email: str


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write_layout(root: Path) -> None:
    """Materialise the repository layout of spec §3.

    ``gregraph init`` (spec §13.1) will do this properly in S17; until then the
    fixture writes the root marker and managed directories directly. Only the
    root marker ``.gregraph/config.toml`` is content-free (config model is S3).
    """
    (root / ".gregraph").mkdir()
    (root / ".gregraph" / "config.toml").write_text(
        "# gregraph configuration (spec §5.3, appendix B.1)\n",
        encoding="utf-8",
    )
    (root / ".gregraph" / "templates").mkdir()
    for name in ("documents", "changes", "glossary", "assets"):
        (root / name).mkdir()
    (root / ".gitignore").write_text(".gregraph/cache/\n", encoding="utf-8")


@pytest.fixture(params=[False, True], ids=["no-git", "git"])
def tmp_repo(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """Initialised gregraph repository in ``tmp_path``, with and without ``git init``.

    Spec §17: parameterised ``tmp_repo``; returns the repository root path.
    """
    _write_layout(tmp_path)
    if request.param:
        _run_git(tmp_path, "init")
    return tmp_path


@pytest.fixture
def identity(tmp_repo: Path) -> GitIdentity:
    """Set ``user.name``/``user.email`` in ``tmp_repo`` (spec §12.2, §17).

    Git identity only exists inside a repository, so this fixture skips when
    ``tmp_repo`` was parameterised without ``git init``.
    """
    if not (tmp_repo / ".git").exists():
        pytest.skip("identity requires a git-initialised tmp_repo (spec §12.2)")
    git_identity = GitIdentity(name="Test Author", email="test.author@example.org")
    _run_git(tmp_repo, "config", "user.name", git_identity.name)
    _run_git(tmp_repo, "config", "user.email", git_identity.email)
    return git_identity


class SampleGraph(NamedTuple):
    """Materialised ``sample_graph``: files, workspace, graph, role → ID map."""

    root: Path
    workspace: Workspace
    graph: Graph
    ids: dict[str, str]


SAMPLE_CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=dt.UTC)

#: role -> (type, title, [(role, link type), …]) — 14 documents covering all
#: five kinds and all nine edge types (spec §6.1), incl. a superseded node, a
#: deprecated edge-less node, and a true orphan (spec §6.3).
_SAMPLE_SPECS: dict[str, tuple[str, str, tuple[tuple[str, LinkType], ...]]] = {
    "goal": ("goal", "Increase self-service", ()),
    "compliance": (
        "goal",
        "Meet GDPR",
        (("design", "conflicts-with"),),
    ),
    "epic": ("epic", "Knowledge base", (("goal", "refines"),)),
    "feature": ("feature", "Upload documents", (("epic", "refines"),)),
    "story": (
        "user-story",
        "Upload from the desktop",
        (("feature", "refines"), ("story_old", "supersedes")),
    ),
    "story_old": ("user-story", "Upload from the desktop (old)", ()),
    "scan_story": (
        "user-story",
        "Scan uploads for malware",
        (("feature", "derives-from"),),
    ),
    "fr": (
        "functional-requirement",
        "Pipeline rejects infected files",
        (("scan_story", "refines"), ("story", "depends-on")),
    ),
    "nfr": (
        "non-functional-requirement",
        "P95 upload latency under 3 s",
        (("feature", "constrains"),),
    ),
    "design": (
        "design",
        "Ingestion pipeline",
        (("feature", "satisfies"),),
    ),
    "test": (
        "test-case",
        "Upload happy path",
        (("story", "verifies"), ("design", "verifies")),
    ),
    "stakeholder": (
        "stakeholder",
        "Anna the compliance officer",
        (("goal", "relates-to"),),
    ),
    "orphan": ("assumption", "Users have modern browsers", ()),
    "stale_note": ("assumption", "English-only is enough", ()),
}


def _sample_uuid(index: int) -> UUID:
    """Deterministic UUID whose §4.1 ID body is ``encode_body(index)``."""
    return UUID(int=index << 98)


@pytest.fixture
def sample_graph(tmp_repo: Path) -> SampleGraph:
    """A dozen-plus documents across kinds with a realistic edge mix (spec §17).

    Deterministic IDs (S16 golden tests depend on them). ``ids`` maps the role
    names of the spec table to the derived document IDs. Writes a full default
    ``config.toml`` so type→kind resolution works.
    """
    write_config(config_path(tmp_repo), Config())
    config = Config()
    ids = {
        role: derive_id(_sample_uuid(index))
        for index, role in enumerate(_SAMPLE_SPECS, start=1)
    }

    for index, (role, (type_name, title, link_specs)) in enumerate(
        _SAMPLE_SPECS.items(), start=1
    ):
        links = [
            Link(
                type=link_type,
                target=ids[target_role],
                target_version=1,
            )
            for target_role, link_type in sorted(
                link_specs, key=lambda item: (item[1], item[0])
            )
        ]
        body = f"# {title}\n\nSample body for {title}.\n"
        document = Document(
            schema=1,
            uuid=_sample_uuid(index),
            id=ids[role],
            type=type_name,
            title=title,
            created=SAMPLE_CREATED,
            created_by=None,
            template=TemplateRef(name=config.types[type_name].template, version=1),
            version=1,
            body_hash=body_hash(body),
            assets=[],
            links=links,
            deprecated=(
                Deprecation(at=SAMPLE_CREATED, by=None, reason="obsolete assumption")
                if role == "stale_note"
                else None
            ),
            tags=[],
            extra={},
        )
        folder = config.types[type_name].folder
        body_rel = Path("documents") / folder / f"{ids[role]}.md"
        sidecar_rel = Path("documents") / folder / f"{ids[role]}.json"
        write_body(tmp_repo / body_rel, body)
        write_sidecar(tmp_repo / sidecar_rel, document)

    workspace = Workspace.open(tmp_repo)
    return SampleGraph(
        root=tmp_repo, workspace=workspace, graph=workspace.graph, ids=dict(ids)
    )
