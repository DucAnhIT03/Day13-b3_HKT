from __future__ import annotations

import json
from pathlib import Path

from app.dashboard_data import build_requests, build_trends, calculate_snapshot, filter_logs, load_logs


def write_log(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def test_dashboard_builds_six_metric_groups_from_request_journeys(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    write_log(
        log_path,
        [
            {
                "ts": "2026-08-11T04:00:00Z",
                "event": "request_received",
                "correlation_id": "req-success",
                "feature": "search",
                "session_id": "s1",
                "model": "test-model",
                "payload": {"message_preview": "safe"},
            },
            {
                "ts": "2026-08-11T04:00:01Z",
                "event": "response_sent",
                "correlation_id": "req-success",
                "feature": "search",
                "latency_ms": 1200,
                "tokens_in": 10,
                "tokens_out": 20,
                "cost_usd": 0.01,
                "quality_score": 0.9,
            },
            {
                "ts": "2026-08-11T04:01:00Z",
                "event": "request_received",
                "correlation_id": "req-error",
                "feature": "refund",
                "payload": {"message_preview": "safe"},
            },
            {
                "ts": "2026-08-11T04:01:01Z",
                "event": "request_failed",
                "correlation_id": "req-error",
                "feature": "refund",
                "error_type": "TimeoutError",
            },
        ],
    )

    logs = load_logs(log_path)
    requests = build_requests(logs)
    snapshot = calculate_snapshot(requests)
    trends = build_trends(requests)

    assert snapshot["total_requests"] == 2
    assert snapshot["traffic"] == 1
    assert snapshot["latency_p95"] == 1200
    assert snapshot["error_rate_pct"] == 50
    assert snapshot["total_cost_usd"] == 0.01
    assert snapshot["tokens_in_total"] == 10
    assert snapshot["tokens_out_total"] == 20
    assert snapshot["quality_avg"] == 0.9
    assert snapshot["error_breakdown"] == {"TimeoutError": 1}
    assert set(trends) == {"latency", "traffic", "errors", "cost", "tokens", "quality"}


def test_dashboard_filters_by_feature_and_latest_window(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    write_log(
        log_path,
        [
            {
                "ts": "2026-08-11T03:00:00Z",
                "event": "request_received",
                "correlation_id": "req-old",
                "feature": "search",
            },
            {
                "ts": "2026-08-11T04:00:00Z",
                "event": "request_received",
                "correlation_id": "req-new",
                "feature": "refund",
            },
            {
                "ts": "2026-08-11T04:00:01Z",
                "event": "response_sent",
                "correlation_id": "req-new",
                "feature": "refund",
                "latency_ms": 100,
            },
        ],
    )

    filtered = filter_logs(load_logs(log_path), minutes=15, features=["refund"])

    assert filtered["correlation_id"].unique().tolist() == ["req-new"]
    assert filtered["event"].tolist() == ["request_received", "response_sent"]
