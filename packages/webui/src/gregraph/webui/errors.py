"""Error envelope and status mapping for the web API (design §21.8, webui design).

Every failure is ``{"error": Finding-shaped object}``. ``doc_id`` and ``path`` are
derived from the Finding subject (ID string or repository-relative path). No
traceback, exception text from unexpected errors, or absolute path is ever sent.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from gregraph.core.models import Finding

#: Refusal codes naming an unsafe path (400, design-level input problem).
PATH_REFUSAL_CODES: Final = frozenset({"E-PATH-UNSAFE"})


class ApiError(Exception):
    """An expected HTTP-level failure with a Finding-shaped body."""

    def __init__(
        self,
        status_code: int | HTTPStatus,
        code: str,
        message: str,
        *,
        doc_id: str | None = None,
        path: str | None = None,
        fix: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = code
        self.message = message
        self.doc_id = doc_id
        self.path = path
        self.fix = fix

    def envelope(self) -> dict[str, Any]:
        return error_body(
            self.code,
            self.message,
            doc_id=self.doc_id,
            path=self.path,
            fix=self.fix,
        )


def error_body(
    code: str,
    message: str,
    *,
    severity: str = "E",
    doc_id: str | None = None,
    path: str | None = None,
    fix: str | None = None,
) -> dict[str, Any]:
    """The ``{"error": …}`` envelope with the contract's Finding fields."""
    return {
        "error": {
            "code": code,
            "severity": severity,
            "message": message,
            "doc_id": doc_id,
            "path": path,
            "fix": fix,
        }
    }


def finding_json(finding: Finding) -> dict[str, Any]:
    """Contract Finding object (``doc_id``/``path`` derived from the subject)."""
    subject = finding.subject
    is_path = isinstance(subject, Path)
    return {
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "doc_id": None if is_path else str(subject),
        "path": str(subject) if is_path else None,
        "fix": finding.fix,
    }


def finding_envelope(finding: Finding) -> dict[str, Any]:
    return {"error": finding_json(finding)}


def refusal_status(code: str) -> int:
    """HTTP status of an ``OperationRefused`` by its code (design §21.8, webui)."""
    if code == "E-ID-UNKNOWN":
        return HTTPStatus.NOT_FOUND
    if code in PATH_REFUSAL_CODES:
        return HTTPStatus.BAD_REQUEST
    return HTTPStatus.CONFLICT


#: Upper bound on the message of a request-validation error (characters).
MAX_VALIDATION_MESSAGE: Final = 200
_GENERIC_INVALID: Final = "request body is invalid"


def invalid_request_message(exc: ValidationError) -> str:
    """Safe, bounded description of the first request-validation error.

    Format ``<field path>: <constraint>`` (for example ``tags.0: String should
    match pattern …``). Input values are excluded by pydantic
    (``include_input=False``), an unexpected key is reported only as
    ``unexpected field`` (its name is caller-chosen), and the result is cut to
    :data:`MAX_VALIDATION_MESSAGE` characters.
    """
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    if not errors:
        return _GENERIC_INVALID
    first = errors[0]
    if first.get("type") == "extra_forbidden":
        return "unexpected field"[:MAX_VALIDATION_MESSAGE]
    location = ".".join(str(part) for part in first.get("loc", ())) or "body"
    constraint = str(first.get("msg", _GENERIC_INVALID))
    return f"{location}: {constraint}"[:MAX_VALIDATION_MESSAGE]
