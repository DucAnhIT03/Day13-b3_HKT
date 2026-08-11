from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import logging_config
from app.dashboard import build_dashboard_snapshot, load_recent_records, render_dashboard
from app.main import app


def _write_records(path: Path) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    records = [
        {"ts": timestamp, "event": "request_received"},
        {"ts": timestamp, "event": "response_sent", "latency_ms": 120, "cost_usd": 0.01, "tokens_in": 10, "tokens_out": 20, "quality_score": 0.8},
        {"ts": timestamp, "event": "request_received"},
        {"ts": timestamp, "event": "request_failed", "error_type": "TimeoutError"},
    ]
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def test_dashboard_aggregates_runtime_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    _write_records(log_path)

    snapshot = build_dashboard_snapshot(load_recent_records(log_path))

    assert snapshot["request_count"] == 2
    assert snapshot["error_rate_pct"] == 50.0
    assert snapshot["error_breakdown"] == {"TimeoutError": 1}
    assert snapshot["tokens_in_total"] == 10
    assert snapshot["tokens_out_total"] == 20


def test_dashboard_endpoint_renders_six_runtime_panels(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "logs.jsonl"
    _write_records(log_path)
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.count('<article class="card"') == 6
    assert "50.00<span" in response.text
    assert "TimeoutError: 1" in response.text
    assert "Source: data/logs.jsonl" in response.text
    assert 'http-equiv="refresh" content="30"' in response.text


def test_dashboard_shows_no_data_without_recent_logs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "missing.jsonl")

    html = render_dashboard()

    assert html.count("NO DATA") == 6
    assert "No data in selected window" in html


def test_dashboard_data_endpoint_exposes_machine_readable_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    log_path = tmp_path / "logs.jsonl"
    _write_records(log_path)
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = TestClient(app).get("/dashboard/data")
    payload = response.json()

    assert response.status_code == 200
    assert payload["schema_version"] == 1
    assert payload["source"] == log_path.as_posix()
    assert payload["time_range_minutes"] == 60
    assert payload["refresh_seconds"] == 30
    assert payload["metrics"]["request_count"] == 2
    assert payload["metrics"]["error_rate_pct"] == 50.0


def test_recent_log_loader_ignores_invalid_and_out_of_window_records(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 11, 5, 0, tzinfo=timezone.utc)
    recent = {"ts": (now - timedelta(minutes=5)).isoformat(), "event": "request_received"}
    stale = {"ts": (now - timedelta(minutes=61)).isoformat(), "event": "request_received"}
    future = {"ts": (now + timedelta(seconds=1)).isoformat(), "event": "request_received"}
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(
        "\n".join([json.dumps(recent), "not-json", json.dumps(stale), json.dumps(future)]),
        encoding="utf-8",
    )

    records = load_recent_records(log_path, now=now)

    assert records == [recent]
