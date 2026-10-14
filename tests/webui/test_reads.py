"""Read endpoints: documents, status, validate, graph (frontend contract, spec §13)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from webui_support import add_document, error_code

from gregraph.core.operations import link, sync
from gregraph.core.storage import find_document
from gregraph.core.workspace import Workspace
from gregraph.webui import app as app_module


def _snapshot(root: Path) -> dict[str, bytes]:
    """Every file under the repository, including Git and cache state."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_documents_list_has_item_shape_and_notices(
    client: TestClient, repo: Path
) -> None:
    doc_id = add_document(repo, type="user-story", title="Upload documents")

    response = client.get("/api/documents")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "notices"}
    assert isinstance(body["notices"], list)
    item = next(entry for entry in body["items"] if entry["id"] == doc_id)
    assert set(item) == {"id", "type", "kind", "status", "version", "title", "tags"}
    assert item["type"] == "user-story"
    assert item["kind"] == "requirement"
    assert item["version"] == 1
    assert item["title"] == "Upload documents"
    assert item["tags"] == []


def test_documents_list_filters_by_type_status_and_text(
    client: TestClient, repo: Path
) -> None:
    story = add_document(repo, type="user-story", title="Upload documents")
    feature = add_document(repo, type="feature", title="Knowledge base")

    by_type = client.get("/api/documents", params={"type": "feature"}).json()
    assert [item["id"] for item in by_type["items"]] == [feature]

    by_text = client.get("/api/documents", params={"q": "UPLOAD"}).json()
    assert [item["id"] for item in by_text["items"]] == [story]

    by_id = client.get("/api/documents", params={"q": feature.lower()}).json()
    assert [item["id"] for item in by_id["items"]] == [feature]

    by_status = client.get("/api/documents", params={"status": "draft"}).json()
    assert {item["status"] for item in by_status["items"]} <= {"draft", "unknown"}


def test_documents_list_rejects_oversized_query(client: TestClient) -> None:
    response = client.get("/api/documents", params={"q": "x" * 500})

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"


def test_document_detail_has_contract_fields(client: TestClient, repo: Path) -> None:
    doc_id = add_document(repo, type="user-story", title="Upload documents")

    response = client.get(f"/api/documents/{doc_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "type",
        "kind",
        "status",
        "version",
        "title",
        "tags",
        "body_text",
        "body_hash",
        "outbound",
        "inbound",
        "notices",
    }
    assert body["id"] == doc_id
    assert body["title"] == "Upload documents"
    assert body["body_text"].startswith("# Upload documents")
    assert body["body_hash"].startswith("sha256:")
    assert body["outbound"] == [] and body["inbound"] == []


def test_document_detail_maps_outdated_links(client: TestClient, repo: Path) -> None:
    feature = add_document(repo, type="feature", title="Knowledge base")
    story = add_document(repo, type="user-story", title="Upload documents")
    link(Workspace.open(repo), source=story, link_type="refines", target=feature)
    # Edit the target and bump it: the link still records version 1 (spec §7.4).
    entry = find_document(repo, feature)
    assert entry is not None
    entry.body.write_text(entry.body.read_text(encoding="utf-8") + "\nMore.\n")
    sync(Workspace.open(repo), bump=True)

    story_body = client.get(f"/api/documents/{story}").json()
    feature_body_json = client.get(f"/api/documents/{feature}").json()

    assert story_body["outbound"] == [
        {
            "type": "refines",
            "target": feature,
            "outdated": True,
            "state": "outdated",
        }
    ]
    assert feature_body_json["inbound"][0]["source"] == story
    assert feature_body_json["inbound"][0]["outdated"] is True


def test_document_detail_unknown_id_is_a_finding(client: TestClient) -> None:
    response = client.get("/api/documents/RE-ZZZZZZ")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "E-ID-UNKNOWN"
    assert error["severity"] == "E"
    assert error["doc_id"] == "RE-ZZZZZZ"
    assert "Traceback" not in response.text


def test_change_request_id_is_not_a_document(client: TestClient, repo: Path) -> None:
    from gregraph.core.changes import new_change_request

    cr = new_change_request(Workspace.open(repo), title="Raise the limit")

    response = client.get(f"/api/documents/{cr.id}")

    assert response.status_code == 404
    assert error_code(response) == "E-ID-UNKNOWN"


def test_document_with_missing_body_is_a_finding_not_a_crash(
    client: TestClient, repo: Path
) -> None:
    doc_id = add_document(repo, type="user-story", title="Upload documents")
    entry = find_document(repo, doc_id)
    assert entry is not None
    (repo / entry.body).unlink()

    response = client.get(f"/api/documents/{doc_id}")

    assert response.status_code == 409
    assert error_code(response) == "E-BODY-MISSING"


def test_status_has_contract_shape(client: TestClient, repo: Path) -> None:
    add_document(repo, type="user-story", title="Upload documents")

    response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    for key in ("counts", "degraded", "pending", "outdated", "stale", "findings"):
        assert key in body
    assert sum(body["counts"].values()) >= 1
    assert isinstance(body["degraded"], bool)
    assert body["pending"] == [] and body["outdated"] == [] and body["stale"] == []
    for finding in body["findings"]:
        assert {"code", "severity", "message"} <= set(finding)


def test_validate_reports_counts_and_orphans(client: TestClient, repo: Path) -> None:
    add_document(repo, type="user-story", title="Upload documents")

    response = client.get("/api/validate")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"findings", "error_count", "warning_count"}
    errors = [f for f in body["findings"] if f["severity"] == "E"]
    assert body["error_count"] == len(errors) >= 1
    codes = [finding["code"] for finding in body["findings"]]
    assert "W-ORPHAN" in codes
    assert body["warning_count"] == sum(
        1 for finding in body["findings"] if finding["severity"] == "W"
    )
    orphan = next(f for f in body["findings"] if f["code"] == "W-ORPHAN")
    assert orphan["doc_id"] is not None


def test_graph_returns_nodes_and_edges(client: TestClient, repo: Path) -> None:
    feature = add_document(repo, type="feature", title="Knowledge base")
    story = add_document(repo, type="user-story", title="Upload documents")
    link(Workspace.open(repo), source=story, link_type="refines", target=feature)

    response = client.get("/api/graph")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"nodes", "edges", "truncated"}
    assert body["truncated"] is False
    nodes = {node["id"]: node for node in body["nodes"]}
    assert nodes[story] == {
        "id": story,
        "title": "Upload documents",
        "kind": "requirement",
    }
    assert body["edges"] == [{"source": story, "type": "refines", "target": feature}]


def test_graph_caps_nodes_deterministically(
    client: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "GRAPH_NODE_CAP", 2)
    for index in range(4):
        add_document(repo, type="feature", title=f"Feature {index}")

    first = client.get("/api/graph").json()
    second = client.get("/api/graph").json()

    assert first["truncated"] is True
    assert len(first["nodes"]) == 2
    assert [node["id"] for node in first["nodes"]] == sorted(
        node["id"] for node in first["nodes"]
    )
    assert first == second


def test_graph_edges_only_join_included_nodes(
    client: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "GRAPH_NODE_CAP", 1)
    feature = add_document(repo, type="feature", title="Knowledge base")
    story = add_document(repo, type="user-story", title="Upload documents")
    link(Workspace.open(repo), source=story, link_type="refines", target=feature)

    body = client.get("/api/graph").json()

    included = {node["id"] for node in body["nodes"]}
    assert all(
        edge["source"] in included and edge["target"] in included
        for edge in body["edges"]
    )


def test_read_endpoints_never_mutate_the_repository(
    client: TestClient, repo: Path, token: str
) -> None:
    feature = add_document(repo, type="feature", title="Knowledge base")
    story = add_document(repo, type="user-story", title="Upload documents")
    link(Workspace.open(repo), source=story, link_type="refines", target=feature)
    before = _snapshot(repo)

    for path in (
        "/api/session",
        "/api/documents",
        f"/api/documents/{story}",
        "/api/status",
        "/api/validate",
        "/api/graph",
    ):
        assert client.get(path).status_code == 200, path

    assert _snapshot(repo) == before
