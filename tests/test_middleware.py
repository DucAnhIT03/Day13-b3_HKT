from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import logging_config
from app.main import app


CORRELATION_ID_PATTERN = re.compile(r"^req-[0-9a-f]{8}$")


def _chat_payload() -> dict[str, str]:
    return {
        "user_id": "middleware-test-user",
        "session_id": "middleware-test-session",
        "feature": "qa",
        "message": "Explain request correlation",
    }


def test_middleware_generates_and_propagates_correlation_id(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    with TestClient(app) as client:
        response = client.post("/chat", json=_chat_payload())

    correlation_id = response.headers["x-request-id"]
    assert response.status_code == 200
    assert CORRELATION_ID_PATTERN.fullmatch(correlation_id)
    assert response.json()["correlation_id"] == correlation_id
    assert float(response.headers["x-response-time-ms"]) >= 0

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    request_event = next(event for event in events if event["event"] == "request_received")
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert request_event["correlation_id"] == correlation_id
    assert response_event["correlation_id"] == correlation_id


def test_middleware_reuses_valid_client_correlation_id(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")
    correlation_id = "req-a1b2c3d4"
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            headers={"x-request-id": correlation_id},
            json=_chat_payload(),
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == correlation_id
    assert response.json()["correlation_id"] == correlation_id


def test_exception_handler_returns_correlation_id(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    correlation_id = "req-deadbeef"

    @app.get("/_test/unhandled-error")
    async def unhandled_error() -> None:
        raise RuntimeError("test failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/_test/unhandled-error",
            headers={"x-request-id": correlation_id},
        )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == correlation_id
    assert float(response.headers["x-response-time-ms"]) >= 0
    assert response.json() == {
        "detail": "Internal Server Error",
        "correlation_id": correlation_id,
    }
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    error_event = next(
        event for event in events if event["event"] == "unhandled_request_error"
    )
    assert error_event["correlation_id"] == correlation_id
    assert error_event["error_type"] == "RuntimeError"
