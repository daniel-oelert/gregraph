"""Mutation endpoints: create, body update, meta, links (contract + refusals).

``PUT /api/documents/{id}/body`` depends on the core ``update_body`` operation
(spec §5.2, §5.6) which lands in ``operations.py``; those tests are written
against that agreed interface and will fail until it exists.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webui_support import add_document, auth, error_code

from gregraph.core import operations
from gregraph.core.hashing import body_hash
from gregraph.core.models import Finding, OperationRefused
from gregraph.core.storage import find_document, read_body
from gregraph.webui import app as app_module


def _create(client: TestClient, token: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"type": "user-story", "title": "Upload", "tags": []}
    payload.update(overrides)
    response = client.post("/api/documents", json=payload, headers=auth(token))
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------


def test_create_document_returns_201_with_id_notices_and_findings(
    client: TestClient, token: str, repo: Path
) -> None:
    response = client.post(
        "/api/documents",
        json={"type": "feature", "title": "Knowledge base", "tags": ["kb"]},
        headers=auth(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "notices", "findings"}
    assert body["id"].startswith("RE-")
    assert body["notices"] == [] or all(isinstance(n, str) for n in body["notices"])
    assert isinstance(body["findings"], list)
    entry = find_document(repo, body["id"])
    assert entry is not None
    assert "# Knowledge base" in read_body(entry.body)


def test_create_document_persists_tags(
    client: TestClient, token: str, repo: Path
) -> None:
    created = _create(client, token, tags=["kb", "upload"])

    listing = client.get("/api/documents").json()["items"]
    item = next(entry for entry in listing if entry["id"] == created["id"])
    assert item["tags"] == ["kb", "upload"]


def test_create_unknown_type_is_refused_with_envelope(
    client: TestClient, token: str
) -> None:
    response = client.post(
        "/api/documents",
        json={"type": "no-such-type", "title": "X", "tags": []},
        headers=auth(token),
    )

    assert response.status_code == 409
    assert error_code(response) == "E-TYPE-UNKNOWN"


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "feature", "title": "X", "tags": [], "extra": 1},
        {"type": "feature", "title": "", "tags": []},
        {"type": "feature", "title": "Line\nBreak", "tags": []},
        {"type": "feature", "title": "X", "tags": ["Upper"]},
        {"type": "feature", "title": "X", "tags": ["a,b"]},
        {"type": "feature", "title": "X", "tags": [f"t{i}" for i in range(200)]},
        {"type": "feature", "title": "X"},
        {"type": "Not A Type", "title": "X", "tags": []},
    ],
)
def test_create_request_is_validated_strictly(
    client: TestClient, token: str, payload: dict[str, object]
) -> None:
    response = client.post("/api/documents", json=payload, headers=auth(token))

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"
    assert "Traceback" not in response.text


def test_malformed_json_is_a_400_envelope(client: TestClient, token: str) -> None:
    response = client.post(
        "/api/documents",
        content=b'{"type": ',
        headers={"Content-Type": "application/json", "X-GREGraph-Token": token},
    )

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"


# --------------------------------------------------------------------------
# meta (tags) and links
# --------------------------------------------------------------------------


def test_patch_meta_replaces_tags(client: TestClient, token: str) -> None:
    doc_id = _create(client, token)["id"]

    response = client.patch(
        f"/api/documents/{doc_id}/meta",
        json={"tags": ["alpha", "beta"]},
        headers=auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "tags", "notices"}
    assert body["id"] == doc_id
    assert body["tags"] == ["alpha", "beta"]


def test_patch_meta_with_empty_list_clears_tags(client: TestClient, token: str) -> None:
    doc_id = _create(client, token, tags=["alpha"])["id"]

    response = client.patch(
        f"/api/documents/{doc_id}/meta", json={"tags": []}, headers=auth(token)
    )

    assert response.status_code == 200
    assert response.json()["tags"] == []


def test_patch_meta_refuses_non_tag_fields(client: TestClient, token: str) -> None:
    doc_id = _create(client, token)["id"]

    response = client.patch(
        f"/api/documents/{doc_id}/meta",
        json={"title": "Renamed"},
        headers=auth(token),
    )

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"


def test_link_create_and_duplicate_notice(client: TestClient, token: str) -> None:
    feature = _create(client, token, type="feature", title="Knowledge base")["id"]
    story = _create(client, token)["id"]
    payload = {"source": story, "type": "refines", "target": feature}

    first = client.post("/api/links", json=payload, headers=auth(token))
    second = client.post("/api/links", json=payload, headers=auth(token))

    assert first.status_code == 200
    assert first.json()["created"] is True
    assert set(first.json()) == {"created", "notices"}
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["notices"]


def test_link_cycle_is_refused_as_409(client: TestClient, token: str) -> None:
    feature = _create(client, token, type="feature", title="Knowledge base")["id"]
    story = _create(client, token)["id"]
    client.post(
        "/api/links",
        json={"source": story, "type": "refines", "target": feature},
        headers=auth(token),
    )

    response = client.post(
        "/api/links",
        json={"source": feature, "type": "refines", "target": story},
        headers=auth(token),
    )

    assert response.status_code == 409
    assert error_code(response) == "E-CYCLE"


def test_link_rule_violation_is_409(client: TestClient, token: str) -> None:
    goal = _create(client, token, type="goal", title="Goal")["id"]
    story = _create(client, token)["id"]

    response = client.post(
        "/api/links",
        json={"source": story, "type": "verifies", "target": goal},
        headers=auth(token),
    )

    assert response.status_code == 409
    assert error_code(response) == "E-EDGE-RULE"


def test_link_rejects_unknown_link_type_before_core(
    client: TestClient, token: str
) -> None:
    doc_id = _create(client, token)["id"]

    response = client.post(
        "/api/links",
        json={"source": doc_id, "type": "owns", "target": doc_id},
        headers=auth(token),
    )

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"


def test_unlink_removes_the_edge(client: TestClient, token: str) -> None:
    feature = _create(client, token, type="feature", title="Knowledge base")["id"]
    story = _create(client, token)["id"]
    client.post(
        "/api/links",
        json={"source": story, "type": "refines", "target": feature},
        headers=auth(token),
    )

    response = client.delete(
        f"/api/links/{story}/refines/{feature}",
        headers={"X-GREGraph-Token": token, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert set(response.json()) == {"removed", "notices"}
    assert response.json()["removed"] is True
    outbound = client.get(f"/api/documents/{story}").json()["outbound"]
    assert outbound == []


def test_unlink_missing_edge_is_a_notice_not_an_error(
    client: TestClient, token: str
) -> None:
    feature = _create(client, token, type="feature", title="Knowledge base")["id"]
    story = _create(client, token)["id"]

    response = client.delete(
        f"/api/links/{story}/refines/{feature}",
        headers={"X-GREGraph-Token": token, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["removed"] is False


def test_unlink_unknown_type_in_path_is_refused_cleanly(
    client: TestClient, token: str
) -> None:
    doc_id = _create(client, token)["id"]

    response = client.delete(
        f"/api/links/{doc_id}/owns/{doc_id}",
        headers={"X-GREGraph-Token": token, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"


def test_delete_still_requires_json_content_type(
    client: TestClient, token: str
) -> None:
    doc_id = _create(client, token)["id"]

    response = client.delete(
        f"/api/links/{doc_id}/relates-to/{doc_id}",
        headers={"X-GREGraph-Token": token},
    )

    assert response.status_code == 415


# --------------------------------------------------------------------------
# body update (core update_body, spec §5.2, §5.6)
# --------------------------------------------------------------------------


def _current_hash(client: TestClient, doc_id: str) -> str:
    detail: dict[str, str] = client.get(f"/api/documents/{doc_id}").json()
    return detail["body_hash"]


def test_put_body_writes_text_and_syncs_title(client: TestClient, token: str) -> None:
    doc_id = _create(client, token)["id"]
    base_hash = _current_hash(client, doc_id)
    text = "# Renamed story\n\n## Story\n\nNew prose.\n"

    response = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": text, "base_hash": base_hash},
        headers=auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "body_hash", "title", "changed", "findings"}
    assert body["id"] == doc_id
    assert body["title"] == "Renamed story"
    assert body["changed"] is True
    assert body["body_hash"] == body_hash(text)
    readback = client.get(f"/api/documents/{doc_id}").json()
    assert readback["body_text"] == text
    assert readback["title"] == "Renamed story"


def test_put_body_with_stale_base_hash_is_409_and_writes_nothing(
    client: TestClient, token: str, repo: Path
) -> None:
    doc_id = _create(client, token)["id"]
    entry = find_document(repo, doc_id)
    assert entry is not None
    before = entry.body.read_bytes()

    response = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# Overwrite\n", "base_hash": "sha256:" + "0" * 64},
        headers=auth(token),
    )

    assert response.status_code == 409
    assert error_code(response) == "E-BODY-STALE"
    assert entry.body.read_bytes() == before


def test_second_put_with_the_same_base_hash_is_refused(
    client: TestClient, token: str
) -> None:
    doc_id = _create(client, token)["id"]
    base_hash = _current_hash(client, doc_id)
    first = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# One\n", "base_hash": base_hash},
        headers=auth(token),
    )
    second = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# Two\n", "base_hash": base_hash},
        headers=auth(token),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert error_code(second) == "E-BODY-STALE"


def test_put_body_unknown_id_is_404(client: TestClient, token: str) -> None:
    response = client.put(
        "/api/documents/RE-ZZZZZZ/body",
        json={"text": "# X\n", "base_hash": "sha256:" + "0" * 64},
        headers=auth(token),
    )

    assert response.status_code == 404
    assert error_code(response) == "E-ID-UNKNOWN"


def test_put_body_rejects_unknown_fields_and_huge_text(
    client: TestClient, token: str
) -> None:
    doc_id = _create(client, token)["id"]
    base_hash = _current_hash(client, doc_id)

    extra = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# X\n", "base_hash": base_hash, "version": 9},
        headers=auth(token),
    )
    missing = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# X\n"},
        headers=auth(token),
    )

    assert extra.status_code == 400 and error_code(extra) == "E-REQUEST-INVALID"
    assert missing.status_code == 400 and error_code(missing) == "E-REQUEST-INVALID"


def test_put_body_declared_oversize_is_413(client: TestClient, token: str) -> None:
    doc_id = _create(client, token)["id"]
    response = client.put(
        f"/api/documents/{doc_id}/body",
        content=b"{}",
        headers={
            "X-GREGraph-Token": token,
            "Content-Type": "application/json",
            "Content-Length": str(1024 * 1024 + 1),
        },
    )

    assert response.status_code == 413


# --------------------------------------------------------------------------
# whole-process lock (no half-written reads during mutation)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operation",
    [
        "list_documents",
        "show_document",
        "status",
        "validate",
        "create_document",
        "set_fields",
        "link",
        "unlink",
    ],
)
def test_every_workspace_operation_runs_under_the_app_lock(
    client: TestClient,
    token: str,
    repo: Path,
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = client.app.state.lock  # type: ignore[attr-defined]
    held: list[bool] = []
    real = getattr(operations, operation)

    def spy(*args: object, **kwargs: object) -> object:
        held.append(bool(lock.locked()))
        return real(*args, **kwargs)

    monkeypatch.setattr(operations, operation, spy)
    feature = add_document(repo, type="feature", title="Knowledge base")
    story = add_document(repo, type="user-story", title="Upload")
    routes = {
        "list_documents": lambda: client.get("/api/documents"),
        "show_document": lambda: client.get(f"/api/documents/{story}"),
        "status": lambda: client.get("/api/status"),
        "validate": lambda: client.get("/api/validate"),
        "create_document": lambda: client.post(
            "/api/documents",
            json={"type": "feature", "title": "X", "tags": []},
            headers=auth(token),
        ),
        "set_fields": lambda: client.patch(
            f"/api/documents/{story}/meta",
            json={"tags": ["a"]},
            headers=auth(token),
        ),
        "link": lambda: client.post(
            "/api/links",
            json={"source": story, "type": "refines", "target": feature},
            headers=auth(token),
        ),
        "unlink": lambda: client.delete(
            f"/api/links/{story}/refines/{feature}",
            headers={"X-GREGraph-Token": token, "Content-Type": "application/json"},
        ),
    }

    response = routes[operation]()

    assert response.status_code < 500, response.text
    assert held == [True]


def test_graph_route_runs_under_the_app_lock(
    client: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = client.app.state.lock  # type: ignore[attr-defined]
    held: list[bool] = []
    real = app_module._graph_payload

    def spy(ws: object) -> dict[str, object]:
        held.append(bool(lock.locked()))
        return real(ws)  # type: ignore[arg-type]

    monkeypatch.setattr(app_module, "_graph_payload", spy)

    assert client.get("/api/graph").status_code == 200
    assert held == [True]


def test_mutations_are_serialised_across_threads(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent reads cannot overlap a write: the lock is one per app."""
    from gregraph.webui.app import create_app

    app = create_app(repo)
    active = 0
    peak = 0
    guard = threading.Lock()
    real = operations.list_documents

    def slow(*args: object, **kwargs: object) -> object:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            return real(*args, **kwargs)  # type: ignore[arg-type]
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(operations, "list_documents", slow)
    from starlette.testclient import TestClient as _Client

    def worker() -> None:
        with _Client(app, base_url="http://127.0.0.1") as client:
            client.get("/api/documents")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1


# --------------------------------------------------------------------------
# error mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("E-ID-UNKNOWN", 404),
        ("E-PATH-UNSAFE", 400),
        ("E-CYCLE", 409),
        ("E-BODY-STALE", 409),
    ],
)
def test_refusals_map_to_status_by_code(
    client: TestClient,
    token: str,
    repo: Path,
    code: str,
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise OperationRefused(
            Finding(code=code, severity="E", subject="RE-ABCDEF", message="no")
        )

    monkeypatch.setattr(operations, "list_documents", refuse)

    response = client.get("/api/documents")

    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["severity"] == "E"
    assert error["doc_id"] == "RE-ABCDEF"
    assert error["path"] is None


def test_path_subject_finding_serialises_as_path(
    client: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise OperationRefused(
            Finding(
                code="E-PATH-UNSAFE",
                severity="E",
                subject=Path("documents/x.md"),
                message="unsafe",
                fix="gregraph sync",
            )
        )

    monkeypatch.setattr(operations, "list_documents", refuse)

    response = client.get("/api/documents")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["path"] == "documents/x.md"
    assert error["doc_id"] is None
    assert error["fix"] == "gregraph sync"


def test_unexpected_exception_is_generic_500_without_traceback(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.testclient import TestClient as _Client

    from gregraph.webui.app import create_app

    def explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError("secret detail at /home/someone/private")

    monkeypatch.setattr(operations, "list_documents", explode)
    with _Client(
        create_app(repo), base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as client:
        response = client.get("/api/documents")

    assert response.status_code == 500
    assert error_code(response) == "E-INTERNAL"
    assert "secret" not in response.text
    assert "Traceback" not in response.text
    assert str(repo) not in response.text


def test_unknown_api_route_is_json_404_not_the_index(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert error_code(response) == "E-NOT-FOUND"


def test_wrong_method_is_json_405(client: TestClient) -> None:
    response = client.get("/api/links/RE-ABCDEF/refines/RE-ABCDEF")

    assert response.status_code == 405
    assert error_code(response) == "E-METHOD-NOT-ALLOWED"


def test_workspace_is_opened_per_request(client: TestClient, repo: Path) -> None:
    before = client.get("/api/documents").json()["items"]
    add_document(repo, type="feature", title="Late arrival")

    after = client.get("/api/documents").json()["items"]

    assert len(after) == len(before) + 1


# --------------------------------------------------------------------------
# base_hash must describe the body on disk, not the stale sidecar hash
# --------------------------------------------------------------------------


def _sidecar_state(repo: Path, doc_id: str) -> tuple[str, int]:
    from gregraph.core.models import Document
    from gregraph.core.storage import read_sidecar

    entry = find_document(repo, doc_id)
    assert entry is not None
    document = read_sidecar(entry.sidecar, Document)
    return document.body_hash, document.version


def test_get_hash_is_the_working_tree_body_so_a_second_save_succeeds(
    client: TestClient, token: str, repo: Path
) -> None:
    from gregraph.core.hashing import body_hash as core_body_hash

    doc_id = _create(client, token)["id"]
    sidecar_before = _sidecar_state(repo, doc_id)
    first_hash = _current_hash(client, doc_id)
    first = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# First edit\n\nProse one.\n", "base_hash": first_hash},
        headers=auth(token),
    )
    assert first.status_code == 200, first.text

    detail = client.get(f"/api/documents/{doc_id}").json()

    # The hash is of the body on disk now, not the sidecar, which lags (spec §21.5).
    assert detail["body_hash"] == core_body_hash(detail["body_text"])
    assert detail["body_hash"] != sidecar_before[0]
    second = client.put(
        f"/api/documents/{doc_id}/body",
        json={
            "text": "# Second edit\n\nProse two.\n",
            "base_hash": detail["body_hash"],
        },
        headers=auth(token),
    )
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is True


def test_sidecar_hash_and_version_are_untouched_by_saves(
    client: TestClient, token: str, repo: Path
) -> None:
    doc_id = _create(client, token)["id"]
    before = _sidecar_state(repo, doc_id)

    response = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# Edited\n\nNew.\n", "base_hash": _current_hash(client, doc_id)},
        headers=auth(token),
    )

    assert response.status_code == 200
    assert _sidecar_state(repo, doc_id) == before


def test_external_body_edit_is_visible_in_the_next_get_hash(
    client: TestClient, token: str, repo: Path
) -> None:
    """A CLI or editor edit changes the file only; the next GET must return a
    hash the browser can save with, not the stale sidecar hash (spec §21.5)."""
    from gregraph.core.hashing import body_hash as core_body_hash

    doc_id = _create(client, token)["id"]
    entry = find_document(repo, doc_id)
    assert entry is not None
    entry.body.write_text("# Edited outside\n\nFrom an editor.\n", encoding="utf-8")
    before = _sidecar_state(repo, doc_id)

    detail = client.get(f"/api/documents/{doc_id}").json()
    response = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# Saved from browser\n", "base_hash": detail["body_hash"]},
        headers=auth(token),
    )

    assert detail["body_hash"] == core_body_hash(
        "# Edited outside\n\nFrom an editor.\n"
    )
    assert response.status_code == 200, response.text
    assert _sidecar_state(repo, doc_id) == before
