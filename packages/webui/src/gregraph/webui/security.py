"""Local-only request guards (design §21.4).

Pure predicates (Host, Origin, Sec-Fetch-Site, token) plus one ASGI middleware
that applies them to every HTTP request before routing, adds the security
headers, and turns any unexpected exception into a generic JSON 500 so that no
traceback reaches a client. Header values are decoded as Latin-1 by Starlette;
the token comparison works on UTF-8 bytes so a non-ASCII token is a plain
mismatch (403), never an exception.
"""

from __future__ import annotations

import hmac
import logging
from http import HTTPStatus
from typing import Any, Final

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gregraph.webui.errors import ApiError, error_body

_LOG = logging.getLogger("gregraph.webui")

TOKEN_HEADER: Final = "x-gregraph-token"
MAX_BODY_BYTES: Final = 1024 * 1024
CSP: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
    "object-src 'none'"
)
_LOOPBACK_NAME: Final = "localhost"
_LOOPBACK_IPV4: Final = "127.0.0.1"
_LOOPBACK_IPV6: Final = "::1"
_SAFE_FETCH_SITES: Final = frozenset({"same-origin", "none"})
_MAX_PORT: Final = 65535
_HTTP_DEFAULT_PORT: Final = 80


def _parse_port(text: str) -> int | None:
    """Explicit port in a Host value; ``None`` for an invalid or empty port."""
    if not text.isascii() or not text.isdigit():
        return None
    value = int(text)
    return value if 1 <= value <= _MAX_PORT else None


def _split_host(value: str) -> tuple[str, int | None] | None:
    """``(name, port)`` of a Host header value, or ``None`` when malformed."""
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        name = value[1:end]
        rest = value[end + 1 :]
        if rest == "":
            return name, None
        if not rest.startswith(":"):
            return None
        port = _parse_port(rest[1:])
        return (name, port) if port is not None else None
    if value.count(":") > 1:
        return None
    if ":" in value:
        name, _, port_text = value.partition(":")
        port = _parse_port(port_text)
        return (name, port) if port is not None else None
    return value, None


def _is_loopback_name(name: str, *, ipv6: bool) -> bool:
    """Exactly the served loopback names (design §21.3): ``127.0.0.1``,
    ``localhost`` (any case) and, bracketed in Host, ``::1``. The rest of
    ``127/8``, mapped or expanded IPv6 spellings are different addresses."""
    if ipv6:
        return name == _LOOPBACK_IPV6
    return name == _LOOPBACK_IPV4 or name.lower() == _LOOPBACK_NAME


def host_allowed(host: str | None, port: int | None = None) -> bool:
    """Whether a Host header names a loopback host (and ``port`` when given).

    Accepts exactly ``127.0.0.1``, ``localhost`` (any case) and ``::1``
    (bracketed in Host); other ``127/8`` addresses and IPv6 spellings are refused.
    With ``port`` set, the header must name that port. A header without a port
    means the HTTP default, 80, so a server bound to port 80 accepts the bare
    ``127.0.0.1`` and ``localhost`` that browsers send; any other bound port
    still needs its explicit value (design §21.4). Plain HTTP only.
    """
    if not host:
        return False
    parsed = _split_host(host)
    if parsed is None:
        return False
    name, header_port = parsed
    bracketed = host.startswith("[")
    if not _is_loopback_name(name, ipv6=bracketed):
        return False
    if port is None:
        return True
    effective = _HTTP_DEFAULT_PORT if header_port is None else header_port
    return effective == port


def origin_matches(origin: str, *, scheme: str, host: str) -> bool:
    """Exact origin equality with the request origin (design §21.4)."""
    if not origin or not host:
        return False
    return origin.lower() == f"{scheme}://{host}".lower()


def fetch_site_allowed(value: str | None) -> bool:
    """Only ``same-origin`` or ``none`` (or an absent header) pass."""
    return value is None or value in _SAFE_FETCH_SITES


def token_matches(provided: str | None, expected: str) -> bool:
    """Constant-time token comparison over UTF-8 bytes; never raises."""
    if provided is None:
        return False
    left = provided.encode("utf-8", "surrogatepass")
    right = expected.encode("utf-8", "surrogatepass")
    return hmac.compare_digest(left, right)


def _header_values(scope: Scope, name: bytes) -> list[str]:
    return [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == name
    ]


def _refusal(message: str) -> ApiError:
    return ApiError(HTTPStatus.FORBIDDEN, "E-REQUEST-REFUSED", message)


def check_request(scope: Scope, bound_port: int | None) -> ApiError | None:
    """First failing guard for an HTTP scope, or ``None``."""
    hosts = _header_values(scope, b"host")
    if len(hosts) != 1:
        return _refusal("request must carry exactly one loopback Host header")
    host = hosts[0]
    if not host_allowed(host, port=bound_port):
        return _refusal("request host is not an allowed loopback host")
    origins = _header_values(scope, b"origin")
    if len(origins) > 1:
        return _refusal("ambiguous Origin header")
    if origins and not origin_matches(origins[0], scheme=scope["scheme"], host=host):
        return _refusal("cross-origin request refused")
    fetch_sites = _header_values(scope, b"sec-fetch-site")
    if len(fetch_sites) > 1:
        return _refusal("ambiguous Sec-Fetch-Site header")
    if fetch_sites and not fetch_site_allowed(fetch_sites[0]):
        return _refusal("cross-site request refused")
    return None


def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> None:
    headers[:] = [(key, val) for key, val in headers if key.lower() != name]
    headers.append((name, value))


def _secured_send(send: Send, path: str) -> Send:
    api = path == "/api" or path.startswith("/api/")

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
            _set_header(headers, b"content-security-policy", CSP.encode("ascii"))
            _set_header(headers, b"x-content-type-options", b"nosniff")
            _set_header(headers, b"referrer-policy", b"no-referrer")
            _set_header(headers, b"x-frame-options", b"DENY")
            if api:
                _set_header(headers, b"cache-control", b"no-store")
            message["headers"] = headers
        await send(message)

    return wrapped


class SecurityMiddleware:
    """ASGI guard: Host/Origin/Fetch-Site, security headers, generic 500."""

    def __init__(self, app: ASGIApp, *, bound_port: int | None = None) -> None:
        self.app = app
        self.bound_port = bound_port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        secured = _secured_send(send, path)
        refusal = check_request(scope, self.bound_port)
        if refusal is not None:
            await self._respond(
                scope, receive, secured, refusal.status_code, refusal.envelope()
            )
            return
        started = False

        async def tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await secured(message)

        try:
            await self.app(scope, receive, tracking)
        except Exception:
            _LOG.exception("unhandled error in web UI request")
            if started:
                raise
            await self._respond(
                scope,
                receive,
                secured,
                500,
                error_body("E-INTERNAL", "internal error"),
            )

    async def _respond(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        body: dict[str, Any],
    ) -> None:
        await JSONResponse(body, status_code=status)(scope, receive, send)


async def read_mutation_body(request: Request, expected_token: str) -> bytes:
    """Authorise and bound a mutation request, then return its raw body.

    Order: exactly one token header that matches (403); JSON media type and no
    Content-Encoding (415); declared length within the cap (413); then the body
    is streamed and counted, refusing at the first byte past the cap (413).
    """
    tokens = request.headers.getlist(TOKEN_HEADER)
    if len(tokens) != 1 or not token_matches(tokens[0], expected_token):
        raise ApiError(
            HTTPStatus.FORBIDDEN, "E-TOKEN-INVALID", "missing or invalid token"
        )
    if request.headers.get("content-encoding") is not None:
        raise ApiError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "E-CONTENT-ENCODING",
            "request bodies must not be content-encoded",
        )
    media = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if media != "application/json":
        raise ApiError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "E-CONTENT-TYPE",
            "request body must be application/json",
        )
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _too_large() -> ApiError:
    return ApiError(
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        "E-BODY-TOO-LARGE",
        "request body exceeds 1 MiB",
    )
