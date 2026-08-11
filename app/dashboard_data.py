from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"


def _empty_logs() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp",
            "ts",
            "event",
            "level",
            "service",
            "correlation_id",
            "feature",
            "session_id",
            "model",
        ]
    )


def load_logs(path: Path = DEFAULT_LOG_PATH) -> pd.DataFrame:
    """Load structured JSONL logs and flatten nested payload fields."""
    if not path.exists():
        return _empty_logs()

    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as log_file:
        for line in log_file:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not records:
        return _empty_logs()

    logs = pd.json_normalize(records, sep="_")
    for column in _empty_logs().columns:
        if column not in logs:
            logs[column] = pd.NA
    logs["timestamp"] = pd.to_datetime(logs["ts"], errors="coerce", utc=True)
    return logs.sort_values("timestamp", kind="stable").reset_index(drop=True)


def filter_logs(
    logs: pd.DataFrame,
    *,
    minutes: int | None = None,
    features: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Apply dashboard filters, anchoring the window to the newest log event."""
    if logs.empty:
        return logs.copy()

    filtered = logs.copy()
    if minutes is not None and filtered["timestamp"].notna().any():
        anchor = filtered["timestamp"].max()
        filtered = filtered[filtered["timestamp"] >= anchor - pd.Timedelta(minutes=minutes)]

    selected_features = list(features or [])
    if selected_features:
        request_ids = filtered.loc[
            filtered["feature"].isin(selected_features), "correlation_id"
        ].dropna()
        filtered = filtered[
            filtered["feature"].isin(selected_features)
            | filtered["correlation_id"].isin(request_ids)
        ]

    return filtered.reset_index(drop=True)


def build_requests(logs: pd.DataFrame) -> pd.DataFrame:
    """Collapse request lifecycle events into one operational row per request."""
    columns = [
        "timestamp",
        "correlation_id",
        "feature",
        "session_id",
        "model",
        "status",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "quality_score",
        "error_type",
        "message_preview",
    ]
    if logs.empty or "correlation_id" not in logs:
        return pd.DataFrame(columns=columns)

    request_events = logs[logs["event"].isin(["request_received", "response_sent", "request_failed"])]
    request_events = request_events[request_events["correlation_id"].notna()]
    rows: list[dict[str, Any]] = []

    for correlation_id, journey in request_events.groupby("correlation_id", sort=False):
        journey = journey.sort_values("timestamp", kind="stable")
        received = journey[journey["event"] == "request_received"]
        responses = journey[journey["event"] == "response_sent"]
        failures = journey[journey["event"] == "request_failed"]
        context = received.iloc[0] if not received.empty else journey.iloc[0]

        if not failures.empty:
            terminal = failures.iloc[-1]
            status = "Error"
        elif not responses.empty:
            terminal = responses.iloc[-1]
            status = "Success"
        else:
            terminal = journey.iloc[-1]
            status = "Pending"

        def value(name: str, fallback: Any = None) -> Any:
            candidate = terminal.get(name, fallback)
            if pd.isna(candidate):
                candidate = context.get(name, fallback)
            return fallback if pd.isna(candidate) else candidate

        rows.append(
            {
                "timestamp": value("timestamp"),
                "correlation_id": correlation_id,
                "feature": value("feature", "unknown"),
                "session_id": value("session_id", "unknown"),
                "model": value("model", "unknown"),
                "status": status,
                "latency_ms": value("latency_ms", 0.0),
                "tokens_in": value("tokens_in", 0),
                "tokens_out": value("tokens_out", 0),
                "cost_usd": value("cost_usd", 0.0),
                "quality_score": value("quality_score", 0.0),
                "error_type": value("error_type", ""),
                "message_preview": value("payload_message_preview", ""),
            }
        )

    requests = pd.DataFrame(rows, columns=columns)
    numeric_columns = [
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "quality_score",
    ]
    for column in numeric_columns:
        requests[column] = pd.to_numeric(requests[column], errors="coerce").fillna(0)
    return requests.sort_values("timestamp", ascending=False, kind="stable").reset_index(drop=True)


def calculate_snapshot(requests: pd.DataFrame) -> dict[str, Any]:
    """Calculate the six dashboard metric groups from request rows."""
    if requests.empty:
        return {
            "traffic": 0,
            "total_requests": 0,
            "observed_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "pending_requests": 0,
            "success_rate_pct": 0.0,
            "request_rate_per_min": 0.0,
            "latency_p50": 0.0,
            "latency_p95": 0.0,
            "latency_p99": 0.0,
            "latency_avg": 0.0,
            "avg_cost_usd": 0.0,
            "total_cost_usd": 0.0,
            "tokens_in_total": 0,
            "tokens_out_total": 0,
            "tokens_avg": 0.0,
            "error_rate_pct": 0.0,
            "error_breakdown": {},
            "quality_avg": 0.0,
            "active_sessions": 0,
            "active_features": 0,
            "active_models": 0,
            "window_start": None,
            "window_end": None,
        }

    successful = requests[requests["status"] == "Success"]
    failed = requests[requests["status"] == "Error"]
    pending = requests[requests["status"] == "Pending"]
    latencies = successful["latency_ms"]
    costs = successful["cost_usd"]
    quality = successful["quality_score"]
    total_requests = len(successful) + len(failed)
    window_start = pd.to_datetime(requests["timestamp"], utc=True).min()
    window_end = pd.to_datetime(requests["timestamp"], utc=True).max()
    duration_minutes = max((window_end - window_start).total_seconds() / 60, 1.0)

    def percentile(percent: float) -> float:
        return float(latencies.quantile(percent)) if not latencies.empty else 0.0

    error_breakdown = {
        str(key): int(value)
        for key, value in failed["error_type"].replace("", "UnknownError").value_counts().items()
    }
    return {
        "traffic": int(len(successful)),
        "total_requests": int(total_requests),
        "observed_requests": int(len(requests)),
        "successful_requests": int(len(successful)),
        "failed_requests": int(len(failed)),
        "pending_requests": int(len(pending)),
        "success_rate_pct": round(len(successful) / total_requests * 100, 2) if total_requests else 0.0,
        "request_rate_per_min": round(total_requests / duration_minutes, 2),
        "latency_p50": round(percentile(0.50), 1),
        "latency_p95": round(percentile(0.95), 1),
        "latency_p99": round(percentile(0.99), 1),
        "latency_avg": round(float(latencies.mean()), 1) if not latencies.empty else 0.0,
        "avg_cost_usd": round(float(costs.mean()), 6) if not costs.empty else 0.0,
        "total_cost_usd": round(float(costs.sum()), 6),
        "tokens_in_total": int(successful["tokens_in"].sum()),
        "tokens_out_total": int(successful["tokens_out"].sum()),
        "tokens_avg": round(
            float((successful["tokens_in"] + successful["tokens_out"]).mean()), 1
        )
        if not successful.empty
        else 0.0,
        "error_rate_pct": round(len(failed) / total_requests * 100, 2) if total_requests else 0.0,
        "error_breakdown": error_breakdown,
        "quality_avg": round(float(quality.mean()), 4) if not quality.empty else 0.0,
        "active_sessions": int(requests["session_id"].replace("unknown", pd.NA).nunique()),
        "active_features": int(requests["feature"].replace("unknown", pd.NA).nunique()),
        "active_models": int(requests["model"].replace("unknown", pd.NA).nunique()),
        "window_start": window_start,
        "window_end": window_end,
    }


def build_trends(requests: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build minute-level data sets used by the dashboard charts."""
    empty = pd.DataFrame()
    if requests.empty:
        return {
            name: empty.copy()
            for name in (
                "latency",
                "traffic",
                "errors",
                "cost",
                "tokens",
                "quality",
                "request_series",
                "outcomes",
            )
        }

    data = requests.copy()
    data["minute"] = pd.to_datetime(data["timestamp"], utc=True).dt.floor("min")
    data = data[data["minute"].notna()]
    successful = data[data["status"] == "Success"]

    request_series = successful.sort_values("timestamp", kind="stable").copy()
    if not request_series.empty:
        request_series["cumulative_cost_usd"] = request_series["cost_usd"].cumsum()
        request_series["rolling_p95_ms"] = request_series["latency_ms"].expanding().quantile(0.95)
        request_series["total_tokens"] = request_series["tokens_in"] + request_series["tokens_out"]

    if successful.empty:
        latency = cost = tokens = quality = empty.copy()
    else:
        latency = (
            successful.groupby("minute")["latency_ms"]
            .agg(
                p50=lambda values: values.quantile(0.50),
                p95=lambda values: values.quantile(0.95),
                p99=lambda values: values.quantile(0.99),
            )
            .reset_index()
        )
        cost = successful.groupby("minute", as_index=False)["cost_usd"].sum()
        cost["cumulative_cost_usd"] = cost["cost_usd"].cumsum()
        tokens = successful.groupby("minute", as_index=False)[["tokens_in", "tokens_out"]].sum()
        quality = successful.groupby("minute", as_index=False)["quality_score"].mean()

    traffic = data.groupby("minute").size().rename("requests").reset_index()
    error_counts = (
        data.assign(is_error=(data["status"] == "Error").astype(int))
        .groupby("minute")
        .agg(total=("status", "size"), errors=("is_error", "sum"))
        .reset_index()
    )
    error_counts["error_rate_pct"] = error_counts["errors"] / error_counts["total"] * 100
    outcomes = (
        data.groupby(["minute", "status"])
        .size()
        .rename("requests")
        .reset_index()
    )
    return {
        "latency": latency,
        "traffic": traffic,
        "errors": error_counts,
        "cost": cost,
        "tokens": tokens,
        "quality": quality,
        "request_series": request_series,
        "outcomes": outcomes,
    }


def build_feature_summary(requests: pd.DataFrame) -> pd.DataFrame:
    """Aggregate service, cost and quality signals by feature."""
    columns = [
        "feature",
        "requests",
        "success_rate_pct",
        "latency_p95_ms",
        "error_rate_pct",
        "total_cost_usd",
        "avg_cost_usd",
        "tokens_total",
        "quality_avg",
    ]
    if requests.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for feature, group in requests.groupby("feature", dropna=False):
        terminal = group[group["status"].isin(["Success", "Error"])]
        successful = group[group["status"] == "Success"]
        failed = group[group["status"] == "Error"]
        denominator = len(terminal)
        rows.append(
            {
                "feature": str(feature),
                "requests": int(denominator),
                "success_rate_pct": round(len(successful) / denominator * 100, 2)
                if denominator
                else 0.0,
                "latency_p95_ms": round(float(successful["latency_ms"].quantile(0.95)), 1)
                if not successful.empty
                else 0.0,
                "error_rate_pct": round(len(failed) / denominator * 100, 2)
                if denominator
                else 0.0,
                "total_cost_usd": round(float(successful["cost_usd"].sum()), 6),
                "avg_cost_usd": round(float(successful["cost_usd"].mean()), 6)
                if not successful.empty
                else 0.0,
                "tokens_total": int(
                    successful["tokens_in"].sum() + successful["tokens_out"].sum()
                ),
                "quality_avg": round(float(successful["quality_score"].mean()), 4)
                if not successful.empty
                else 0.0,
            }
        )

    return pd.DataFrame(rows, columns=columns).sort_values(
        ["requests", "feature"], ascending=[False, True], kind="stable"
    )


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}
