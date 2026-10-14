"""Request-validation errors name the bad field, never echo input (design §21.6).

``E-REQUEST-INVALID`` (400) stays the code. The message is the first pydantic
error as ``<field path>: <constraint>``, bounded to 200 characters. Input values,
unexpected key names, raw JSON and tracebacks never appear in it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from webui_support import auth, error_code

SECRET = "hunter2-secret-value"


def _post_document(client: TestClient, token: str, payload: Any) -> Any:
    return client.post("/api/documents", json=payload, headers=auth(token))


def _message(response: Any) -> str:
    return str(response.json()["error"]["message"])


def test_invalid_tag_names_the_field_and_the_pattern(
    client: TestClient, token: str
) -> None:
    response = _post_document(
        client, token, {"type": "feature", "title": "X", "tags": ["Upper"]}
    )

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"
    message = _message(response)
    assert message.startswith("tags.0:")
    assert "pattern" in message
    assert "Upper" not in message


def test_overlong_title_names_the_field_and_the_limit(
    client: TestClient, token: str
) -> None:
    response = _post_document(
        client, token, {"type": "feature", "title": "Q" * 300, "tags": []}
    )

    assert response.status_code == 400
    message = _message(response)
    assert message.startswith("title:")
    assert "200" in message
    assert "QQQQ" not in message


@pytest.mark.parametrize("title", ["Line\nBreak", "Nul\x00byte", "Tab\rCR"])
def test_control_characters_in_title_are_named_not_echoed(
    client: TestClient, token: str, title: str
) -> None:
    response = _post_document(
        client, token, {"type": "feature", "title": title, "tags": []}
    )

    assert response.status_code == 400
    message = _message(response)
    assert message.startswith("title:")
    assert "pattern" in message
    assert "\n" not in message and "\x00" not in message and "\r" not in message


def test_unexpected_field_does_not_echo_its_name_or_value(
    client: TestClient, token: str
) -> None:
    response = _post_document(
        client,
        token,
        {"type": "feature", "title": "X", "tags": [], "password": SECRET},
    )

    assert response.status_code == 400
    message = _message(response)
    assert message.startswith("unexpected field")
    assert SECRET not in message
    assert "password" not in message


def test_unknown_type_value_is_not_echoed(client: TestClient, token: str) -> None:
    hostile = "<script>alert(1)</script>" + "A" * 900
    response = _post_document(
        client, token, {"type": hostile, "title": "X", "tags": []}
    )

    assert response.status_code == 400
    message = _message(response)
    assert message.startswith("type:")
    assert "<script>" not in message
    assert len(message) <= 200


def test_message_is_bounded_to_200_characters(client: TestClient, token: str) -> None:
    response = _post_document(
        client, token, {"type": "feature", "title": "X", "tags": ["z" * 5000]}
    )

    assert response.status_code == 400
    assert len(_message(response)) <= 200


def test_malformed_json_is_reported_without_the_raw_body(
    client: TestClient, token: str
) -> None:
    body = b'{"type": "feature", "title": "' + SECRET.encode() + b'", "tags": '
    response = client.post(
        "/api/documents",
        content=body,
        headers={"X-GREGraph-Token": token, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert error_code(response) == "E-REQUEST-INVALID"
    message = _message(response)
    assert message.startswith("body:")
    assert SECRET not in response.text
    assert "Traceback" not in response.text


def test_missing_required_field_names_it(client: TestClient, token: str) -> None:
    response = _post_document(client, token, {"type": "feature", "title": "X"})

    assert response.status_code == 400
    assert _message(response).startswith("tags:")


def test_body_schema_errors_use_the_same_format(client: TestClient, token: str) -> None:
    doc_id = _post_document(
        client, token, {"type": "feature", "title": "X", "tags": []}
    ).json()["id"]
    response = client.put(
        f"/api/documents/{doc_id}/body",
        json={"text": "# X\n", "base_hash": "not-a-hash"},
        headers=auth(token),
    )

    assert response.status_code == 400
    assert _message(response).startswith("base_hash:")
    assert "not-a-hash" not in _message(response)
    assert json.dumps(response.json())  # still a plain JSON envelope
