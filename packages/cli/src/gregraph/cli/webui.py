"""Discovery of the optional ``serve`` command (spec §21.2–21.3).

The CLI learns whether ``gregraph-webui`` is installed from entry-point
*metadata* only (group ``gregraph.serve``, name ``webui``). Nothing here imports
the web UI package: the launcher is loaded by :func:`load_launcher`, which
``gregraph.cli.commands.serve`` calls at dispatch time, never during parser
construction or ``--help``.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from importlib.metadata import EntryPoint, entry_points

SERVE_GROUP = "gregraph.serve"
SERVE_NAME = "webui"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")

#: ``launch(root, *, host, port) -> int``; blocks until interrupted (§21.3).
Launcher = Callable[..., int]


def serve_entry_points() -> list[EntryPoint]:
    """Entry points of group ``gregraph.serve``; reads metadata, imports nothing."""
    return list(entry_points(group=SERVE_GROUP))


def find_serve_entry_point() -> EntryPoint | None:
    """The ``webui`` entry point when ``gregraph-webui`` is installed, else ``None``."""
    for entry in serve_entry_points():
        if entry.name == SERVE_NAME:
            return entry
    return None


def load_launcher(entry: EntryPoint) -> Launcher:
    """Import the launcher. Only called at dispatch of ``serve`` (§21.2)."""
    loaded: Launcher = entry.load()
    return loaded


def check_port_available(host: str, port: int) -> None:
    """Raise ``OSError`` when ``host:port`` cannot be bound right now.

    The probe binds and closes a socket; it listens for nothing. SO_REUSEADDR
    is set off Windows so a port left in TIME_WAIT by a previous run is not a
    false failure, mirroring what the server socket does.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        if os.name != "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
