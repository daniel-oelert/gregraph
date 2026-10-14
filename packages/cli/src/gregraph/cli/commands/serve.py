"""``gregraph serve`` — start the optional local web UI (spec §21.3).

A lifecycle command, exempt from the one-function-per-command rule (§13, §21.10).
It exists only when ``gregraph-webui`` is installed (see ``gregraph.cli.webui``),
and it loads the launcher only here, at dispatch. Repository discovery goes
through ``App.open_workspace`` like every other command. The CLI prints the
plain banner (URL and stop hint) through ``Output.announce``, which ignores
``--quiet``/``--json`` and flushes, before the blocking launcher runs. The
launcher itself prints nothing (log level warning). No token appears in the URL.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from gregraph.cli import webui
from gregraph.cli.main import EXIT_ENV, EXIT_OK

if TYPE_CHECKING:
    from gregraph.cli.main import App


def run(args: argparse.Namespace, app: App) -> int:
    entry = webui.find_serve_entry_point()
    if entry is None:
        app.out.error("gregraph serve needs gregraph-webui: pip install gregraph-webui")
        return EXIT_ENV
    workspace = app.open_workspace()
    host: str = args.host
    port: int = args.port
    try:
        launcher = webui.load_launcher(entry)
    except ImportError as exc:
        app.out.error(_missing_dependency(exc))
        return EXIT_ENV
    try:
        webui.check_port_available(host, port)
    except OSError as exc:
        app.out.error(
            f"cannot listen on {host} port {port}: {exc.strerror or exc} "
            "(is it in use? choose another with --port)"
        )
        return EXIT_ENV
    app.out.announce(_banner(host, port))
    try:
        return int(launcher(workspace.root, host=host, port=port))
    except KeyboardInterrupt:
        return EXIT_OK
    except ImportError as exc:
        app.out.error(_missing_dependency(exc))
        return EXIT_ENV
    except OSError as exc:
        app.out.error(f"web UI stopped: {exc}")
        return EXIT_ENV


def _banner(host: str, port: int) -> str:
    """Plain URL (IPv6 bracketed) and the stop hint (spec §21.3)."""
    shown = f"[{host}]" if ":" in host else host
    return f"GREGraph UI: http://{shown}:{port}/\nPress Ctrl-C to stop."


def _missing_dependency(exc: ImportError) -> str:
    return (
        f"gregraph serve cannot import the web UI ({exc}); "
        "reinstall gregraph-webui (pip install gregraph-webui)"
    )
