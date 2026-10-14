"""Local-only request guards: Host, Origin, Sec-Fetch-Site, token, body (webui design).

Unit tests pin the pure predicates; integration tests drive the app through
``TestClient``. Loopback literals include IPv6 ``[::1]`` and ``localhost``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webui_support import LOOPBACK_BASE, TOKEN_HEADER, add_document, auth, error_code

from gregraph.webui import app as app_module
from gregraph.webui import security
from gregraph.webui.app import create_app

MIB = 1024 * 1024


# --------------------------------------------------------------------------
# pure predicates
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.1:8765",
        "localhost",
        "localhost:8765",
        "LOCALHOST:65535",
        "[::1]",
        "[::1]:8765",
    ],
)
def test_loopback_host_headers_are_accepted(host: str) -> None:
    assert security.host_allowed(host) is True


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "evil.example",
        "evil.example:8765",
        "localhost.evil.example",
        # Only 127.0.0.1, localhost and ::1 are served (design §21.3); the rest of
        # 127/8 and mapped or expanded IPv6 spellings are other addresses.
        "127.0.0.2",
        "127.20.30.40",
        "127.8.9.10:1",
        "127.0.0.2:8765",
        "[::ffff:127.0.0.1]",
        "[::ffff:127.0.0.1]:8765",
        "[0:0:0:0:0:0:0:1]",
        "[::1%lo]",
        "[localhost]",
        "192.168.1.10:8765",
        "0.0.0.0",
        "[2001:db8::1]:8765",
        "::1",
        "[::1]x",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:port",
        "127.0.0.1:8765:1",
        "[::1]:",
    ],
)
def test_non_loopback_or_malformed_hosts_are_refused(host: str | None) -> None:
    assert security.host_allowed(host) is False


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("127.0.0.1:8765", 8765, True),
        ("localhost:8765", 8765, True),
        ("[::1]:8765", 8765, True),
        # The bound port must be named explicitly (design §21.4).
        ("127.0.0.1", 8765, False),
        ("[::1]", 8765, False),
        ("127.0.0.1:9999", 8765, False),
        ("[::1]:9999", 8765, False),
    ],
)
def test_host_must_name_the_bound_port(host: str, port: int, expected: bool) -> None:
    assert security.host_allowed(host, port=port) is expected


@pytest.mark.parametrize(
    ("origin", "host", "expected"),
    [
        ("http://127.0.0.1:8765", "127.0.0.1:8765", True),
        ("http://127.0.0.1", "127.0.0.1", True),
        ("http://localhost:8765", "localhost:8765", True),
        ("http://[::1]:8765", "[::1]:8765", True),
        ("HTTP://127.0.0.1:8765", "127.0.0.1:8765", True),
        # Any other port, host or scheme is cross-origin even on loopback.
        ("http://127.0.0.1:9999", "127.0.0.1:8765", False),
        ("http://localhost:8765", "127.0.0.1:8765", False),
        ("http://127.0.0.1:8765", "localhost:8765", False),
        ("https://127.0.0.1:8765", "127.0.0.1:8765", False),
        ("http://127.0.0.1", "127.0.0.1:8765", False),
        ("null", "127.0.0.1:8765", False),
        ("", "127.0.0.1:8765", False),
        ("http://127.0.0.1:8765/path", "127.0.0.1:8765", False),
    ],
)
def test_origin_must_match_the_request_origin_exactly(
    origin: str, host: str, expected: bool
) -> None:
    assert security.origin_matches(origin, scheme="http", host=host) is expected


@pytest.mark.parametrize(
    ("value", "allowed"),
    [
        (None, True),
        ("same-origin", True),
        ("none", True),
        ("cross-site", False),
        ("same-site", False),
        ("", False),
        ("SAME-ORIGIN ", False),
    ],
)
def test_sec_fetch_site_allows_only_same_origin_or_none(
    value: str | None, allowed: bool
) -> None:
    assert security.fetch_site_allowed(value) is allowed


def test_token_comparison_uses_constant_time_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = security.hmac.compare_digest

    def spy(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return real(left, right)

    monkeypatch.setattr(security.hmac, "compare_digest", spy)

    assert security.token_matches("abc", "abc") is True
    assert security.token_matches("abd", "abc") is False
    assert security.token_matches(None, "abc") is False
    assert len(calls) == 2


# --------------------------------------------------------------------------
# integration through the app
# --------------------------------------------------------------------------


@pytest.fixture
def plain_client(client: TestClient) -> TestClient:
    """Same app (and therefore the same token) as the ``token`` fixture."""
    return client


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.1:8765", "localhost:8765", "[::1]:8765", "[::1]"],
)
def test_loopback_hosts_reach_the_api(plain_client: TestClient, host: str) -> None:
    response = plain_client.get("/api/session", headers={"Host": host})

    assert response.status_code == 200


def test_host_without_the_bound_port_is_refused_when_port_is_known(
    repo: Path,
) -> None:
    with TestClient(create_app(repo, port=8765), base_url=LOOPBACK_BASE) as client:
        accepted = client.get("/api/session", headers={"Host": "127.0.0.1:8765"})
        other_port = client.get("/api/session", headers={"Host": "127.0.0.1:9999"})
        no_port = client.get("/api/session", headers={"Host": "127.0.0.1"})

    assert accepted.status_code == 200
    assert other_port.status_code == 403
    assert no_port.status_code == 403


def test_static_assets_need_no_token_but_api_does(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>x</title>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    with TestClient(create_app(repo), base_url=LOOPBACK_BASE) as client:
        asset = client.get("/assets/app.js")
        index = client.get("/")
        api = client.get("/api/documents")

    assert asset.status_code == 200
    assert index.status_code == 200
    # Reads need no token; only mutations carry X-GREGraph-Token (driver contract).
    assert api.status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "192.168.1.5"])
def test_dns_rebinding_host_is_refused_on_every_route(
    plain_client: TestClient, host: str
) -> None:
    for path in ("/", "/api/session", "/api/documents", "/api/status"):
        response = plain_client.get(path, headers={"Host": host})
        assert response.status_code == 403, path
        assert error_code(response) == "E-REQUEST-REFUSED", path


def test_mutation_with_rebound_host_is_refused_before_token_check(
    plain_client: TestClient,
) -> None:
    response = plain_client.post(
        "/api/documents",
        json={"type": "user-story", "title": "X", "tags": []},
        headers={"Host": "evil.example"},
    )

    assert response.status_code == 403


def test_cross_port_origin_is_refused(plain_client: TestClient) -> None:
    response = plain_client.get(
        "/api/session", headers={"Origin": "http://127.0.0.1:9999"}
    )

    assert response.status_code == 403
    assert error_code(response) == "E-REQUEST-REFUSED"


def test_null_and_foreign_origins_are_refused(plain_client: TestClient) -> None:
    for origin in ("null", "https://evil.example", "http://localhost:1"):
        response = plain_client.get("/api/session", headers={"Origin": origin})
        assert response.status_code == 403, origin


def test_exact_origin_is_accepted(plain_client: TestClient) -> None:
    response = plain_client.get("/api/session", headers={"Origin": "http://127.0.0.1"})

    assert response.status_code == 200


def test_cross_site_fetch_is_refused_on_session_get(plain_client: TestClient) -> None:
    for value in ("cross-site", "same-site"):
        response = plain_client.get("/api/session", headers={"Sec-Fetch-Site": value})
        assert response.status_code == 403, value


def test_same_origin_fetch_is_accepted(plain_client: TestClient) -> None:
    response = plain_client.get(
        "/api/session", headers={"Sec-Fetch-Site": "same-origin"}
    )

    assert response.status_code == 200


def test_token_is_required_for_every_mutation(
    plain_client: TestClient, repo: Path
) -> None:
    doc_id = add_document(repo, type="feature", title="Knowledge base")
    cases = [
        ("post", "/api/documents", {"type": "feature", "title": "X", "tags": []}),
        ("patch", f"/api/documents/{doc_id}/meta", {"tags": ["a"]}),
        (
            "post",
            "/api/links",
            {"source": doc_id, "type": "relates-to", "target": doc_id},
        ),
        ("delete", f"/api/links/{doc_id}/relates-to/{doc_id}", None),
    ]
    for method, path, payload in cases:
        headers = {"Content-Type": "application/json"}
        response = plain_client.request(method, path, json=payload, headers=headers)
        assert response.status_code == 403, path
        assert error_code(response) == "E-TOKEN-INVALID", path


def test_wrong_token_is_refused(plain_client: TestClient) -> None:
    response = plain_client.post(
        "/api/documents",
        json={"type": "feature", "title": "X", "tags": []},
        headers=auth("not-the-token"),
    )

    assert response.status_code == 403
    assert error_code(response) == "E-TOKEN-INVALID"


def test_token_from_one_app_does_not_work_on_another(
    repo: Path, tmp_path: Path
) -> None:
    from gregraph.core.operations import init_repository

    other = tmp_path / "other"
    other.mkdir()
    init_repository(other, no_git=True)
    with (
        TestClient(create_app(repo), base_url=LOOPBACK_BASE) as first,
        TestClient(create_app(other), base_url=LOOPBACK_BASE) as second,
    ):
        foreign = first.get("/api/session").json()["csrf_token"]
        response = second.post(
            "/api/documents",
            json={"type": "feature", "title": "X", "tags": []},
            headers=auth(foreign),
        )

    assert response.status_code == 403


def test_mutation_requires_json_content_type(
    plain_client: TestClient, token: str
) -> None:
    body = b'{"type":"feature","title":"X","tags":[]}'
    for content_type in ("text/plain", "application/x-www-form-urlencoded", None):
        headers = {TOKEN_HEADER: token}
        if content_type is not None:
            headers["Content-Type"] = content_type
        response = plain_client.post("/api/documents", content=body, headers=headers)
        assert response.status_code == 415, content_type
        assert error_code(response) == "E-CONTENT-TYPE"


def test_json_content_type_with_parameters_is_accepted(
    plain_client: TestClient, token: str
) -> None:
    response = plain_client.post(
        "/api/documents",
        content=b'{"type":"feature","title":"X","tags":[]}',
        headers={
            TOKEN_HEADER: token,
            "Content-Type": "Application/JSON; charset=utf-8",
        },
    )

    assert response.status_code == 201


def test_declared_oversize_body_is_refused_without_reading(
    plain_client: TestClient, token: str
) -> None:
    response = plain_client.post(
        "/api/documents",
        content=b"{}",
        headers={
            TOKEN_HEADER: token,
            "Content-Type": "application/json",
            "Content-Length": str(MIB + 1),
        },
    )

    assert response.status_code == 413
    assert error_code(response) == "E-BODY-TOO-LARGE"


def test_chunked_oversize_body_is_refused_while_streaming(
    plain_client: TestClient, token: str
) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"type":"feature","title":"'
        for _ in range(3):
            yield b"x" * (MIB // 2)
        yield b'","tags":[]}'

    response = plain_client.post(
        "/api/documents",
        content=chunks(),
        headers={TOKEN_HEADER: token, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert "Content-Length" not in response.request.headers


def test_body_at_the_limit_is_read_and_then_validated(
    plain_client: TestClient, token: str
) -> None:
    padding = "x" * (MIB - 100)
    payload = f'{{"type":"feature","title":"{padding}","tags":[]}}'.encode()
    assert len(payload) <= MIB

    response = plain_client.post(
        "/api/documents",
        content=payload,
        headers={TOKEN_HEADER: token, "Content-Type": "application/json"},
    )

    # Within the byte cap: the request is parsed; the long title fails validation.
    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"


def test_security_headers_are_present_on_every_response(
    plain_client: TestClient,
) -> None:
    for path in ("/api/session", "/api/nope", "/"):
        response = plain_client.get(path)
        assert response.headers["content-security-policy"] == security.CSP, path
        assert response.headers["x-content-type-options"] == "nosniff", path
        assert response.headers["referrer-policy"] == "no-referrer", path
        assert response.headers["x-frame-options"] == "DENY", path


def test_api_responses_are_no_store(plain_client: TestClient) -> None:
    response = plain_client.get("/api/status")

    assert response.headers["cache-control"] == "no-store"


def test_csp_is_the_designed_policy() -> None:
    assert security.CSP == (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
        "object-src 'none'"
    )


def test_no_cors_headers_are_ever_emitted(plain_client: TestClient) -> None:
    preflight = plain_client.options(
        "/api/documents",
        headers={
            "Origin": "http://127.0.0.1",
            "Access-Control-Request-Method": "POST",
        },
    )
    simple = plain_client.get("/api/session", headers={"Origin": "http://127.0.0.1"})

    for response in (preflight, simple):
        assert "access-control-allow-origin" not in response.headers


# --------------------------------------------------------------------------
# hardening: ambiguous or hostile headers, encodings, non-ASCII tokens
# --------------------------------------------------------------------------


def test_non_ascii_token_is_403_not_500(plain_client: TestClient, token: str) -> None:
    # httpx refuses non-ASCII str header values, so send raw UTF-8 bytes instead.
    for hostile in ("tökén", token + "é", "é" * 300):
        response = plain_client.post(
            "/api/documents",
            json={"type": "feature", "title": "X", "tags": []},
            headers=[
                (TOKEN_HEADER.encode(), hostile.encode("utf-8")),
                (b"Content-Type", b"application/json"),
            ],
        )
        assert response.status_code == 403, hostile
        assert error_code(response) == "E-TOKEN-INVALID", hostile


def test_token_comparison_is_utf8_safe() -> None:
    assert security.token_matches("é", "é") is True
    assert security.token_matches("é", "e") is False
    assert security.token_matches("\udcff", "abc") is False  # lone surrogate


def test_duplicate_host_header_is_refused(plain_client: TestClient) -> None:
    response = plain_client.get(
        "/api/session", headers=[("Host", "127.0.0.1"), ("Host", "127.0.0.1")]
    )

    assert response.status_code == 403


def test_duplicate_origin_header_is_refused(plain_client: TestClient) -> None:
    response = plain_client.get(
        "/api/session",
        headers=[("Origin", "http://127.0.0.1"), ("Origin", "http://127.0.0.1")],
    )

    assert response.status_code == 403


def test_duplicate_sec_fetch_site_is_refused(plain_client: TestClient) -> None:
    response = plain_client.get(
        "/api/session",
        headers=[("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "same-origin")],
    )

    assert response.status_code == 403


def test_duplicate_token_header_is_refused(
    plain_client: TestClient, token: str
) -> None:
    response = plain_client.post(
        "/api/documents",
        json={"type": "feature", "title": "X", "tags": []},
        headers=[
            (TOKEN_HEADER, token),
            (TOKEN_HEADER, token),
            ("Content-Type", "application/json"),
        ],
    )

    assert response.status_code == 403
    assert error_code(response) == "E-TOKEN-INVALID"


def test_missing_host_is_refused(plain_client: TestClient) -> None:
    from gregraph.webui.security import host_allowed

    assert host_allowed(None) is False
    response = plain_client.request("GET", "/api/session", headers=[("Host", "")])
    assert response.status_code == 403


def test_origin_null_and_crossport_are_refused_on_mutations(
    plain_client: TestClient, token: str
) -> None:
    for origin in ("null", "http://127.0.0.1:1"):
        response = plain_client.post(
            "/api/documents",
            json={"type": "feature", "title": "X", "tags": []},
            headers={
                TOKEN_HEADER: token,
                "Content-Type": "application/json",
                "Origin": origin,
            },
        )
        assert response.status_code == 403, origin


def test_content_encoding_on_mutation_is_refused(
    plain_client: TestClient, token: str
) -> None:
    import gzip

    body = gzip.compress(b'{"type":"feature","title":"X","tags":[]}')
    response = plain_client.post(
        "/api/documents",
        content=body,
        headers={
            TOKEN_HEADER: token,
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    )

    assert response.status_code == 415
    assert error_code(response) == "E-CONTENT-ENCODING"


def test_identity_content_encoding_is_still_refused_on_mutation(
    plain_client: TestClient, token: str
) -> None:
    response = plain_client.post(
        "/api/documents",
        json={"type": "feature", "title": "X", "tags": []},
        headers={TOKEN_HEADER: token, "Content-Encoding": "identity"},
    )

    assert response.status_code == 415


def test_token_in_query_string_is_not_accepted(
    plain_client: TestClient, token: str
) -> None:
    response = plain_client.post(
        f"/api/documents?csrf_token={token}&X-GREGraph-Token={token}",
        json={"type": "feature", "title": "X", "tags": []},
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 403


def test_forwarded_headers_do_not_change_origin_decisions(
    plain_client: TestClient,
) -> None:
    response = plain_client.get(
        "/api/session",
        headers={
            "X-Forwarded-Host": "evil.example",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "203.0.113.9",
            "Forwarded": "host=evil.example;proto=https",
            "Origin": "https://evil.example",
        },
    )

    assert response.status_code == 403


def test_responses_do_not_advertise_the_server_software(
    plain_client: TestClient,
) -> None:
    response = plain_client.get("/api/session")

    assert "server" not in response.headers


def test_session_token_is_only_in_the_json_body(plain_client: TestClient) -> None:
    response = plain_client.get("/api/session")

    assert "csrf_token" in response.json()
    assert "token" not in response.headers.get("location", "")
    assert "X-GREGraph-Token" not in response.headers


# --------------------------------------------------------------------------
# default HTTP port: browsers omit ":80" in Host (boundary case, design §21.4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("127.0.0.1", 80, True),
        ("localhost", 80, True),
        ("[::1]", 80, True),
        ("127.0.0.1:80", 80, True),
        # Only the HTTP default is implied; other ports still need the explicit value.
        ("127.0.0.1", 8765, False),
        ("localhost", 8765, False),
        ("127.0.0.1:80", 8765, False),
        ("127.0.0.1:8765", 80, False),
        ("127.0.0.1:443", 80, False),
    ],
)
def test_default_http_port_is_implied_only_when_bound_to_80(
    host: str, port: int, expected: bool
) -> None:
    assert security.host_allowed(host, port=port) is expected


def test_bound_port_80_serves_browser_host_headers(repo: Path) -> None:
    with TestClient(create_app(repo, port=80), base_url=LOOPBACK_BASE) as client:
        plain = client.get("/api/session")
        named = client.get("/api/session", headers={"Host": "localhost"})
        explicit = client.get("/api/session", headers={"Host": "127.0.0.1:80"})
        wrong = client.get("/api/session", headers={"Host": "127.0.0.1:8080"})

    assert plain.status_code == 200
    assert named.status_code == 200
    assert explicit.status_code == 200
    assert wrong.status_code == 403


def test_bound_port_8765_still_requires_the_explicit_port(repo: Path) -> None:
    with TestClient(create_app(repo, port=8765), base_url=LOOPBACK_BASE) as client:
        missing = client.get("/api/session")
        localhost = client.get("/api/session", headers={"Host": "localhost"})
        explicit = client.get("/api/session", headers={"Host": "127.0.0.1:8765"})

    assert missing.status_code == 403
    assert localhost.status_code == 403
    assert explicit.status_code == 200


def test_origin_does_not_widen_for_the_default_port(repo: Path) -> None:
    with TestClient(create_app(repo, port=80), base_url=LOOPBACK_BASE) as client:
        same = client.get("/api/session", headers={"Origin": "http://127.0.0.1"})
        cross = client.get("/api/session", headers={"Origin": "http://127.0.0.1:8080"})

    assert same.status_code == 200
    assert cross.status_code == 403


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.1:8765",
        "localhost",
        "LocalHost:8765",
        "[::1]",
        "[::1]:8765",
    ],
)
def test_canonical_loopback_names_are_accepted(host: str) -> None:
    assert security.host_allowed(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.2",
        "127.20.30.40",
        "[::ffff:127.0.0.1]",
        "[0:0:0:0:0:0:0:1]",
    ],
)
def test_other_loopback_spellings_are_refused_on_the_wire(
    plain_client: TestClient, host: str
) -> None:
    response = plain_client.get("/api/session", headers={"Host": host})

    assert response.status_code == 403
