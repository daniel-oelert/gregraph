"""Foreground loopback server for ``gregraph serve`` (design §21.3–21.4).

:func:`launch` is the ``gregraph.serve`` entry point ``webui``. It validates the
bind address, builds the app for ``root`` and blocks in one uvicorn process until
interrupted. It prints nothing; the CLI announces the URL. Forwarded-header
trust is disabled so that a local client cannot make a request look like it came
from another origin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import uvicorn

from gregraph.webui.app import create_app

ALLOWED_HOSTS: Final = ("127.0.0.1", "localhost", "::1")
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765


def _check_bind(host: str, port: int) -> None:
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host must be one of {', '.join(ALLOWED_HOSTS)}")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer from 1 to 65535")


def launch(root: Path, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> int:
    """Serve the web UI for ``root`` on ``host:port``; return 0 after Ctrl-C.

    Raises ``ValueError`` for a non-loopback host or an invalid port (no socket is
    opened), ``FileNotFoundError`` when ``root`` is not a repository, and
    ``OSError`` when the address cannot be bound.
    """
    _check_bind(host, port)
    app = create_app(root, port=port)
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,
            proxy_headers=False,
            forwarded_allow_ips="",
            server_header=False,
            access_log=False,
            log_level="warning",
        )
    except SystemExit as exc:
        raise OSError(f"could not serve on {host}:{port}") from exc
    return 0
