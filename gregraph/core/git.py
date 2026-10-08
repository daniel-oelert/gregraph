"""GitAdapter / NullGitAdapter (spec §12.1, §12.2, §12.4, §12.5, §16.1).

All Git access shells out to the ``git`` executable via ``subprocess.run`` with
explicit argument lists, ``cwd`` = repository root, ``LC_ALL=C``, and a 30-second
timeout. No Git library dependency (spec §12.1, §16.3). If ``git`` is not on
``PATH`` or the root is not a repository, the adapter is replaced by
``NullGitAdapter`` and the workspace is in degraded mode.

Degraded-mode notes are data, never prints: :class:`NoteSuppressor` yields the
``note: not a git repository — <feature> unavailable`` line at most once per
invocation (spec §12.1). Branching strategy stays neutral (spec §12.5): the
adapter only answers "does this path differ from ``<ref>``".
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from gregraph.core.models import Identity

_TIMEOUT_SECONDS: Final = 30
_DEGRADED_NOTE: Final = "note: not a git repository — {feature} unavailable"
_WHOLE_TREE: Final = Path()


class NoteSuppressor:
    """Hands out the degraded-mode note at most once per instance (spec §12.1).

    One instance per invocation gives the "once per invocation" semantics;
    callers emit whatever :meth:`take` returns, core never prints. ``None``
    means "stay silent".
    """

    def __init__(self) -> None:
        self._emitted = False

    def take(self, feature: str) -> str | None:
        """Note line naming ``feature`` on first call, ``None`` afterwards."""
        if self._emitted:
            return None
        self._emitted = True
        return _DEGRADED_NOTE.format(feature=feature)


class GitAdapter:
    """Subprocess adapter over the ``git`` executable (spec §12.1)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _run(
        self, *args: str, check: bool = True, stdin: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=self._root,
            env={**os.environ, "LC_ALL": "C"},
            capture_output=True,
            input=stdin,
            timeout=_TIMEOUT_SECONDS,
            check=check,
        )

    @staticmethod
    def _paths(raw: bytes) -> list[Path]:
        return sorted(Path(os.fsdecode(item)) for item in raw.split(b"\0") if item)

    def is_repo(self) -> bool:
        """Whether the working directory root is a Git repository."""
        try:
            result = self._run("rev-parse", "--is-inside-work-tree", check=False)
        except FileNotFoundError:
            return False
        return result.returncode == 0 and result.stdout.strip() == b"true"

    def root(self) -> Path:
        """Absolute path of the repository root.

        Falls back to the bound root when there is no repository above it.
        """
        result = self._run("rev-parse", "--show-toplevel", check=False)
        if result.returncode != 0:
            return self._root.resolve()
        return Path(os.fsdecode(result.stdout.strip())).resolve()

    def identity(self) -> Identity | None:
        """Identity from ``git config user.name/email``, or ``None`` (spec §12.2)."""
        name = self._config("user.name")
        email = self._config("user.email")
        if name is None or email is None:
            return None
        return Identity(name=name, email=email)

    def _config(self, key: str) -> str | None:
        result = self._run("config", "--get", key, check=False)
        if result.returncode != 0:
            return None
        value = os.fsdecode(result.stdout).strip()
        return value or None

    def current_branch(self) -> str | None:
        """Current branch name, or ``None`` when detached/unborn."""
        result = self._run("rev-parse", "--abbrev-ref", "HEAD", check=False)
        if result.returncode != 0:
            return None
        name = os.fsdecode(result.stdout).strip()
        return None if name == "HEAD" else name

    def branch_exists(self, name: str) -> bool:
        """Whether a local branch called ``name`` exists."""
        result = self._run(
            "show-ref", "--verify", "--quiet", f"refs/heads/{name}", check=False
        )
        return result.returncode == 0

    def staged_paths(self) -> list[Path]:
        """Repository-relative paths staged for commit."""
        result = self._run("diff", "--cached", "--name-only", "-z")
        return self._paths(result.stdout)

    def changed_paths(self) -> list[Path]:
        """Repository-relative paths changed vs HEAD (staged + unstaged)."""
        staged = self._run("diff", "--cached", "--name-only", "-z")
        unstaged = self._run("diff", "--name-only", "-z")
        changed = set(self._paths(staged.stdout)) | set(self._paths(unstaged.stdout))
        return sorted(changed)

    def untracked_paths(self) -> list[Path]:
        """Repository-relative untracked paths (``.gitignore`` applies)."""
        result = self._run("ls-files", "--others", "--exclude-standard", "-z")
        return self._paths(result.stdout)

    def differs_from_ref(self, path: Path, ref: str) -> bool:
        """Whether ``path`` differs from its state at ``ref`` (spec §12.5).

        Differs when exactly one side exists, or when the working-tree bytes
        differ from the blob at ``ref``.
        """
        at_ref = self.file_at(ref, path)
        local = self._root / path
        if not local.is_file():
            return at_ref is not None
        return local.read_bytes() != at_ref

    def is_tracked(self, path: Path) -> bool:
        """Whether ``path`` is tracked by Git."""
        result = self._run(
            "ls-files", "--error-unmatch", "--", path.as_posix(), check=False
        )
        return result.returncode == 0

    def file_at(self, ref: str, path: Path) -> bytes | None:
        """File contents at ``ref`` (``git show <ref>:<path>``), or ``None``."""
        result = self._run("show", f"{ref}:{path.as_posix()}", check=False)
        if result.returncode != 0:
            return None
        return result.stdout

    def files_at(self, ref: str, prefix: Path = _WHOLE_TREE) -> dict[Path, bytes]:
        """All files under ``prefix`` at ``ref`` (baseline view for CR checks, §9.6).

        ``git ls-tree -r`` lists the tree and one ``git cat-file --batch``
        process reads every blob. Keys are repository-relative. ``prefix``
        defaults to the whole tree. Raises ``subprocess.CalledProcessError``
        when ``ref`` does not resolve.
        """
        args = ["ls-tree", "-r", "-z", ref, "--"]
        if prefix != _WHOLE_TREE:
            args.append(prefix.as_posix())
        entries: list[tuple[Path, bytes]] = []
        for record in self._run(*args).stdout.split(b"\0"):
            if not record:
                continue
            meta, _, name = record.partition(b"\t")
            _mode, kind, sha = meta.split()
            if kind != b"blob":
                continue
            entries.append((Path(os.fsdecode(name)), sha))
        if not entries:
            return {}
        batch = self._run(
            "cat-file",
            "--batch",
            stdin=b"".join(sha + b"\n" for _path, sha in entries),
        )
        data = batch.stdout
        position = 0
        result: dict[Path, bytes] = {}
        for path, _sha in entries:
            end = data.index(b"\n", position)
            header = data[position:end].split()
            position = end + 1
            if header[1] == b"missing":
                continue
            size = int(header[2])
            result[path] = data[position : position + size]
            position += size + 1
        return result

    def stage(self, paths: Sequence[Path]) -> None:
        """Stage ``paths``."""
        if not paths:
            return
        self._run("add", "--", *(path.as_posix() for path in paths))

    def tag_annotated(self, name: str, message: str) -> None:
        """Create an annotated tag (baselines, spec §12.4)."""
        self._run("tag", "--annotate", name, "--message", message)

    def tags(self, prefix: str = "") -> list[str]:
        """Tag names starting with ``prefix``, sorted."""
        result = self._run("tag", "--list")
        names = (os.fsdecode(item) for item in result.stdout.splitlines())
        return sorted(name for name in names if name.startswith(prefix))

    def head_sha(self) -> str | None:
        """SHA of ``HEAD``, or ``None`` when there is no commit."""
        result = self._run("rev-parse", "HEAD", check=False)
        if result.returncode != 0:
            return None
        return os.fsdecode(result.stdout).strip() or None


class NullGitAdapter(GitAdapter):
    """Degraded-mode stand-in when Git is unavailable (spec §12.1).

    Every command works in degraded mode; each method returns empty/None/False
    and the mutators are no-ops. Features that need Git hand out the
    ``note: not a git repository — <feature> unavailable`` line via a
    :class:`NoteSuppressor` (spec §12.1).
    """

    def __init__(self) -> None:
        super().__init__(_WHOLE_TREE)

    def is_repo(self) -> bool:
        return False

    def root(self) -> Path:
        return Path()

    def identity(self) -> Identity | None:
        return None

    def current_branch(self) -> str | None:
        return None

    def branch_exists(self, name: str) -> bool:
        return False

    def staged_paths(self) -> list[Path]:
        return []

    def changed_paths(self) -> list[Path]:
        return []

    def untracked_paths(self) -> list[Path]:
        return []

    def differs_from_ref(self, path: Path, ref: str) -> bool:
        return False

    def is_tracked(self, path: Path) -> bool:
        return False

    def file_at(self, ref: str, path: Path) -> bytes | None:
        return None

    def files_at(self, ref: str, prefix: Path = _WHOLE_TREE) -> dict[Path, bytes]:
        return {}

    def stage(self, paths: Sequence[Path]) -> None:
        return None

    def tag_annotated(self, name: str, message: str) -> None:
        return None

    def tags(self, prefix: str = "") -> list[str]:
        return []

    def head_sha(self) -> str | None:
        return None
