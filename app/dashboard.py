from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

from . import logging_config
from .metrics import percentile


WINDOW_MINUTES = 60
REFRESH_SECONDS = 30


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(record: dict[str, Any], field: str) -> float | None:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load_recent_records(
    log_path: Path | None = None,
    *,
    now: datetime | None = None,
    window_minutes: int = WINDOW_MINUTES,
) -> list[dict[str, Any]]:
    """Load valid JSON log records from the dashboard time window."""
    path = log_path or logging_config.LOG_PATH
    if not path.exists():
        return []

    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = reference - timedelta(minutes=window_minutes)
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        timestamp = _parse_timestamp(record.get("ts"))
        if timestamp is not None and start <= timestamp <= reference:
            records.append(record)
    return records


def build_dashboard_snapshot(records: list[dict[str, Any]]) -> dict[str, Any]:
    received = [record for record in records if record.get("event") == "request_received"]
    responses = [record for record in records if record.get("event") == "response_sent"]
    failures = [record for record in records if record.get("event") == "request_failed"]

    latencies = [value for record in responses if (value := _number(record, "latency_ms")) is not None]
    costs = [value for record in responses if (value := _number(record, "cost_usd")) is not None]
    tokens_in = [value for record in responses if (value := _number(record, "tokens_in")) is not None]
    tokens_out = [value for record in responses if (value := _number(record, "tokens_out")) is not None]
    quality = [value for record in responses if (value := _number(record, "quality_score")) is not None]

    traffic_by_minute: defaultdict[str, int] = defaultdict(int)
    for record in received:
        timestamp = _parse_timestamp(record.get("ts"))
        if timestamp is not None:
            traffic_by_minute[timestamp.strftime("%H:%M")] += 1

    error_breakdown = Counter(
        str(record.get("error_type") or "UnknownError") for record in failures
    )
    error_rate = len(failures) / len(received) * 100 if received else 0.0

    return {
        "record_count": len(records),
        "request_count": len(received),
        "response_count": len(responses),
        "latency_p50": percentile([int(value) for value in latencies], 50),
        "latency_p95": percentile([int(value) for value in latencies], 95),
        "latency_p99": percentile([int(value) for value in latencies], 99),
        "traffic_peak_rpm": max(traffic_by_minute.values(), default=0),
        "traffic_by_minute": dict(sorted(traffic_by_minute.items())),
        "error_rate_pct": round(error_rate, 2),
        "error_breakdown": dict(error_breakdown),
        "total_cost_usd": round(sum(costs), 6),
        "avg_cost_usd": round(mean(costs), 6) if costs else 0.0,
        "tokens_in_total": int(sum(tokens_in)),
        "tokens_out_total": int(sum(tokens_out)),
        "quality_avg": round(mean(quality), 4) if quality else 0.0,
    }


def _status(value: float, threshold: float, operator: str, *, has_data: bool) -> tuple[str, str]:
    if not has_data:
        return "NO DATA", "neutral"
    ok = value <= threshold if operator == "lte" else value >= threshold
    return ("OK", "ok") if ok else ("SLO VIOLATION", "critical")


def _bars(values: list[float], *, color: str = "#4f8cff") -> str:
    if not values:
        return '<div class="empty-chart">No data in selected window</div>'
    maximum = max(values) or 1
    blocks = "".join(
        f'<span style="height:{max(8, round(value / maximum * 100))}%;background:{color}" title="{value:g}"></span>'
        for value in values[-30:]
    )
    return f'<div class="bars" aria-label="time-series visualization">{blocks}</div>'


def render_dashboard(*, now: datetime | None = None) -> str:
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot = build_dashboard_snapshot(load_recent_records(now=reference))

    has_responses = snapshot["response_count"] > 0
    has_requests = snapshot["request_count"] > 0
    latency_status = _status(snapshot["latency_p95"], 3000, "lte", has_data=has_responses)
    traffic_status = _status(snapshot["traffic_peak_rpm"], 1, "gte", has_data=has_requests)
    error_status = _status(snapshot["error_rate_pct"], 2, "lte", has_data=has_requests)
    cost_status = _status(snapshot["total_cost_usd"], 2.5, "lte", has_data=has_responses)
    token_status = _status(
        max(snapshot["tokens_in_total"], snapshot["tokens_out_total"]),
        50_000,
        "lte",
        has_data=has_responses,
    )
    quality_status = _status(snapshot["quality_avg"], 0.75, "gte", has_data=has_responses)

    traffic_values = [float(value) for value in snapshot["traffic_by_minute"].values()]
    latency_values = [snapshot["latency_p50"], snapshot["latency_p95"], snapshot["latency_p99"]] if has_responses else []
    error_details = ", ".join(
        f"{escape(name)}: {count}" for name, count in sorted(snapshot["error_breakdown"].items())
    ) or "No errors"

    def badge(status: tuple[str, str]) -> str:
        label, css_class = status
        return f'<span class="badge {css_class}">{label}</span>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{REFRESH_SECONDS}">
  <title>Day 13 AI Observability Dashboard</title>
  <style>
    :root {{ color-scheme: dark; --bg:#08111f; --card:#111d30; --line:#263651; --muted:#91a3bd; --text:#f5f8ff; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter,Segoe UI,Arial,sans-serif; color:var(--text); background:radial-gradient(circle at top,#172944 0,#08111f 46%); min-height:100vh; }}
    main {{ max-width:1440px; margin:auto; padding:34px; }}
    header {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-end; margin-bottom:24px; }}
    h1 {{ margin:5px 0 8px; font-size:30px; }}
    .eyebrow {{ color:#66d9c5; text-transform:uppercase; letter-spacing:.14em; font-size:12px; font-weight:700; }}
    .meta,.sub,.footer {{ color:var(--muted); font-size:13px; }}
    .meta {{ text-align:right; line-height:1.7; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; }}
    .card {{ background:linear-gradient(145deg,rgba(20,34,56,.98),rgba(12,24,41,.98)); border:1px solid var(--line); border-radius:16px; padding:20px; min-height:250px; box-shadow:0 14px 36px rgba(0,0,0,.22); }}
    .card-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }}
    h2 {{ font-size:16px; margin:0; }}
    .value {{ font-size:36px; font-weight:750; margin:22px 0 3px; letter-spacing:-.03em; }}
    .unit {{ font-size:14px; color:var(--muted); font-weight:500; }}
    .badge {{ border-radius:999px; padding:5px 9px; font-size:10px; font-weight:800; letter-spacing:.06em; }}
    .ok {{ color:#73e4b3; background:#123d35; }} .critical {{ color:#ff9f9f; background:#4b202b; }} .neutral {{ color:#bac5d5; background:#29364a; }}
    .threshold {{ margin-top:8px; color:#b8c5d8; font-size:12px; }}
    .chart {{ height:76px; margin-top:20px; border-bottom:1px solid #32435d; display:flex; align-items:flex-end; }}
    .bars {{ height:72px; width:100%; display:flex; gap:5px; align-items:flex-end; }}
    .bars span {{ flex:1; min-width:5px; border-radius:4px 4px 1px 1px; opacity:.9; }}
    .empty-chart {{ color:#71839e; align-self:center; width:100%; text-align:center; font-size:12px; }}
    .legend {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:13px; color:#aebbd0; font-size:12px; }}
    .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }}
    .footer {{ margin-top:20px; display:flex; justify-content:space-between; }}
    @media (max-width:950px) {{ .grid {{ grid-template-columns:1fr 1fr; }} }}
    @media (max-width:620px) {{ main {{ padding:20px; }} header {{ display:block; }} .meta {{ text-align:left; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <header>
    <div><div class="eyebrow">Runtime dashboard · Member C</div><h1>Day 13 AI Observability</h1><div class="sub">Six signals derived directly from structured application logs</div></div>
    <div class="meta">Time range: last {WINDOW_MINUTES} minutes<br>Auto refresh: {REFRESH_SECONDS} seconds<br>Updated: {reference.strftime('%Y-%m-%d %H:%M:%S UTC')}</div>
  </header>
  <section class="grid">
    <article class="card" id="latency"><div class="card-head"><h2>1. Latency percentiles</h2>{badge(latency_status)}</div><div class="value">{snapshot['latency_p95']:,.0f} <span class="unit">ms P95</span></div><div class="threshold">SLO: P95 ≤ 3,000 ms</div><div class="chart">{_bars(latency_values, color='#4f8cff')}</div><div class="legend"><span>P50 {snapshot['latency_p50']:,.0f} ms</span><span>P95 {snapshot['latency_p95']:,.0f} ms</span><span>P99 {snapshot['latency_p99']:,.0f} ms</span></div></article>
    <article class="card" id="traffic"><div class="card-head"><h2>2. Request traffic</h2>{badge(traffic_status)}</div><div class="value">{snapshot['traffic_peak_rpm']} <span class="unit">peak req/min</span></div><div class="threshold">Freshness threshold: ≥ 1 request/minute</div><div class="chart">{_bars(traffic_values, color='#66d9c5')}</div><div class="legend"><span>Total requests: {snapshot['request_count']}</span><span>Active minute buckets: {len(traffic_values)}</span></div></article>
    <article class="card" id="errors"><div class="card-head"><h2>3. Error rate and breakdown</h2>{badge(error_status)}</div><div class="value">{snapshot['error_rate_pct']:.2f}<span class="unit">%</span></div><div class="threshold">SLO: failed / received ≤ 2%</div><div class="chart">{_bars([snapshot['error_rate_pct']] if has_requests else [], color='#ff6b7a')}</div><div class="legend"><span>{error_details}</span></div></article>
    <article class="card" id="cost"><div class="card-head"><h2>4. Cost over time</h2>{badge(cost_status)}</div><div class="value">${snapshot['total_cost_usd']:.4f} <span class="unit">USD total</span></div><div class="threshold">Budget threshold: ≤ $2.50</div><div class="chart">{_bars([snapshot['total_cost_usd']] if has_responses else [], color='#bd8cff')}</div><div class="legend"><span>Average/request: ${snapshot['avg_cost_usd']:.6f}</span></div></article>
    <article class="card" id="tokens"><div class="card-head"><h2>5. Input and output tokens</h2>{badge(token_status)}</div><div class="value">{snapshot['tokens_in_total'] + snapshot['tokens_out_total']:,} <span class="unit">tokens</span></div><div class="threshold">Threshold: each field ≤ 50,000 tokens</div><div class="chart">{_bars([snapshot['tokens_in_total'], snapshot['tokens_out_total']] if has_responses else [], color='#f6b85f')}</div><div class="legend"><span><i class="dot" style="background:#f6b85f"></i>Input {snapshot['tokens_in_total']:,}</span><span><i class="dot" style="background:#ffe1a6"></i>Output {snapshot['tokens_out_total']:,}</span></div></article>
    <article class="card" id="quality"><div class="card-head"><h2>6. Quality proxy</h2>{badge(quality_status)}</div><div class="value">{snapshot['quality_avg']:.2f} <span class="unit">score 0–1</span></div><div class="threshold">SLO: mean quality ≥ 0.75</div><div class="chart">{_bars([snapshot['quality_avg']] if has_responses else [], color='#65d989')}</div><div class="legend"><span>Successful responses: {snapshot['response_count']}</span></div></article>
  </section>
  <div class="footer"><span>Source: data/logs.jsonl</span><span>{snapshot['record_count']} valid records in selected window · No prompt or PII rendered</span></div>
</main></body></html>"""
