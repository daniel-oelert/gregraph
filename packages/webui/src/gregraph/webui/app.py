"""FastAPI application for the optional web UI (design §21, webui contract).

``create_app(root)`` builds the app for one repository. Every API request opens a
fresh :class:`~gregraph.core.workspace.Workspace` (Git adapter chosen by the same
probe as the CLI) and runs inside one in-process lock, so a read never observes a
half-written mutation. Routes call ``gregraph.core.operations`` only; this module
never reads or writes repository files (the static bundle aside).
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Iterable
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as FPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

import gregraph
from gregraph.core import operations as ops
from gregraph.core.config import read_config
from gregraph.core.git import GitAdapter, NullGitAdapter
from gregraph.core.graph import Edge
from gregraph.core.hashing import body_hash
from gregraph.core.ids import normalise_id
from gregraph.core.models import OperationRefused
from gregraph.core.rules import EDGE_RULES
from gregraph.core.storage import config_path
from gregraph.core.versioning import Freshness
from gregraph.core.workspace import Workspace, find_root
from gregraph.webui import schemas
from gregraph.webui.errors import (
    ApiError,
    error_body,
    finding_envelope,
    finding_json,
    invalid_request_message,
    refusal_status,
)
from gregraph.webui.security import SecurityMiddleware, read_mutation_body

STATIC_DIR: Path = Path(__file__).resolve().parent / "static"
GRAPH_NODE_CAP: int = 300


def _open_workspace(root: Path) -> Workspace:
    """Fresh workspace per request; Git probe identical to the CLI (spec §12.1)."""
    config = read_config(config_path(root))
    probe = GitAdapter(root)
    git: GitAdapter = probe if probe.is_repo() else NullGitAdapter()
    return Workspace(root=root, config=config, git=git)


def _parse[M: BaseModel](raw: bytes, model: type[M]) -> M:
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise ApiError(400, "E-REQUEST-INVALID", invalid_request_message(exc)) from exc


def _link_label(entry: Freshness) -> str:
    return f"{entry.source} {entry.type} {entry.target}"


def _outbound_json(view: Any) -> dict[str, Any]:
    return {
        "type": view.type,
        "target": view.target,
        "outdated": view.state == "outdated",
        "state": view.state,
    }


def _inbound_json(view: Any) -> dict[str, Any]:
    return {
        "type": view.type,
        "source": view.source,
        "outdated": view.state == "outdated",
        "state": view.state,
    }


def _graph_payload(ws: Workspace) -> dict[str, Any]:
    nodes = sorted(ws.graph.nodes.values(), key=lambda node: node.id)
    truncated = len(nodes) > GRAPH_NODE_CAP
    kept = nodes[:GRAPH_NODE_CAP]
    included = {node.id for node in kept}
    edges: Iterable[Edge] = sorted(
        (
            edge
            for edge in ws.graph.edges
            if edge.source in included and edge.target in included
        ),
        key=lambda edge: (edge.source, edge.type, edge.target),
    )
    return {
        "nodes": [
            {"id": node.id, "title": node.title, "kind": node.kind or ""}
            for node in kept
        ],
        "edges": [
            {"source": edge.source, "type": edge.type, "target": edge.target}
            for edge in edges
        ],
        "truncated": truncated,
    }


def create_app(root: Path, *, port: int | None = None) -> FastAPI:
    """Build the web app for the repository at ``root`` (the repository root).

    ``port`` is the bound port; when given, the Host header must name it
    (design §21.4). Raises :class:`FileNotFoundError` when ``root`` is not the
    root of a gregraph repository.
    """
    repository = root.resolve()
    if find_root(repository) != repository:
        raise FileNotFoundError("not a gregraph repository (no .gregraph/config.toml)")

    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.lock = lock
    app.add_middleware(SecurityMiddleware, bound_port=port)

    async def mutation_body(request: Request) -> bytes:
        return await read_mutation_body(request, token)

    @app.exception_handler(OperationRefused)
    async def _refused(_: Request, exc: OperationRefused) -> JSONResponse:
        return JSONResponse(
            finding_envelope(exc.finding),
            status_code=refusal_status(exc.finding.code),
        )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.envelope(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            error_body("E-REQUEST-INVALID", "request parameters are invalid"),
            status_code=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "E-NOT-FOUND", 405: "E-METHOD-NOT-ALLOWED"}
        code = codes.get(exc.status_code, "E-HTTP")
        try:
            message = HTTPStatus(exc.status_code).phrase
        except ValueError:
            message = "request failed"
        return JSONResponse(
            error_body(code, message),
            status_code=exc.status_code,
            headers=dict(exc.headers) if exc.headers else None,
        )

    # ------------------------------------------------------------------
    # static bundle (no token; carries no repository data)
    # ------------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            raise ApiError(503, "E-ASSETS-MISSING", "web UI bundle is not installed")
        return FileResponse(page, media_type="text/html; charset=utf-8")

    app.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIR / "assets", check_dir=False),
        name="assets",
    )

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    @app.get("/api/session")
    def session() -> dict[str, Any]:
        with lock:
            ws = _open_workspace(repository)
            git = not isinstance(ws.git, NullGitAdapter)
            types = [
                {"name": name, "kind": spec.kind}
                for name, spec in ws.config.types.items()
            ]
        return {
            "repository": {"name": repository.name, "git": git, "degraded": not git},
            "types": types,
            "link_types": sorted(EDGE_RULES),
            "version": gregraph.__version__,
            "csrf_token": token,
        }

    @app.get("/api/documents")
    def documents(
        type: str | None = Query(None, max_length=64, pattern=schemas.TYPE_NAME),
        status: str | None = Query(None, max_length=32, pattern=r"^[a-z-]{1,32}$"),
        q: str | None = Query(None, max_length=200),
    ) -> dict[str, Any]:
        with lock:
            ws = _open_workspace(repository)
            result = ops.list_documents(
                ws,
                type_names=[type] if type else (),
                statuses=[status] if status else (),
            )
        needle = (q or "").strip().lower()
        items = [
            {
                "id": row.id,
                "type": row.type,
                "kind": row.kind,
                "status": row.status,
                "version": row.version,
                "title": row.title,
                "tags": list(row.tags),
            }
            for row in result.rows
            if not needle or needle in row.id.lower() or needle in row.title.lower()
        ]
        return {"items": items, "notices": list(result.notices)}

    @app.get("/api/documents/{doc_id}")
    def document(
        doc_id: str = FPath(max_length=32, pattern=schemas.DOC_ID),
    ) -> dict[str, Any]:
        with lock:
            ws = _open_workspace(repository)
            resolved = normalise_id(
                doc_id, ws.config.ids.prefix, known=ws.index.documents
            )
            loaded = ws.index.documents.get(resolved) if resolved is not None else None
            if loaded is not None:
                # A sidecar without its Markdown body is reported, not crashed on (§14).
                for finding in ws.index.findings:
                    if (
                        finding.code == "E-BODY-MISSING"
                        and finding.subject == loaded.sidecar
                    ):
                        raise OperationRefused(finding)
            result = ops.show_document(ws, doc_id, body=True)
        if result.document is None:
            raise ApiError(404, "E-ID-UNKNOWN", "unknown document", doc_id=doc_id)
        doc = result.document
        # The body on disk is the snapshot the editor saves against. The sidecar
        # body_hash lags unbumped edits (spec §21.5), so hash the text just read.
        body_text = result.body_text or ""
        return {
            "id": result.id,
            "type": doc.type,
            "kind": result.kind or "",
            "status": result.status or "unknown",
            "version": doc.version,
            "title": doc.title,
            "tags": list(doc.tags),
            "body_text": body_text,
            "body_hash": body_hash(body_text),
            "outbound": [_outbound_json(view) for view in result.outbound],
            "inbound": [_inbound_json(view) for view in result.inbound],
            "notices": list(result.notices),
        }

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        with lock:
            ws = _open_workspace(repository)
            result = ops.status(ws)
        return {
            "counts": dict(result.document_counts),
            "degraded": result.degraded,
            "pending": [_link_label(entry) for entry in result.pending],
            "outdated": [_link_label(entry) for entry in result.outdated],
            "stale": [_link_label(entry) for entry in result.stale],
            "findings": [finding_json(finding) for finding in result.findings],
        }

    @app.get("/api/validate")
    def validate() -> dict[str, Any]:
        with lock:
            ws = _open_workspace(repository)
            result = ops.validate(ws)
        return {
            "findings": [finding_json(finding) for finding in result.findings],
            "error_count": result.errors,
            "warning_count": result.warnings,
        }

    @app.get("/api/graph")
    def graph() -> dict[str, Any]:
        with lock:
            ws = _open_workspace(repository)
            return _graph_payload(ws)

    # ------------------------------------------------------------------
    # mutations (token, JSON, bounded body; see security.read_mutation_body)
    # ------------------------------------------------------------------
    @app.post("/api/documents", status_code=201)
    def create_doc(raw: bytes = Depends(mutation_body)) -> JSONResponse:
        payload = _parse(raw, schemas.CreateDocument)
        with lock:
            ws = _open_workspace(repository)
            result = ops.create_document(
                ws, type=payload.type, title=payload.title, tags=payload.tags
            )
        body = {
            "id": result.id,
            "notices": list(result.notices),
            "findings": [finding_json(finding) for finding in result.findings],
        }
        return JSONResponse(body, status_code=201)

    @app.put("/api/documents/{doc_id}/body")
    def put_body(
        doc_id: str = FPath(max_length=32, pattern=schemas.DOC_ID),
        raw: bytes = Depends(mutation_body),
    ) -> dict[str, Any]:
        payload = _parse(raw, schemas.BodyUpdate)
        with lock:
            ws = _open_workspace(repository)
            result = ops.update_body(
                ws, doc_id=doc_id, text=payload.text, base_hash=payload.base_hash
            )
        return {
            "id": result.id,
            "body_hash": result.body_hash,
            "title": result.title,
            "changed": result.changed,
            "findings": [finding_json(finding) for finding in result.findings],
        }

    @app.patch("/api/documents/{doc_id}/meta")
    def patch_meta(
        doc_id: str = FPath(max_length=32, pattern=schemas.DOC_ID),
        raw: bytes = Depends(mutation_body),
    ) -> dict[str, Any]:
        payload = _parse(raw, schemas.PatchMeta)
        assignment = "tags=" + ",".join(payload.tags)
        with lock:
            ws = _open_workspace(repository)
            result = ops.set_fields(ws, doc_id=doc_id, assignments=[assignment])
        return {
            "id": result.id,
            "tags": list(result.tags),
            "notices": list(result.notices),
        }

    @app.post("/api/links")
    def create_link(raw: bytes = Depends(mutation_body)) -> dict[str, Any]:
        payload = _parse(raw, schemas.LinkCreate)
        with lock:
            ws = _open_workspace(repository)
            result = ops.link(
                ws, source=payload.source, link_type=payload.type, target=payload.target
            )
        notices = [result.notice] if result.notice else []
        return {"created": result.created, "notices": notices}

    @app.delete("/api/links/{source}/{link_type}/{target}")
    def remove_link(
        source: str = FPath(max_length=32, pattern=schemas.DOC_ID),
        link_type: str = FPath(max_length=32),
        target: str = FPath(max_length=32, pattern=schemas.DOC_ID),
        raw: bytes = Depends(mutation_body),
    ) -> dict[str, Any]:
        if link_type not in EDGE_RULES:
            raise ApiError(400, "E-REQUEST-INVALID", "unknown link type")
        with lock:
            ws = _open_workspace(repository)
            result = ops.unlink(
                ws,
                source=source,
                link_type=link_type,
                target=target,
            )
        notices = [result.notice] if result.notice else []
        return {"removed": result.removed, "notices": notices}

    return app


__all__ = ["GRAPH_NODE_CAP", "STATIC_DIR", "create_app"]
