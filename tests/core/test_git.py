"""Tests for ``gregraph.core.git`` (spec §12.1, §12.2, §12.4, §12.5).

Real ``git`` in ``tmp_path`` fixtures; the test scaffolding may shell out to
``git`` directly (spec §17). Every ``GitAdapter`` method, the ``NullGitAdapter``
degraded mode and the note suppression helper are covered.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from gregraph.core.git import GitAdapter, NoteSuppressor, NullGitAdapter
from gregraph.core.models import Identity


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, "LC_ALL": "C"},
        capture_output=True,
        check=True,
        text=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Git repository with identity and one commit of managed-looking files."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test Author")
    _git(tmp_path, "config", "user.email", "test.author@example.org")
    (tmp_path / "documents").mkdir()
    (tmp_path / "changes").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "documents" / "A.md").write_text("A body\n", encoding="utf-8")
    (tmp_path / "changes" / "CR-1.md").write_text("CR body\n", encoding="utf-8")
    (tmp_path / "changes" / "CR-1.json").write_bytes(b'{"id": "RE-000001"}\n')
    (tmp_path / "assets" / "blob.bin").write_bytes(b"\x00\x01\xfe\xff")
    _commit_all(tmp_path, "init")
    return tmp_path


@pytest.fixture
def unborn(tmp_path: Path) -> Path:
    """Initialised repository with identity but no commit yet."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test Author")
    _git(tmp_path, "config", "user.email", "test.author@example.org")
    return tmp_path


class TestIsRepo:
    def test_true_in_repository(self, repo: Path) -> None:
        assert GitAdapter(repo).is_repo() is True

    def test_false_outside_repository(self, tmp_path: Path) -> None:
        assert GitAdapter(tmp_path).is_repo() is False


class TestRoot:
    def test_repository_root(self, repo: Path) -> None:
        assert GitAdapter(repo).root() == repo.resolve()

    def test_falls_back_to_bound_root(self, tmp_path: Path) -> None:
        assert GitAdapter(tmp_path).root() == tmp_path.resolve()


class TestIdentity:
    def test_reads_configured_identity(self, repo: Path) -> None:
        identity = GitAdapter(repo).identity()
        assert identity == Identity(name="Test Author", email="test.author@example.org")

    def test_none_when_unconfigured(self, unborn: Path) -> None:
        _git(unborn, "config", "user.name", "")
        _git(unborn, "config", "user.email", "")
        assert GitAdapter(unborn).identity() is None

    def test_none_when_email_missing(self, unborn: Path) -> None:
        _git(unborn, "config", "user.email", "")
        assert GitAdapter(unborn).identity() is None


class TestCurrentBranch:
    def test_branch_name(self, repo: Path) -> None:
        assert GitAdapter(repo).current_branch() == "main"

    def test_none_when_unborn(self, unborn: Path) -> None:
        assert GitAdapter(unborn).current_branch() is None

    def test_none_when_detached(self, repo: Path) -> None:
        _git(repo, "checkout", "--detach")
        assert GitAdapter(repo).current_branch() is None


class TestBranchExists:
    def test_existing_branch(self, repo: Path) -> None:
        assert GitAdapter(repo).branch_exists("main") is True

    def test_missing_branch(self, repo: Path) -> None:
        assert GitAdapter(repo).branch_exists("nope") is False

    def test_created_branch(self, repo: Path) -> None:
        _git(repo, "branch", "feature/x")
        assert GitAdapter(repo).branch_exists("feature/x") is True


class TestStagedPaths:
    def test_empty_when_clean(self, repo: Path) -> None:
        assert GitAdapter(repo).staged_paths() == []

    def test_staged_files(self, repo: Path) -> None:
        (repo / "documents" / "A.md").write_text("changed\n", encoding="utf-8")
        (repo / "documents" / "B.md").write_text("B body\n", encoding="utf-8")
        _git(repo, "add", "documents/A.md", "documents/B.md")
        assert GitAdapter(repo).staged_paths() == [
            Path("documents/A.md"),
            Path("documents/B.md"),
        ]

    def test_empty_after_commit(self, repo: Path) -> None:
        (repo / "documents" / "B.md").write_text("B body\n", encoding="utf-8")
        _commit_all(repo, "add B")
        assert GitAdapter(repo).staged_paths() == []


class TestChangedPaths:
    def test_empty_when_clean(self, repo: Path) -> None:
        assert GitAdapter(repo).changed_paths() == []

    def test_unstaged_change(self, repo: Path) -> None:
        (repo / "documents" / "A.md").write_text("changed\n", encoding="utf-8")
        assert GitAdapter(repo).changed_paths() == [Path("documents/A.md")]

    def test_staged_and_unstaged_deduplicated(self, repo: Path) -> None:
        (repo / "documents" / "A.md").write_text("staged\n", encoding="utf-8")
        _git(repo, "add", "documents/A.md")
        (repo / "documents" / "A.md").write_text("unstaged too\n", encoding="utf-8")
        (repo / "documents" / "B.md").write_text("B body\n", encoding="utf-8")
        _git(repo, "add", "documents/B.md")
        assert GitAdapter(repo).changed_paths() == [
            Path("documents/A.md"),
            Path("documents/B.md"),
        ]

    def test_deleted_file(self, repo: Path) -> None:
        (repo / "documents" / "A.md").unlink()
        assert GitAdapter(repo).changed_paths() == [Path("documents/A.md")]


class TestUntrackedPaths:
    def test_empty_when_clean(self, repo: Path) -> None:
        assert GitAdapter(repo).untracked_paths() == []

    def test_untracked_file(self, repo: Path) -> None:
        (repo / "documents" / "B.md").write_text("B body\n", encoding="utf-8")
        assert GitAdapter(repo).untracked_paths() == [Path("documents/B.md")]

    def test_excludes_ignored(self, repo: Path) -> None:
        (repo / ".gitignore").write_text("scratch/\n", encoding="utf-8")
        (repo / "scratch").mkdir()
        (repo / "scratch" / "notes.md").write_text("x\n", encoding="utf-8")
        assert GitAdapter(repo).untracked_paths() == [Path(".gitignore")]


class TestDiffersFromRef:
    def test_false_when_unchanged(self, repo: Path) -> None:
        adapter = GitAdapter(repo)
        assert adapter.differs_from_ref(Path("documents/A.md"), "HEAD") is False

    def test_true_when_modified(self, repo: Path) -> None:
        (repo / "documents" / "A.md").write_text("changed\n", encoding="utf-8")
        assert GitAdapter(repo).differs_from_ref(Path("documents/A.md"), "HEAD") is True

    def test_true_when_missing_at_ref(self, repo: Path) -> None:
        (repo / "documents" / "B.md").write_text("B body\n", encoding="utf-8")
        assert GitAdapter(repo).differs_from_ref(Path("documents/B.md"), "HEAD") is True

    def test_true_when_missing_in_worktree(self, repo: Path) -> None:
        (repo / "documents" / "A.md").unlink()
        adapter = GitAdapter(repo)
        assert adapter.differs_from_ref(Path("documents/A.md"), "HEAD") is True

    def test_false_when_missing_everywhere(self, repo: Path) -> None:
        adapter = GitAdapter(repo)
        assert adapter.differs_from_ref(Path("documents/B.md"), "HEAD") is False

    def test_against_other_branch(self, repo: Path) -> None:
        _git(repo, "branch", "baseline")
        (repo / "documents" / "A.md").write_text("changed\n", encoding="utf-8")
        _commit_all(repo, "change A")
        adapter = GitAdapter(repo)
        assert adapter.differs_from_ref(Path("documents/A.md"), "baseline") is True
        assert adapter.differs_from_ref(Path("documents/A.md"), "HEAD") is False


class TestIsTracked:
    def test_tracked_file(self, repo: Path) -> None:
        assert GitAdapter(repo).is_tracked(Path("documents/A.md")) is True

    def test_untracked_file(self, repo: Path) -> None:
        (repo / "documents" / "B.md").write_text("B body\n", encoding="utf-8")
        assert GitAdapter(repo).is_tracked(Path("documents/B.md")) is False


class TestFileAt:
    def test_returns_contents(self, repo: Path) -> None:
        assert GitAdapter(repo).file_at("HEAD", Path("documents/A.md")) == b"A body\n"

    def test_returns_binary_contents(self, repo: Path) -> None:
        assert GitAdapter(repo).file_at("HEAD", Path("assets/blob.bin")) == (
            b"\x00\x01\xfe\xff"
        )

    def test_none_for_missing_path(self, repo: Path) -> None:
        assert GitAdapter(repo).file_at("HEAD", Path("documents/B.md")) is None

    def test_none_for_missing_ref(self, repo: Path) -> None:
        assert GitAdapter(repo).file_at("no-such-ref", Path("documents/A.md")) is None


class TestFilesAt:
    def test_whole_tree(self, repo: Path) -> None:
        files = GitAdapter(repo).files_at("HEAD")
        assert set(files) == {
            Path("documents/A.md"),
            Path("changes/CR-1.md"),
            Path("changes/CR-1.json"),
            Path("assets/blob.bin"),
        }
        assert files[Path("documents/A.md")] == b"A body\n"
        assert files[Path("assets/blob.bin")] == b"\x00\x01\xfe\xff"

    def test_prefix_scopes_the_listing(self, repo: Path) -> None:
        files = GitAdapter(repo).files_at("HEAD", Path("changes"))
        assert set(files) == {Path("changes/CR-1.md"), Path("changes/CR-1.json")}

    def test_loads_baseline_sidecars(self, repo: Path) -> None:
        files = GitAdapter(repo).files_at("HEAD", Path("changes"))
        assert files[Path("changes/CR-1.json")] == b'{"id": "RE-000001"}\n'

    def test_empty_for_missing_prefix(self, repo: Path) -> None:
        assert GitAdapter(repo).files_at("HEAD", Path("glossary")) == {}

    def test_reads_a_branch_view(self, repo: Path) -> None:
        _git(repo, "branch", "baseline")
        (repo / "changes" / "CR-1.json").write_bytes(b'{"id": "RE-000002"}\n')
        _commit_all(repo, "edit sidecar")
        files = GitAdapter(repo).files_at("baseline", Path("changes"))
        assert files[Path("changes/CR-1.json")] == b'{"id": "RE-000001"}\n'

    def test_raises_for_missing_ref(self, repo: Path) -> None:
        with pytest.raises(subprocess.CalledProcessError):
            GitAdapter(repo).files_at("no-such-ref")


class TestStage:
    def test_stages_paths(self, repo: Path) -> None:
        (repo / "documents" / "A.md").write_text("changed\n", encoding="utf-8")
        (repo / "documents" / "B.md").write_text("B body\n", encoding="utf-8")
        GitAdapter(repo).stage([Path("documents/A.md"), Path("documents/B.md")])
        assert GitAdapter(repo).staged_paths() == [
            Path("documents/A.md"),
            Path("documents/B.md"),
        ]

    def test_empty_sequence_is_noop(self, repo: Path) -> None:
        GitAdapter(repo).stage([])
        assert GitAdapter(repo).staged_paths() == []


class TestTagAnnotated:
    def test_creates_annotated_tag(self, repo: Path) -> None:
        GitAdapter(repo).tag_annotated("baseline/v1", "manifest")
        assert GitAdapter(repo).tags("baseline/") == ["baseline/v1"]
        tagged = _git(repo, "cat-file", "-t", "refs/tags/baseline/v1")
        assert tagged.stdout.strip() == "tag"

    def test_refuses_duplicate_tag(self, repo: Path) -> None:
        adapter = GitAdapter(repo)
        adapter.tag_annotated("baseline/v1", "manifest")
        with pytest.raises(subprocess.CalledProcessError):
            adapter.tag_annotated("baseline/v1", "again")


class TestTags:
    def test_empty_without_tags(self, repo: Path) -> None:
        assert GitAdapter(repo).tags("") == []

    def test_lists_and_filters_by_prefix(self, repo: Path) -> None:
        adapter = GitAdapter(repo)
        adapter.tag_annotated("baseline/v1", "manifest")
        adapter.tag_annotated("baseline/v2", "manifest")
        adapter.tag_annotated("v1.0.0", "release")
        assert adapter.tags("") == ["baseline/v1", "baseline/v2", "v1.0.0"]
        assert adapter.tags("baseline/") == ["baseline/v1", "baseline/v2"]


class TestHeadSha:
    def test_none_without_commits(self, unborn: Path) -> None:
        assert GitAdapter(unborn).head_sha() is None

    def test_matches_rev_parse(self, repo: Path) -> None:
        expected = _git(repo, "rev-parse", "HEAD").stdout.strip()
        assert GitAdapter(repo).head_sha() == expected


class TestNullGitAdapter:
    def test_is_repo_false(self) -> None:
        assert NullGitAdapter().is_repo() is False

    def test_root_empty(self) -> None:
        assert NullGitAdapter().root() == Path()

    def test_identity_none(self) -> None:
        assert NullGitAdapter().identity() is None

    def test_current_branch_none(self) -> None:
        assert NullGitAdapter().current_branch() is None

    def test_branch_exists_false(self) -> None:
        assert NullGitAdapter().branch_exists("main") is False

    def test_path_lists_empty(self) -> None:
        adapter = NullGitAdapter()
        assert adapter.staged_paths() == []
        assert adapter.changed_paths() == []
        assert adapter.untracked_paths() == []

    def test_differs_from_ref_false(self) -> None:
        assert NullGitAdapter().differs_from_ref(Path("a.md"), "HEAD") is False

    def test_is_tracked_false(self) -> None:
        assert NullGitAdapter().is_tracked(Path("a.md")) is False

    def test_file_at_none(self) -> None:
        assert NullGitAdapter().file_at("HEAD", Path("a.md")) is None

    def test_files_at_empty(self) -> None:
        assert NullGitAdapter().files_at("HEAD") == {}

    def test_stage_noop(self) -> None:
        NullGitAdapter().stage([Path("a.md")])

    def test_tag_annotated_noop(self) -> None:
        NullGitAdapter().tag_annotated("baseline/v1", "manifest")

    def test_tags_empty(self) -> None:
        assert NullGitAdapter().tags("") == []

    def test_head_sha_none(self) -> None:
        assert NullGitAdapter().head_sha() is None


class TestNoteSuppressor:
    def test_first_take_returns_note(self) -> None:
        note = NoteSuppressor().take("baseline create")
        assert note == "note: not a git repository — baseline create unavailable"

    def test_subsequent_takes_are_suppressed(self) -> None:
        suppressor = NoteSuppressor()
        assert suppressor.take("baseline create") is not None
        assert suppressor.take("cr check") is None
        assert suppressor.take("sync") is None

    def test_each_instance_notes_once(self) -> None:
        assert NoteSuppressor().take("sync") is not None
        assert NoteSuppressor().take("sync") is not None
