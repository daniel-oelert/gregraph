"""Optional ``gregraph serve`` command (spec §13, §16.4; web UI contract).

``serve`` exists only when the optional ``gregraph-webui`` distribution is
installed. Its presence is decided from ``gregraph.serve`` entry-point metadata
alone: ``--help`` never imports the optional package, and the launcher is
loaded only at dispatch. Tests fake the discovery seam
(``gregraph.cli.webui.serve_entry_points``) so they behave the same whether or
not ``gregraph-webui`` is installed in the environment.
"""

from __future__ import annotations

import io
import socket
import sys
import types
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest

from gregraph.cli import webui
from gregraph.cli.main import (
    EXIT_ENV,
    EXIT_OK,
    EXIT_USAGE,
    UsageError,
    build_parser,
    main,
)

FAKE_MODULE = "fake_gregraph_webui_launch"
ABSENT_MODULE = "gregraph_webui_module_that_does_not_exist"


def _entry_point(module: str) -> EntryPoint:
    return EntryPoint(name="webui", value=f"{module}:launch", group=webui.SERVE_GROUP)


@pytest.fixture
def serve_present(monkeypatch: pytest.MonkeyPatch) -> EntryPoint:
    """Advertise the serve entry point, pointing at a loadable fake launcher."""
    entry = _entry_point(FAKE_MODULE)
    monkeypatch.setattr(webui, "serve_entry_points", lambda: [entry])
    return entry


@pytest.fixture
def launcher_calls(
    monkeypatch: pytest.MonkeyPatch, serve_present: EntryPoint
) -> list[dict[str, Any]]:
    """Record every call into the fake launcher; it returns 0."""
    calls: list[dict[str, Any]] = []

    def launch(root: Path, *, host: str, port: int) -> int:
        calls.append({"root": root, "host": host, "port": port})
        return 0

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    return calls


@pytest.fixture
def no_port_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real bind probe (used when the test only checks argv/output)."""
    monkeypatch.setattr(webui, "check_port_available", lambda host, port: None)


@pytest.fixture
def free_port() -> int:
    """A loopback port that was free a moment ago (the probe is closed)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# --------------------------------------------------------------------------
# absent: no serve command, no help entry, existing CLI unchanged
# --------------------------------------------------------------------------


@pytest.fixture
def serve_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webui, "serve_entry_points", lambda: [])


def test_absent_help_has_no_serve_entry(
    serve_absent: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "serve" not in capsys.readouterr().out


def test_absent_serve_is_usage_error_with_install_hint(
    serve_absent: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "gregraph-webui" in err


def test_absent_parser_rejects_serve(serve_absent: None) -> None:
    with pytest.raises(UsageError):
        build_parser().parse_args(["serve"])


def test_absent_leaves_other_commands_untouched(serve_absent: None) -> None:
    args = build_parser().parse_args(["list", "--roots"])
    assert args.command == "list"
    assert args.roots is True


# --------------------------------------------------------------------------
# present: discovery is metadata-only and the launcher loads at dispatch
# --------------------------------------------------------------------------


def test_present_help_lists_serve(
    serve_present: EntryPoint, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "serve" in capsys.readouterr().out


def test_present_serve_help_documents_loopback_options(
    serve_present: EntryPoint, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["serve", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--host" in out
    assert "--port" in out
    assert "127.0.0.1" in out
    assert "8765" in out


def test_help_never_loads_the_launcher(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Help must not import the optional package (absent module here)."""
    entry = _entry_point(ABSENT_MODULE)
    monkeypatch.setattr(webui, "serve_entry_points", lambda: [entry])

    def fail(_: EntryPoint) -> None:
        raise AssertionError("launcher loaded during --help")

    monkeypatch.setattr(webui, "load_launcher", fail)
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    with pytest.raises(SystemExit):
        main(["serve", "--help"])
    assert ABSENT_MODULE not in sys.modules


def test_dispatch_loads_launcher_and_passes_arguments(
    tmp_repo: Path,
    launcher_calls: list[dict[str, Any]],
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["--repo", str(tmp_repo), "serve", "--port", "9123"])
    assert rc == EXIT_OK
    assert launcher_calls == [
        {"root": tmp_repo.resolve(), "host": "127.0.0.1", "port": 9123}
    ]
    assert "GREGraph UI: http://127.0.0.1:9123/" in capsys.readouterr().out


def test_defaults_are_loopback_and_8765(
    tmp_repo: Path, launcher_calls: list[dict[str, Any]], no_port_check: None
) -> None:
    assert main(["--repo", str(tmp_repo), "serve"]) == EXIT_OK
    assert launcher_calls[0]["host"] == "127.0.0.1"
    assert launcher_calls[0]["port"] == 8765


def test_localhost_is_accepted(
    tmp_repo: Path, launcher_calls: list[dict[str, Any]], no_port_check: None
) -> None:
    assert main(["--repo", str(tmp_repo), "serve", "--host", "localhost"]) == EXIT_OK
    assert launcher_calls[0]["host"] == "localhost"


def test_banner_is_printed_before_the_blocking_launcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plain URL plus stop hint, printed before launch() blocks (spec §21.3)."""
    seen_at_launch: list[str] = []

    def launch(root: Path, *, host: str, port: int) -> int:
        seen_at_launch.append(capsys.readouterr().out)
        return 0

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    rc = main(["--repo", str(tmp_repo), "serve", "--port", "9123"])
    assert rc == EXIT_OK
    assert seen_at_launch == [
        "GREGraph UI: http://127.0.0.1:9123/\nPress Ctrl-C to stop.\n"
    ]


def test_banner_brackets_ipv6_and_carries_no_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def launch(root: Path, *, host: str, port: int) -> int:
        return 0

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    main(["--repo", str(tmp_repo), "serve", "--host", "::1", "--port", "8000"])
    out = capsys.readouterr().out
    assert "GREGraph UI: http://[::1]:8000/\n" in out
    assert "Press Ctrl-C to stop." in out
    assert "token" not in out
    assert "#" not in out


def test_ipv6_loopback_host_is_passed_through(
    tmp_repo: Path,
    launcher_calls: list[dict[str, Any]],
    no_port_check: None,
) -> None:
    rc = main(["--repo", str(tmp_repo), "serve", "--host", "::1", "--port", "8000"])
    assert rc == EXIT_OK
    assert launcher_calls[0]["host"] == "::1"
    assert launcher_calls[0]["port"] == 8000


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "192.168.1.5", "example.com", "", "*", "[::1]"]
)
def test_remote_or_unknown_hosts_are_usage_errors(
    host: str,
    tmp_repo: Path,
    launcher_calls: list[dict[str, Any]],
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["--repo", str(tmp_repo), "serve", "--host", host])
    assert rc == EXIT_USAGE
    assert launcher_calls == []
    assert "127.0.0.1" in capsys.readouterr().err


@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc", "1.5", ""])
def test_out_of_range_ports_are_usage_errors(
    port: str,
    tmp_repo: Path,
    launcher_calls: list[dict[str, Any]],
    no_port_check: None,
) -> None:
    rc = main(["--repo", str(tmp_repo), "serve", "--port", port])
    assert rc == EXIT_USAGE
    assert launcher_calls == []


@pytest.mark.parametrize("port", ["1", "65535"])
def test_port_bounds_are_accepted(port: str, serve_present: EntryPoint) -> None:
    args = build_parser().parse_args(["serve", "--port", port])
    assert args.port == int(port)


def test_outside_repository_is_environment_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launcher_calls: list[dict[str, Any]],
    no_port_check: None,
) -> None:
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert main(["serve"]) == EXIT_ENV
    assert launcher_calls == []


def test_root_is_discovered_from_a_subdirectory(
    tmp_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    launcher_calls: list[dict[str, Any]],
    no_port_check: None,
) -> None:
    monkeypatch.chdir(tmp_repo / "documents")
    assert main(["serve"]) == EXIT_OK
    assert launcher_calls[0]["root"] == tmp_repo.resolve()


def test_missing_optional_dependency_is_environment_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        webui, "serve_entry_points", lambda: [_entry_point(ABSENT_MODULE)]
    )
    rc = main(["--repo", str(tmp_repo), "serve"])
    assert rc == EXIT_ENV
    assert "gregraph-webui" in capsys.readouterr().err


def test_import_error_while_launching_is_environment_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def launch(root: Path, *, host: str, port: int) -> int:
        raise ImportError("No module named 'fastapi'")

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    rc = main(["--repo", str(tmp_repo), "serve", "--port", "8123"])
    assert rc == EXIT_ENV
    assert "gregraph-webui" in capsys.readouterr().err


def test_port_in_use_is_environment_error(
    tmp_repo: Path,
    launcher_calls: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = int(busy.getsockname()[1])
        rc = main(["--repo", str(tmp_repo), "serve", "--port", str(port)])
    assert rc == EXIT_ENV
    assert launcher_calls == []
    err = capsys.readouterr().err
    assert str(port) in err
    assert "--port" in err


def test_free_port_passes_the_probe(free_port: int) -> None:
    webui.check_port_available("127.0.0.1", free_port)


def test_os_error_from_launcher_is_environment_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def launch(root: Path, *, host: str, port: int) -> int:
        raise OSError("socket went away")

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    assert main(["--repo", str(tmp_repo), "serve"]) == EXIT_ENV
    assert "socket went away" in capsys.readouterr().err


def test_keyboard_interrupt_is_a_clean_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
) -> None:
    def launch(root: Path, *, host: str, port: int) -> int:
        raise KeyboardInterrupt

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    assert main(["--repo", str(tmp_repo), "serve"]) == EXIT_OK


def test_cli_modules_never_import_the_webui_package() -> None:
    """Static guard: the CLI layer reaches the web UI only through metadata."""
    root = Path(__file__).resolve().parents[2]
    cli = root / "packages" / "cli" / "src" / "gregraph" / "cli"
    sources: list[Path] = [cli / "main.py", cli / "webui.py"]
    sources += sorted((cli / "commands").glob("*.py"))
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "gregraph.webui" not in text, path
        assert "fastapi" not in text, path
        assert "uvicorn" not in text, path


BANNER = "GREGraph UI: http://127.0.0.1:9123/\nPress Ctrl-C to stop.\n"


def _plain_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake launcher that returns at once (the real one blocks)."""

    def launch(root: Path, *, host: str, port: int) -> int:
        return 0

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)


class _StdoutSpy(io.StringIO):
    """stdout stand-in that remembers the text present at its last flush."""

    def __init__(self) -> None:
        super().__init__()
        self.flushed = ""

    def flush(self) -> None:
        super().flush()
        self.flushed = self.getvalue()


@pytest.mark.parametrize(
    "argv_before",
    [[], ["--json"], ["--quiet"], ["-q"], ["--json", "-q"], ["--no-input"]],
)
@pytest.mark.parametrize(
    "argv_after",
    [[], ["--json"], ["--quiet"], ["-q"], ["--json", "-q"]],
)
def test_banner_is_printed_under_global_flags_wherever_they_appear(
    argv_before: list[str],
    argv_after: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _plain_launcher(monkeypatch)
    argv = [
        *argv_before,
        "--repo",
        str(tmp_repo),
        "serve",
        "--port",
        "9123",
        *argv_after,
    ]
    assert main(argv) == EXIT_OK
    assert BANNER in capsys.readouterr().out


def test_banner_under_json_is_plain_text_not_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _plain_launcher(monkeypatch)
    main(["--json", "--repo", str(tmp_repo), "serve", "--port", "9123"])
    out = capsys.readouterr().out
    assert out == BANNER
    assert "{" not in out
    assert "token" not in out


def test_ipv6_banner_under_quiet_is_bracketed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _plain_launcher(monkeypatch)
    main(["-q", "--repo", str(tmp_repo), "serve", "--host", "::1", "--port", "8000"])
    out = capsys.readouterr().out
    assert out == "GREGraph UI: http://[::1]:8000/\nPress Ctrl-C to stop.\n"


def test_banner_is_flushed_before_the_launcher_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_repo: Path,
    serve_present: EntryPoint,
    no_port_check: None,
) -> None:
    spy = _StdoutSpy()
    monkeypatch.setattr(sys, "stdout", spy)
    flushed_at_launch: list[str] = []

    def launch(root: Path, *, host: str, port: int) -> int:
        flushed_at_launch.append(spy.flushed)
        return 0

    module = types.ModuleType(FAKE_MODULE)
    module.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
    assert main(["--repo", str(tmp_repo), "serve", "--port", "9123"]) == EXIT_OK
    assert flushed_at_launch == [BANNER]
