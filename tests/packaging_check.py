"""Packaging verification for ``gregraph-core`` and ``gregraph-cli`` (spec §16.4).

Dedicated CI step, not a unit test (it builds wheels and creates virtual
environments). It runs from the repository root:

    python tests/packaging_check.py [--no-build-isolation] [--wheel-dir DIR]

Checks, in order:

1. Build both wheels (``pip wheel --no-deps``), or reuse ``--wheel-dir``.
2. Wheel contract: the wheels share no archive member and each provides exactly
   its share of the ``gregraph`` namespace (see ``wheel_contract_violations``).
3. Core-only: a fresh venv with only ``gregraph-core`` imports ``gregraph.core``
   and ``gregraph.__version__``, ships the 14 built-in templates, has no
   ``gregraph.cli`` and no ``gregraph`` console script.
4. Both: a fresh venv with both wheels runs ``gregraph --version`` and
   ``python -m gregraph --version`` reporting the release version, and records
   the exact ``gregraph-core==<version>`` requirement.

Subprocesses never inherit ``PYTHONPATH``/``PYTHONHOME`` and the in-venv Python
runs with ``-I``, so the editable checkout cannot leak into a clean install.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Collection, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "packages" / "core"
CLI_DIR = REPO_ROOT / "packages" / "cli"
TEMPLATE_COUNT = 14

CORE_REQUIRED = (
    "gregraph/__init__.py",
    "gregraph/core/operations.py",
    "gregraph/builtin_templates/term/v1/template.json",
)
CORE_FORBIDDEN_PREFIXES = ("gregraph/cli/", "gregraph/__main__.py")
CLI_REQUIRED = ("gregraph/__main__.py", "gregraph/cli/main.py")
CLI_FORBIDDEN_PREFIXES = (
    "gregraph/__init__.py",
    "gregraph/core/",
    "gregraph/builtin_templates/",
)


def find_overlaps(wheels: Sequence[Path]) -> list[str]:
    """Return archive members present in more than one wheel, sorted."""
    seen: dict[str, int] = {}
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            for name in set(archive.namelist()):
                seen[name] = seen.get(name, 0) + 1
    return sorted(name for name, count in seen.items() if count > 1)


def wheel_contract_violations(
    core_names: Collection[str], cli_names: Collection[str]
) -> list[str]:
    """Return human-readable violations of the core/cli wheel split (§16.1)."""
    violations: list[str] = []
    for name in CORE_REQUIRED:
        if name not in core_names:
            violations.append(f"core wheel lacks {name}")
    for name in CLI_REQUIRED:
        if name not in cli_names:
            violations.append(f"cli wheel lacks {name}")
    for name in cli_names:
        if name.startswith(CLI_FORBIDDEN_PREFIXES):
            violations.append(f"cli wheel must not contain {name}")
    for name in core_names:
        if name.startswith(CORE_FORBIDDEN_PREFIXES):
            violations.append(f"core wheel must not contain {name}")
    return violations


def _archive_names(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def release_version(pyproject: Path = CORE_DIR / "pyproject.toml") -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version: str = data["project"]["version"]
    return version


def venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_script(venv: Path, name: str) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def _run(args: Sequence[str | Path], cwd: Path, what: str) -> str:
    result = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"FAILED: {what} (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def build_wheels(out: Path, *, no_build_isolation: bool) -> tuple[Path, Path]:
    args: list[str | Path] = [sys.executable, "-m", "pip", "wheel", "--no-deps"]
    if no_build_isolation:
        args.append("--no-build-isolation")
    args += [CORE_DIR, CLI_DIR, "-w", out]
    _run(args, REPO_ROOT, "build wheels")
    return build_wheels_from(out)


def _make_venv(path: Path) -> Path:
    _run([sys.executable, "-m", "venv", path], REPO_ROOT, f"create venv {path}")
    return path


CORE_SNIPPET = """
import importlib.metadata as md
import importlib.resources as res
import importlib.util
import gregraph
import gregraph.core
assert gregraph.__version__ == {version!r}, gregraph.__version__
assert md.version("gregraph-core") == {version!r}
assert importlib.util.find_spec("gregraph.cli") is None, "cli leaked"
templates = res.files("gregraph").joinpath("builtin_templates")
names = sorted(p.name for p in templates.iterdir() if p.is_dir())
assert len(names) == {count}, names
for name in names:
    assert templates.joinpath(name, "v1", "template.json").is_file(), name
print("core ok", len(names))
"""

BOTH_SNIPPET = """
import importlib.metadata as md
import importlib.util
import gregraph
import gregraph.core
import gregraph.cli.main
assert gregraph.__version__ == {version!r}
assert md.version("gregraph-cli") == {version!r}
assert md.version("gregraph-core") == {version!r}
requires = md.requires("gregraph-cli") or []
assert "gregraph-core=={version}" in [r.replace(" ", "") for r in requires], requires
print("both ok")
"""


def check_core_only(core_wheel: Path, work: Path, version: str) -> None:
    venv = _make_venv(work / "core-only")
    _run(
        [venv_python(venv), "-m", "pip", "install", "--quiet", core_wheel],
        work,
        "install core-only wheel",
    )
    _run(
        [
            venv_python(venv),
            "-I",
            "-c",
            CORE_SNIPPET.format(version=version, count=TEMPLATE_COUNT),
        ],
        work,
        "core-only import checks",
    )
    if venv_script(venv, "gregraph").exists():
        raise SystemExit("FAILED: core-only install provides a gregraph script")
    result = subprocess.run(
        [str(venv_python(venv)), "-I", "-m", "gregraph", "--version"],
        cwd=work,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        raise SystemExit("FAILED: core-only install runs python -m gregraph")
    print("core-only: ok")


def check_both(core_wheel: Path, cli_wheel: Path, work: Path, version: str) -> None:
    venv = _make_venv(work / "both")
    _run(
        [venv_python(venv), "-m", "pip", "install", "--quiet", core_wheel, cli_wheel],
        work,
        "install both wheels",
    )
    _run(
        [venv_python(venv), "-I", "-c", BOTH_SNIPPET.format(version=version)],
        work,
        "both-wheel import checks",
    )
    for command in (
        [venv_script(venv, "gregraph"), "--version"],
        [venv_python(venv), "-I", "-m", "gregraph", "--version"],
    ):
        out = _run(command, work, f"run {command[0]} --version").strip()
        if out != version:
            raise SystemExit(f"FAILED: {command[0]} --version printed {out!r}")
    print("both: ok")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-build-isolation", action="store_true")
    parser.add_argument("--wheel-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    version = release_version()
    with tempfile.TemporaryDirectory(prefix="gregraph-pkg-") as tmp:
        work = Path(tmp)
        if args.wheel_dir is None:
            wheels_dir = work / "dist"
            wheels_dir.mkdir()
            core_wheel, cli_wheel = build_wheels(
                wheels_dir, no_build_isolation=args.no_build_isolation
            )
        else:
            core_wheel, cli_wheel = build_wheels_from(args.wheel_dir)
        print(f"wheels: {core_wheel.name}, {cli_wheel.name}")

        overlaps = find_overlaps([core_wheel, cli_wheel])
        if overlaps:
            raise SystemExit(f"FAILED: overlapping wheel files: {overlaps}")
        violations = wheel_contract_violations(
            _archive_names(core_wheel), _archive_names(cli_wheel)
        )
        if violations:
            raise SystemExit("FAILED: " + "; ".join(violations))
        print("wheel contract: ok")

        check_core_only(core_wheel, work, version)
        check_both(core_wheel, cli_wheel, work, version)
    print(f"packaging check passed for {version}")
    return 0


def build_wheels_from(directory: Path) -> tuple[Path, Path]:
    core = sorted(directory.glob("gregraph_core-*.whl"))
    cli = sorted(directory.glob("gregraph_cli-*.whl"))
    if len(core) != 1 or len(cli) != 1:
        raise SystemExit(f"expected one wheel per distribution in {directory}")
    return core[0], cli[0]


if __name__ == "__main__":
    raise SystemExit(main())
