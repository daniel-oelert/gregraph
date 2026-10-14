"""Packaging verification for the three gregraph distributions (spec §16.4, §21.2).

Dedicated CI step, not a unit test (it builds wheels and creates virtual
environments). It runs from the repository root:

    python tests/packaging_check.py [--no-build-isolation] [--wheel-dir DIR]

Checks, in order:

1. Build the three wheels (``pip wheel --no-deps``), or reuse ``--wheel-dir``.
2. Wheel contract: the wheels share no archive member and each provides exactly
   its share of the ``gregraph`` namespace (see ``wheel_contract_violations``);
   the web UI wheel declares its ``gregraph.serve`` entry point.
3. Static bundle: ``gregraph/webui/static/index.html`` exists and every local
   ``src``/``href`` in it, and every ``url()`` in its stylesheets, resolves to a
   member of the web UI wheel (see ``static_asset_violations``).
4. Core-only: a fresh venv with only ``gregraph-core`` imports ``gregraph.core``
   and ``gregraph.__version__``, ships the 14 built-in templates, has no
   ``gregraph.cli`` and no ``gregraph`` console script.
5. Core + CLI: a fresh venv runs ``gregraph --version`` and
   ``python -m gregraph --version`` reporting the release version, and records
   the exact ``gregraph-core==<version>`` requirement. ``serve`` is absent from
   help and rejected as a usage error.
6. All three: a fresh venv with every wheel exposes ``gregraph serve --help``,
   the ``gregraph.serve`` entry point, and the static bundle; ``--help`` does
   not import the web UI package or FastAPI; an installed server starts on a
   free loopback port in an initialised repository and serves ``/`` and every
   asset it references.
7. Optional dependencies missing: a fresh venv with core and CLI (with their
   dependencies) and the web UI wheel installed ``--no-deps`` runs
   ``gregraph --help`` successfully, and ``gregraph serve`` fails with exit 3
   and a message naming ``gregraph-webui``.

Subprocesses never inherit ``PYTHONPATH``/``PYTHONHOME`` and the in-venv Python
runs with ``-I``, so the editable checkout cannot leak into a clean install.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Collection, Sequence
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "packages" / "core"
CLI_DIR = REPO_ROOT / "packages" / "cli"
WEBUI_DIR = REPO_ROOT / "packages" / "webui"
TEMPLATE_COUNT = 14
SERVE_EXIT_ENV = 3
STATIC_PREFIX = "gregraph/webui/static/"

CORE_REQUIRED = (
    "gregraph/__init__.py",
    "gregraph/core/operations.py",
    "gregraph/builtin_templates/term/v1/template.json",
)
CORE_FORBIDDEN_PREFIXES = ("gregraph/cli/", "gregraph/__main__.py", "gregraph/webui/")
CLI_REQUIRED = ("gregraph/__main__.py", "gregraph/cli/main.py")
CLI_FORBIDDEN_PREFIXES = (
    "gregraph/__init__.py",
    "gregraph/core/",
    "gregraph/builtin_templates/",
    "gregraph/webui/",
)
WEBUI_REQUIRED = (
    "gregraph/webui/__init__.py",
    "gregraph/webui/launch.py",
    "gregraph/webui/static/index.html",
)
WEBUI_FORBIDDEN_PREFIXES = (
    "gregraph/__init__.py",
    "gregraph/__main__.py",
    "gregraph/core/",
    "gregraph/cli/",
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
    core_names: Collection[str],
    cli_names: Collection[str],
    webui_names: Collection[str] | None = None,
) -> list[str]:
    """Return human-readable violations of the wheel split (§16.1, §16.4).

    ``webui_names`` is optional so the two-wheel contract remains checkable on
    its own; the three-wheel check always passes it.
    """
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
    if webui_names is not None:
        for name in WEBUI_REQUIRED:
            if name not in webui_names:
                violations.append(f"webui wheel lacks {name}")
        for name in webui_names:
            if name.startswith(WEBUI_FORBIDDEN_PREFIXES):
                violations.append(f"webui wheel must not contain {name}")
    return violations


class _ReferenceParser(HTMLParser):
    """Collects ``src``/``href`` attributes of the tags that load assets."""

    _ATTRIBUTE_BY_TAG = {"script": "src", "link": "href", "img": "src"}

    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attribute = self._ATTRIBUTE_BY_TAG.get(tag)
        if attribute is None:
            return
        for name, value in attrs:
            if name == attribute and value:
                self.references.append(value)


_CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'"\)\s]+)\1\s*\)""")


def _is_local(reference: str) -> bool:
    parts = urlsplit(reference)
    if parts.scheme or reference.startswith(("//", "#", "data:")):
        return False
    return bool(parts.path)


def _member_for(base_dir: str, reference: str) -> str:
    """Archive member a local reference points at (``/x`` is root-relative)."""
    path = urlsplit(reference).path
    if path.startswith("/"):
        relative = path.lstrip("/")
    else:
        relative = posixpath.join(base_dir, path)
    return STATIC_PREFIX + posixpath.normpath(relative)


def index_references(html: str) -> list[str]:
    """Local asset references of an HTML page, in document order."""
    parser = _ReferenceParser()
    parser.feed(html)
    return [ref for ref in parser.references if _is_local(ref)]


def static_asset_violations(
    names: Collection[str], read: Callable[[str], str]
) -> list[str]:
    """Check the committed web UI bundle inside the wheel's member list.

    ``read`` returns the text of an archive member. Every local reference of
    ``index.html`` and of every stylesheet's ``url()`` must name a member, and
    the bundle must contain at least one script and one stylesheet.
    """
    violations: list[str] = []
    index = STATIC_PREFIX + "index.html"
    if index not in names:
        return [f"webui wheel lacks {index}"]
    if not any(
        name.startswith(STATIC_PREFIX) and name.endswith(".js") for name in names
    ):
        violations.append("webui static bundle has no .js file")
    if not any(
        name.startswith(STATIC_PREFIX) and name.endswith(".css") for name in names
    ):
        violations.append("webui static bundle has no .css file")
    for reference in index_references(read(index)):
        member = _member_for("", reference)
        if member not in names:
            violations.append(f"index.html references missing {reference}")
    for name in sorted(names):
        if not (name.startswith(STATIC_PREFIX) and name.endswith(".css")):
            continue
        css_dir = posixpath.dirname(name.removeprefix(STATIC_PREFIX))
        for match in _CSS_URL.finditer(read(name)):
            reference = match.group(2)
            if not _is_local(reference):
                continue
            member = _member_for(css_dir, reference)
            if member not in names:
                violations.append(f"{name} references missing {reference}")
    return violations


def session_violations(payload: object, repository_name: str) -> list[str]:
    """Check the ``GET /api/session`` payload of an installed server (§21.6).

    The page reads ``csrf_token`` (mutations need it), the repository name, the
    configured types and the version. Anything missing or wrong is reported.
    """
    if not isinstance(payload, dict):
        return ["/api/session did not return a JSON object"]
    violations: list[str] = []
    token = payload.get("csrf_token")
    if not isinstance(token, str) or not token:
        violations.append("/api/session lacks a non-empty csrf_token")
    repository = payload.get("repository")
    name = repository.get("name") if isinstance(repository, dict) else None
    if name != repository_name:
        violations.append(
            f"/api/session repository.name is {name!r}, expected {repository_name!r}"
        )
    types = payload.get("types")
    if not isinstance(types, list) or not types:
        violations.append("/api/session lacks configured types")
    if not isinstance(payload.get("version"), str):
        violations.append("/api/session lacks version")
    return violations


def page_url(base: str, reference: str) -> str:
    """Absolute URL of a page-relative or root-relative reference."""
    return urljoin(base, reference)


def _archive_names(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def _archive_text(wheel: Path, name: str) -> str:
    with zipfile.ZipFile(wheel) as archive:
        return archive.read(name).decode("utf-8")


def _entry_point_violations(wheel: Path, version: str) -> list[str]:
    """The web UI wheel must declare ``webui`` in the ``gregraph.serve`` group."""
    dist_info = f"gregraph_webui-{version}.dist-info/entry_points.txt"
    names = _archive_names(wheel)
    if dist_info not in names:
        return [f"webui wheel lacks {dist_info}"]
    text = _archive_text(wheel, dist_info)
    expected = "[gregraph.serve]\nwebui = gregraph.webui.launch:launch"
    if expected not in text.replace("\r\n", "\n"):
        return [f"{dist_info} lacks the gregraph.serve webui entry point"]
    return []


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


def _run_expect(
    args: Sequence[str | Path], cwd: Path, what: str, expected: int
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != expected:
        raise SystemExit(
            f"FAILED: {what} (exit {result.returncode}, expected {expected})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def build_wheels(out: Path, *, no_build_isolation: bool) -> tuple[Path, Path, Path]:
    args: list[str | Path] = [sys.executable, "-m", "pip", "wheel", "--no-deps"]
    if no_build_isolation:
        args.append("--no-build-isolation")
    args += [CORE_DIR, CLI_DIR, WEBUI_DIR, "-w", out]
    _run(args, REPO_ROOT, "build wheels")
    return build_wheels_from(out)


def _make_venv(path: Path) -> Path:
    _run([sys.executable, "-m", "venv", path], REPO_ROOT, f"create venv {path}")
    return path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


CORE_SNIPPET = """
import importlib.metadata as md
import importlib.resources as res
import importlib.util
import gregraph
import gregraph.core
assert gregraph.__version__ == {version!r}, gregraph.__version__
assert md.version("gregraph-core") == {version!r}
assert importlib.util.find_spec("gregraph.cli") is None, "cli leaked"
assert importlib.util.find_spec("gregraph.webui") is None, "webui leaked"
assert list(md.entry_points(group="gregraph.serve")) == [], "serve leaked"
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
assert importlib.util.find_spec("gregraph.webui") is None, "webui leaked"
assert list(md.entry_points(group="gregraph.serve")) == [], "serve leaked"
requires = md.requires("gregraph-cli") or []
assert "gregraph-core=={version}" in [r.replace(" ", "") for r in requires], requires
print("both ok")
"""

ALL_SNIPPET = """
import importlib.metadata as md
import importlib.resources as res
import sys
import gregraph
import gregraph.webui
assert gregraph.__version__ == {version!r}
assert md.version("gregraph-webui") == {version!r}
assert md.version("gregraph-cli") == {version!r}
assert md.version("gregraph-core") == {version!r}
serve = {{ep.name: ep.value for ep in md.entry_points(group="gregraph.serve")}}
assert serve == {{"webui": "gregraph.webui.launch:launch"}}, serve
index = res.files("gregraph.webui").joinpath("static", "index.html")
assert index.is_file(), index
print("all ok")
"""

HELP_SNIPPET = """
import sys
from gregraph.cli.main import main
try:
    main(["--help"])
except SystemExit as exc:
    assert exc.code == 0, exc.code
for name in ("gregraph.webui", "gregraph.webui.launch", "fastapi", "uvicorn"):
    assert name not in sys.modules, f"--help imported {{name}}"
print("help lazy ok")
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
        "install core and cli wheels",
    )
    _run(
        [venv_python(venv), "-I", "-c", BOTH_SNIPPET.format(version=version)],
        work,
        "core+cli import checks",
    )
    for command in (
        [venv_script(venv, "gregraph"), "--version"],
        [venv_python(venv), "-I", "-m", "gregraph", "--version"],
    ):
        out = _run(command, work, f"run {command[0]} --version").strip()
        if out != version:
            raise SystemExit(f"FAILED: {command[0]} --version printed {out!r}")
    help_text = _run([venv_script(venv, "gregraph"), "--help"], work, "core+cli --help")
    if re.search(r"^\s+serve\s", help_text, re.MULTILINE):
        raise SystemExit("FAILED: core+cli help lists serve without gregraph-webui")
    _run_expect(
        [venv_python(venv), "-I", "-m", "gregraph", "serve", "--help"],
        work,
        "serve must be absent without gregraph-webui",
        2,
    )
    print("both: ok")


def check_all(
    core_wheel: Path, cli_wheel: Path, webui_wheel: Path, work: Path, version: str
) -> None:
    venv = _make_venv(work / "all")
    _run(
        [
            venv_python(venv),
            "-m",
            "pip",
            "install",
            "--quiet",
            core_wheel,
            cli_wheel,
            webui_wheel,
        ],
        work,
        "install all three wheels",
    )
    _run(
        [venv_python(venv), "-I", "-c", ALL_SNIPPET.format(version=version)],
        work,
        "all-three import checks",
    )
    _run(
        [venv_python(venv), "-I", "-c", HELP_SNIPPET],
        work,
        "--help must not import the web UI",
    )
    help_text = _run([venv_script(venv, "gregraph"), "--help"], work, "all --help")
    if not re.search(r"^\s+serve\s", help_text, re.MULTILINE):
        raise SystemExit("FAILED: all-three help does not list serve")
    _run(
        [venv_script(venv, "gregraph"), "serve", "--help"],
        work,
        "gregraph serve --help",
    )
    _check_serve_smoke(venv, work)
    print("all: ok")


def check_webui_without_deps(
    core_wheel: Path, cli_wheel: Path, webui_wheel: Path, work: Path
) -> None:
    venv = _make_venv(work / "webui-no-deps")
    _run(
        [venv_python(venv), "-m", "pip", "install", "--quiet", core_wheel, cli_wheel],
        work,
        "install core and cli wheels",
    )
    _run(
        [
            venv_python(venv),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            webui_wheel,
        ],
        work,
        "install webui wheel without dependencies",
    )
    _run(
        [
            venv_python(venv),
            "-I",
            "-c",
            "import importlib.util as u;"
            "assert u.find_spec('fastapi') is None;"
            "assert u.find_spec('uvicorn') is None;"
            "print('no fastapi')",
        ],
        work,
        "webui dependencies must be absent",
    )
    _run([venv_python(venv), "-I", "-c", HELP_SNIPPET], work, "lazy --help")
    help_text = _run([venv_script(venv, "gregraph"), "--help"], work, "--help")
    if not re.search(r"^\s+serve\s", help_text, re.MULTILINE):
        raise SystemExit("FAILED: --help without fastapi does not list serve")
    repo = work / "no-deps-repo"
    _run(
        [venv_script(venv, "gregraph"), "init", repo, "--no-git"],
        work,
        "init no-deps repository",
    )
    failed = _run_expect(
        [venv_script(venv, "gregraph"), "--repo", repo, "serve"],
        work,
        "serve without fastapi must fail",
        SERVE_EXIT_ENV,
    )
    if "gregraph-webui" not in failed.stderr:
        raise SystemExit(f"FAILED: missing-dependency message: {failed.stderr!r}")
    print("webui without deps: ok")


def _wait_for_http(url: str, process: subprocess.Popen[bytes], log: Path) -> str:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(
                f"FAILED: serve exited early ({process.returncode}):\n"
                f"{log.read_text(encoding='utf-8', errors='replace')}"
            )
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body: str = response.read().decode("utf-8")
                return body
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise SystemExit(f"FAILED: serve did not answer {url} within 60 s")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _check_serve_smoke(venv: Path, work: Path) -> None:
    """Start the installed server on a free loopback port and fetch its pages."""
    repo = work / "smoke-repo"
    _run(
        [venv_script(venv, "gregraph"), "init", repo, "--no-git"],
        work,
        "init smoke repository",
    )
    port = _free_port()
    log = work / "serve.log"
    with log.open("wb") as handle:
        process = subprocess.Popen(
            [
                str(venv_script(venv, "gregraph")),
                "--repo",
                str(repo),
                "serve",
                "--port",
                str(port),
            ],
            cwd=work,
            env=_clean_env(),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        try:
            base = f"http://127.0.0.1:{port}/"
            page = _wait_for_http(base, process, log)
            references = index_references(page)
            if not references:
                raise SystemExit("FAILED: served index.html references no assets")
            for reference in references:
                url = page_url(base, reference)
                with urllib.request.urlopen(url, timeout=10) as response:
                    if response.status != 200:
                        raise SystemExit(f"FAILED: {url} -> {response.status}")
            with urllib.request.urlopen(base + "api/session", timeout=10) as response:
                if response.status != 200:
                    raise SystemExit(f"FAILED: /api/session -> {response.status}")
                payload: object = json.loads(response.read().decode("utf-8"))
            problems = session_violations(payload, repo.name)
            if problems:
                raise SystemExit("FAILED: " + "; ".join(problems))
        finally:
            _stop(process)
    print("serve smoke: ok")


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
            core_wheel, cli_wheel, webui_wheel = build_wheels(
                wheels_dir, no_build_isolation=args.no_build_isolation
            )
        else:
            core_wheel, cli_wheel, webui_wheel = build_wheels_from(args.wheel_dir)
        print(f"wheels: {core_wheel.name}, {cli_wheel.name}, {webui_wheel.name}")

        overlaps = find_overlaps([core_wheel, cli_wheel, webui_wheel])
        if overlaps:
            raise SystemExit(f"FAILED: overlapping wheel files: {overlaps}")
        violations = wheel_contract_violations(
            _archive_names(core_wheel),
            _archive_names(cli_wheel),
            _archive_names(webui_wheel),
        )
        violations += _entry_point_violations(webui_wheel, version)
        if violations:
            raise SystemExit("FAILED: " + "; ".join(violations))
        print("wheel contract: ok")

        assets = static_asset_violations(
            _archive_names(webui_wheel),
            lambda member: _archive_text(webui_wheel, member),
        )
        if assets:
            raise SystemExit("FAILED: " + "; ".join(assets))
        print("static bundle: ok")

        check_core_only(core_wheel, work, version)
        check_both(core_wheel, cli_wheel, work, version)
        check_all(core_wheel, cli_wheel, webui_wheel, work, version)
        check_webui_without_deps(core_wheel, cli_wheel, webui_wheel, work)
    print(f"packaging check passed for {version}")
    return 0


def build_wheels_from(directory: Path) -> tuple[Path, Path, Path]:
    core = sorted(directory.glob("gregraph_core-*.whl"))
    cli = sorted(directory.glob("gregraph_cli-*.whl"))
    webui = sorted(directory.glob("gregraph_webui-*.whl"))
    if len(core) != 1 or len(cli) != 1 or len(webui) != 1:
        raise SystemExit(f"expected one wheel per distribution in {directory}")
    return core[0], cli[0], webui[0]


if __name__ == "__main__":
    raise SystemExit(main())
