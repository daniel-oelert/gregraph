"""Tests for ``gregraph hook pre-commit`` (spec §13.22, §7.5) — real Git commits.

M3 acceptance: a real ``git commit`` in ``tmp_repo`` is blocked when a link is
newly outdated and succeeds after ``link refresh``; sidecar changes (the
bump) are asserted. Plus: degraded-mode ``sync`` bumps, refinement 2
(previously outdated links never block), policy handling
(``versioning.on_outdated_links``, ``versioning.on_cr_modified``,
``graph.open_conflicts``), BOOT-303 (no CR findings for scope-target edits)
and BOOT-128 (drift/scope changes never abort).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import GitIdentity

from gregraph.cli.main import main
from gregraph.core.config import Config, GraphSection, VersioningSection, write_config
from gregraph.core.hashing import asset_hash, body_hash
from gregraph.core.ids import derive_id
from gregraph.core.models import AssetRef, Document, Link, TemplateRef
from gregraph.core.storage import (
    assets_dir,
    config_path,
    document_paths,
    read_sidecar,
    templates_dir,
    write_body,
    write_sidecar,
)
from gregraph.core.templates import LoadedTemplate, load_template_dir


def install_templates(root: Path) -> None:
    """Copy every shipped built-in template into the repository (spec §5.5)."""
    from importlib.resources import files as resource_files

    source_root = resource_files("gregraph").joinpath("builtin_templates")
    for name in sorted(entry.name for entry in source_root.iterdir() if entry.is_dir()):
        for version in source_root.joinpath(name).iterdir():
            if not version.is_dir():
                continue
            target = root / ".gregraph" / "templates" / name / version.name
            target.mkdir(parents=True, exist_ok=True)
            for child in version.iterdir():
                if child.is_file():
                    (target / child.name).write_bytes(child.read_bytes())


def git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def git_commit(
    root: Path, message: str = "commit", *extra: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "commit", "-m", message, *extra],
        cwd=root,
        check=False,
        capture_output=True,
    )


def hook_output(proc: subprocess.CompletedProcess[bytes]) -> str:
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _template(root: Path, name: str) -> LoadedTemplate:
    versions = sorted(
        load_template_dir(templates_dir(root))[name], key=lambda t: t.version
    )
    return versions[0]


def filled_body(root: Path, template_name: str, title: str) -> str:
    """A body with every template section filled (clean validation, §5.5)."""
    descriptor = _template(root, template_name).descriptor
    lines = [f"# {title}", ""]
    for section in descriptor.sections:
        lines.append(f"## {section.heading}")
        lines.append(f"Filled content for {section.heading} of {title}.")
        lines.append("")
    return "\n".join(lines)


def write_doc(
    root: Path,
    type_name: str,
    title: str,
    links: list[Link] | None = None,
    *,
    assets: list[AssetRef] | None = None,
) -> str:
    """Write a validation-clean document pair; returns its ID (spec §5.4)."""
    config = Config()
    spec = config.types[type_name]
    body = filled_body(root, spec.template, title)
    generated = uuid4()
    doc_id = derive_id(generated)
    document = Document(
        schema=1,
        uuid=generated,
        id=doc_id,
        type=type_name,
        title=title,
        created=dt.datetime(2026, 9, 10, 12, 0, 0, tzinfo=dt.UTC),
        created_by=None,
        template=TemplateRef(name=spec.template, version=1),
        version=1,
        body_hash=body_hash(body),
        assets=list(assets or []),
        links=list(links or []),
        deprecated=None,
        tags=[],
        extra={},
    )
    body_abs, sidecar_abs = document_paths(root, spec.folder, doc_id)
    write_body(body_abs, body)
    write_sidecar(sidecar_abs, document)
    return doc_id


def doc_body(root: Path, doc_id: str) -> Path:
    for path in (root / "documents").rglob(f"{doc_id}.md"):
        return path
    raise AssertionError(f"no body for {doc_id}")


def doc_sidecar(root: Path, doc_id: str) -> Path:
    for path in (root / "documents").rglob(f"{doc_id}.json"):
        return path
    raise AssertionError(f"no sidecar for {doc_id}")


def fill_cr_body(root: Path, cr_id: str) -> None:
    """Rewrite a CR body with every required section filled (spec §5.5)."""
    path = root / "changes" / f"{cr_id}.md"
    title = path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ").strip()
    path.write_text(filled_body(root, "change-request", title), encoding="utf-8")


def link(type: str, target: str, target_version: int = 1) -> Link:
    return Link(type=type, target=target, target_version=target_version)  # type: ignore[arg-type]


@pytest.fixture
def hook_repo(tmp_repo: Path, identity: GitIdentity) -> Path:
    """Git-backed repository with templates, default config, branch ``main``."""
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    git(tmp_repo, "symbolic-ref", "HEAD", "refs/heads/main")
    assert main(["--repo", str(tmp_repo), "hooks", "install"]) == 0
    return tmp_repo


def install_hook_only(root: Path) -> None:
    assert main(["--repo", str(root), "hooks", "install"]) == 0


# --------------------------------------------------------------------------
# M3 acceptance (BOOT-301)
# --------------------------------------------------------------------------


def test_commit_blocked_on_newly_outdated_link(
    hook_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = hook_repo
    target = write_doc(root, "feature", "Upload documents")
    source = write_doc(
        root,
        "user-story",
        "Upload from the desktop",
        [link("depends-on", target)],
    )
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    body = doc_body(root, target)
    body.write_text(
        body.read_text(encoding="utf-8") + "\nEdited after review.\n", encoding="utf-8"
    )
    git(root, "add", "-A")
    proc = git_commit(root, "edit target")
    output = hook_output(proc)
    assert proc.returncode != 0
    assert "newly outdated" in output
    assert f"gregraph link refresh {source} depends-on {target}" in output

    sidecar = read_sidecar(doc_sidecar(root, target), Document)
    assert sidecar.version == 2

    assert main(["--repo", str(root), "link", "refresh", "--to", target]) == 0
    capsys.readouterr()
    git(root, "add", "-A")
    proc = git_commit(root, "edit target")
    assert proc.returncode == 0
    source_model = read_sidecar(doc_sidecar(root, source), Document)
    assert source_model.links[0].target_version == 2
    committed = git(root, "show", "HEAD:documents/user-story/" + f"{source}.json")
    assert b'"target_version": 2' in committed.stdout


def test_retry_without_refresh_stays_blocked(hook_repo: Path) -> None:
    root = hook_repo
    target = write_doc(root, "feature", "Upload documents")
    write_doc(
        root, "user-story", "Upload from the desktop", [link("depends-on", target)]
    )
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    body = doc_body(root, target)
    body.write_text(body.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    git(root, "add", "-A")
    assert git_commit(root, "edit target").returncode != 0
    retry = git_commit(root, "edit target again")
    assert retry.returncode != 0
    assert "newly outdated" in hook_output(retry)


def test_clean_commit_succeeds(hook_repo: Path) -> None:
    root = hook_repo
    target = write_doc(root, "feature", "Upload documents")
    write_doc(
        root, "user-story", "Upload from the desktop", [link("depends-on", target)]
    )
    git(root, "add", "-A")
    proc = git_commit(root, "initial")
    assert proc.returncode == 0
    assert "bumped" not in hook_output(proc)


def test_hook_is_a_noop_without_staged_files(hook_repo: Path) -> None:
    assert git_commit(hook_repo, "empty", "--allow-empty").returncode == 0


def test_bump_records_staged_content_not_unstaged_edits(hook_repo: Path) -> None:
    root = hook_repo
    doc_id = write_doc(root, "feature", "Upload documents")
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    body = doc_body(root, doc_id)
    staged = body.read_text(encoding="utf-8") + "\nStaged edit.\n"
    body.write_text(staged, encoding="utf-8")
    git(root, "add", "-A")
    body.write_text(staged + "\nUnstaged edit.\n", encoding="utf-8")
    assert git_commit(root, "staged edit").returncode == 0

    sidecar = read_sidecar(doc_sidecar(root, doc_id), Document)
    assert sidecar.version == 2
    assert sidecar.body_hash == body_hash(staged)


def test_asset_change_bumps_document(hook_repo: Path) -> None:
    root = hook_repo
    asset_bytes = b"png-bytes-v1"
    generated_uuid = uuid4()
    doc_id = derive_id(generated_uuid)
    config = Config()
    spec = config.types["feature"]
    body = filled_body(root, spec.template, "Upload documents")
    body += f"\n![flow](../../assets/{doc_id}/pic.png)\n"
    document = Document(
        schema=1,
        uuid=generated_uuid,
        id=doc_id,
        type="feature",
        title="Upload documents",
        created=dt.datetime(2026, 9, 10, 12, 0, 0, tzinfo=dt.UTC),
        created_by=None,
        template=TemplateRef(name=spec.template, version=1),
        version=1,
        body_hash=body_hash(body),
        assets=[AssetRef(path="pic.png", hash=asset_hash(asset_bytes))],
        links=[],
        deprecated=None,
        tags=[],
        extra={},
    )
    body_abs, sidecar_abs = document_paths(root, spec.folder, doc_id)
    write_body(body_abs, body)
    write_sidecar(sidecar_abs, document)
    folder = assets_dir(root, doc_id)
    folder.mkdir(parents=True)
    (folder / "pic.png").write_bytes(asset_bytes)

    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    (folder / "pic.png").write_bytes(b"png-bytes-v2")
    git(root, "add", "-A")
    proc = git_commit(root, "asset change")
    assert proc.returncode == 0
    assert f"bumped {doc_id}" in hook_output(proc)
    sidecar_model = read_sidecar(sidecar_abs, Document)
    assert sidecar_model.version == 2
    assert sidecar_model.assets[0].hash == asset_hash(b"png-bytes-v2")


# --------------------------------------------------------------------------
# refinement 2: previously outdated links never block
# --------------------------------------------------------------------------


def test_previously_outdated_links_do_not_block(hook_repo: Path) -> None:
    root = hook_repo
    target = write_doc(root, "feature", "Upload documents")
    other = write_doc(root, "feature", "Scan uploads")
    git(root, "add", "-A")
    assert git_commit(root, "target on main").returncode == 0

    git(root, "checkout", "-b", "feature-links")
    source = write_doc(
        root, "user-story", "Upload from the desktop", [link("depends-on", target)]
    )
    git(root, "add", "-A")
    assert git_commit(root, "linking story").returncode == 0

    git(root, "checkout", "main")
    body = doc_body(root, target)
    body.write_text(
        body.read_text(encoding="utf-8") + "\nColleague edit.\n", encoding="utf-8"
    )
    git(root, "add", "-A")
    assert git_commit(root, "colleague bump").returncode == 0

    git(root, "checkout", "feature-links")
    git(root, "merge", "main", "-m", "merge main")

    other_body = doc_body(root, other)
    other_body.write_text(
        other_body.read_text(encoding="utf-8") + "\nUnrelated edit.\n",
        encoding="utf-8",
    )
    git(root, "add", "-A")
    proc = git_commit(root, "unrelated edit")
    output = hook_output(proc)
    assert proc.returncode == 0
    assert "previously outdated" in output
    assert "newly outdated" not in output

    target_body = doc_body(root, target)
    target_body.write_text(
        target_body.read_text(encoding="utf-8") + "\nFurther edit.\n", encoding="utf-8"
    )
    git(root, "add", "-A")
    proc = git_commit(root, "edit the already-outdated target")
    output = hook_output(proc)
    assert proc.returncode == 0
    assert "previously outdated" in output
    source_model = read_sidecar(doc_sidecar(root, source), Document)
    assert source_model.links[0].target_version == 1


# --------------------------------------------------------------------------
# policies
# --------------------------------------------------------------------------


def test_validation_errors_block(hook_repo: Path) -> None:
    root = hook_repo
    doc_id = write_doc(root, "feature", "Upload documents")
    body = doc_body(root, doc_id)
    body.write_text("# Upload documents\n", encoding="utf-8")
    git(root, "add", "-A")
    proc = git_commit(root, "broken document")
    output = hook_output(proc)
    assert proc.returncode != 0
    assert "validation error" in output


def test_warnings_never_abort(hook_repo: Path) -> None:
    root = hook_repo
    orphan = write_doc(root, "assumption", "Users have modern browsers")
    git(root, "add", "-A")
    proc = git_commit(root, "orphan document")
    output = hook_output(proc)
    assert proc.returncode == 0
    assert "W-ORPHAN" in output
    assert f"bumped {orphan}" not in output


def test_outdated_links_policy_warn(hook_repo: Path) -> None:
    root = hook_repo
    write_config(
        config_path(root),
        Config(versioning=VersioningSection(on_outdated_links="warn")),
    )
    target = write_doc(root, "feature", "Upload documents")
    write_doc(
        root, "user-story", "Upload from the desktop", [link("depends-on", target)]
    )
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0
    body = doc_body(root, target)
    body.write_text(body.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    git(root, "add", "-A")
    proc = git_commit(root, "edit target")
    output = hook_output(proc)
    assert proc.returncode == 0
    assert "newly outdated" in output


def test_open_conflicts_block_only_on_baseline_branch(hook_repo: Path) -> None:
    root = hook_repo
    write_config(config_path(root), Config(graph=GraphSection(open_conflicts="block")))
    left = write_doc(root, "feature", "Pipeline rejects infected files")
    right = write_doc(root, "feature", "Pipeline keeps every upload")
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    right_model = read_sidecar(doc_sidecar(root, right), Document)
    right_model.links.append(link("conflicts-with", left))
    write_sidecar(doc_sidecar(root, right), right_model)
    git(root, "add", "-A")
    proc = git_commit(root, "record the conflict on main")
    output = hook_output(proc)
    assert proc.returncode != 0
    assert "open conflicts" in output
    assert "W-CONFLICT-OPEN" in output

    git(root, "checkout", "-b", "analysis")
    proc = git_commit(root, "conflict on feature branch")
    assert proc.returncode == 0


def test_cr_modified_after_decision_policy(hook_repo: Path) -> None:
    root = hook_repo
    target = write_doc(root, "feature", "Upload documents")
    other = write_doc(root, "feature", "Scan uploads")
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    assert (
        main(
            [
                "--repo",
                str(root),
                "cr",
                "new",
                "--title",
                "Raise the upload limit",
                "--scope",
                target,
            ]
        )
        == 0
    )
    cr_id = next(path.stem for path in (root / "changes").rglob("*.md"))
    fill_cr_body(root, cr_id)
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=accepted"]) == 0
    git(root, "add", "-A")
    assert git_commit(root, "accept the CR").returncode == 0

    write_config(
        config_path(root),
        Config(versioning=VersioningSection(on_cr_modified="block")),
    )
    assert main(["--repo", str(root), "cr", "scope", "add", cr_id, other]) == 0
    git(root, "add", "-A")
    proc = git_commit(root, "grow the scope")
    output = hook_output(proc)
    assert proc.returncode != 0
    assert "W-CR-MODIFIED-AFTER-DECISION" in output
    assert "modified after its last decision" in output


def test_cr_modified_after_decision_default_is_warn(hook_repo: Path) -> None:
    root = hook_repo
    target = write_doc(root, "feature", "Upload documents")
    other = write_doc(root, "feature", "Scan uploads")
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    assert (
        main(
            [
                "--repo",
                str(root),
                "cr",
                "new",
                "--title",
                "Raise the upload limit",
                "--scope",
                target,
            ]
        )
        == 0
    )
    cr_id = next(path.stem for path in (root / "changes").rglob("*.md"))
    fill_cr_body(root, cr_id)
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=accepted"]) == 0
    git(root, "add", "-A")
    assert git_commit(root, "accept the CR").returncode == 0

    assert main(["--repo", str(root), "cr", "scope", "add", cr_id, other]) == 0
    git(root, "add", "-A")
    proc = git_commit(root, "grow the scope")
    output = hook_output(proc)
    assert proc.returncode == 0
    assert "W-CR-MODIFIED-AFTER-DECISION" in output


# --------------------------------------------------------------------------
# BOOT-303 / BOOT-128
# --------------------------------------------------------------------------


def test_hook_does_not_block_on_cr_scope_target_edits(hook_repo: Path) -> None:
    """BOOT-303: editing a CR's scope target yields no CR finding."""
    root = hook_repo
    scan = write_doc(root, "feature", "Scan uploads")
    target = write_doc(root, "feature", "Upload documents", [link("relates-to", scan)])
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    assert (
        main(
            [
                "--repo",
                str(root),
                "cr",
                "new",
                "--title",
                "Raise the upload limit",
                "--scope",
                target,
            ]
        )
        == 0
    )
    cr_id = next(path.stem for path in (root / "changes").rglob("*.md"))
    fill_cr_body(root, cr_id)
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=accepted"]) == 0
    git(root, "add", "-A")
    assert git_commit(root, "accept the CR").returncode == 0

    git(root, "checkout", "-b", "implementation")
    body = doc_body(root, target)
    body.write_text(
        body.read_text(encoding="utf-8") + "\nRaise the limit to 200 MB.\n",
        encoding="utf-8",
    )
    git(root, "add", "-A")
    proc = git_commit(root, "implement the CR")
    output = hook_output(proc)
    assert proc.returncode == 0
    assert cr_id not in output
    assert "W-CR" not in output
    assert "E-CR" not in output


def test_hook_never_blocks_on_drift(hook_repo: Path) -> None:
    """BOOT-128: drift (``W-CR-BASE-DRIFT``) is reported, never aborts."""
    root = hook_repo
    target = write_doc(root, "feature", "Upload documents")
    git(root, "add", "-A")
    assert git_commit(root, "initial").returncode == 0

    assert (
        main(
            [
                "--repo",
                str(root),
                "cr",
                "new",
                "--title",
                "Raise the upload limit",
                "--scope",
                target,
            ]
        )
        == 0
    )
    cr_id = next(path.stem for path in (root / "changes").rglob("*.md"))
    fill_cr_body(root, cr_id)
    assert main(["--repo", str(root), "cr", "set", cr_id, "status=accepted"]) == 0
    git(root, "add", "-A")
    assert git_commit(root, "accept the CR").returncode == 0

    git(root, "checkout", "-b", "other-work")
    body = doc_body(root, target)
    body.write_text(
        body.read_text(encoding="utf-8") + "\nSomeone else changed this.\n",
        encoding="utf-8",
    )
    git(root, "add", "-A")
    assert git_commit(root, "change the scope target").returncode == 0
    git(root, "checkout", "main")
    git(root, "merge", "other-work", "-m", "merge the change")

    git(root, "checkout", "-b", "cr-work")
    other = write_doc(root, "feature", "Scan uploads")
    git(root, "add", "-A")
    proc = git_commit(root, "unrelated work on the CR branch")
    output = hook_output(proc)
    assert proc.returncode == 0
    assert "W-CR-BASE-DRIFT" in output
    assert other


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def test_hook_pre_commit_via_cli(hook_repo: Path) -> None:
    assert main(["--repo", str(hook_repo), "hook", "pre-commit"]) == 0


def test_hook_without_subcommand_is_usage_error(hook_repo: Path) -> None:
    assert main(["--repo", str(hook_repo), "hook"]) == 2


def test_hook_hidden_from_help() -> None:
    import re

    from gregraph.cli.main import build_parser

    help_text = build_parser().format_help()
    assert re.search(r"(?m)^\s*hook\s", help_text) is None


# --------------------------------------------------------------------------
# degraded mode
# --------------------------------------------------------------------------


def test_degraded_sync_bumps(tmp_repo: Path) -> None:
    """M3 acceptance: ``sync`` bumps versions in degraded (no-Git) mode."""
    if (tmp_repo / ".git").exists():
        pytest.skip("degraded mode needs the no-git tmp_repo")
    if importlib.util.find_spec("gregraph.cli.commands.sync") is None:
        pytest.skip("sync lands in S18")
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    doc_id = write_doc(tmp_repo, "feature", "Upload documents")
    body = doc_body(tmp_repo, doc_id)
    body.write_text(body.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    assert main(["--repo", str(tmp_repo), "sync"]) == 0
    sidecar = read_sidecar(doc_sidecar(tmp_repo, doc_id), Document)
    assert sidecar.version == 2
