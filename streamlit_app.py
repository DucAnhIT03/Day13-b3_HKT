from __future__ import annotations

from pathlib import Path
from typing import Any

import altair as alt
import httpx
import pandas as pd
import streamlit as st

from app.dashboard_data import (
    DEFAULT_LOG_PATH,
    REPO_ROOT,
    build_requests,
    build_trends,
    calculate_snapshot,
    filter_logs,
    load_logs,
    load_yaml,
)


st.set_page_config(
    page_title="AI Observability Control Center",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

WINDOWS = {
    "15 phút": 15,
    "60 phút": 60,
    "24 giờ": 24 * 60,
    "Tất cả": None,
}
CHART_HEIGHT = 260
SLO_PATH = REPO_ROOT / "config" / "slo.yaml"
ALERTS_PATH = REPO_ROOT / "config" / "alert_rules.yaml"


@st.cache_data(ttl=30, show_spinner=False)
def cached_logs(path: str, version: int) -> pd.DataFrame:
    del version
    return load_logs(Path(path))


@st.cache_data(ttl=10, show_spinner=False)
def probe_api(base_url: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        with httpx.Client(timeout=1.5) as client:
            health_response = client.get(f"{base_url.rstrip('/')}/health")
            metrics_response = client.get(f"{base_url.rstrip('/')}/metrics")
            health_response.raise_for_status()
            metrics_response.raise_for_status()
        return health_response.json(), metrics_response.json()
    except (httpx.HTTPError, ValueError):
        return None, None


def chart_or_empty(chart: alt.Chart | alt.LayerChart | None, message: str) -> None:
    if chart is None:
        st.info(message, icon=":material/info:")
    else:
        st.altair_chart(chart)


def line_chart(
    data: pd.DataFrame,
    *,
    y_columns: list[str],
    labels: list[str],
    y_title: str,
    threshold: float | None = None,
) -> alt.Chart | alt.LayerChart | None:
    if data.empty:
        return None
    melted = data.melt(
        id_vars=["minute"],
        value_vars=y_columns,
        var_name="series",
        value_name="value",
    )
    melted["series"] = melted["series"].map(dict(zip(y_columns, labels, strict=True)))
    base = (
        alt.Chart(melted)
        .mark_line(point=alt.OverlayMarkDef(size=38), strokeWidth=2.5)
        .encode(
            x=alt.X("minute:T", title=None, axis=alt.Axis(format="%H:%M")),
            y=alt.Y("value:Q", title=y_title),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("minute:T", title="Thời gian", format="%H:%M:%S"),
                alt.Tooltip("series:N", title="Chỉ số"),
                alt.Tooltip("value:Q", title="Giá trị", format=",.3f"),
            ],
        )
        .properties(height=CHART_HEIGHT)
        .interactive(bind_y=False)
    )
    if threshold is None:
        return base
    threshold_data = pd.DataFrame({"threshold": [threshold]})
    rule = (
        alt.Chart(threshold_data)
        .mark_rule(color="#F87171", strokeDash=[7, 5], strokeWidth=2)
        .encode(
            y="threshold:Q",
            tooltip=[alt.Tooltip("threshold:Q", title="Ngưỡng SLO", format=",.2f")],
        )
    )
    return base + rule


def area_chart(
    data: pd.DataFrame,
    *,
    y_column: str,
    y_title: str,
    threshold: float | None = None,
) -> alt.Chart | alt.LayerChart | None:
    if data.empty:
        return None
    area = (
        alt.Chart(data)
        .mark_area(line={"strokeWidth": 2.5}, opacity=0.28)
        .encode(
            x=alt.X("minute:T", title=None, axis=alt.Axis(format="%H:%M")),
            y=alt.Y(f"{y_column}:Q", title=y_title),
            tooltip=[
                alt.Tooltip("minute:T", title="Thời gian", format="%H:%M:%S"),
                alt.Tooltip(f"{y_column}:Q", title=y_title, format=",.3f"),
            ],
        )
        .properties(height=CHART_HEIGHT)
        .interactive(bind_y=False)
    )
    if threshold is None:
        return area
    rule = (
        alt.Chart(pd.DataFrame({"threshold": [threshold]}))
        .mark_rule(color="#F87171", strokeDash=[7, 5], strokeWidth=2)
        .encode(y="threshold:Q")
    )
    return area + rule


def panel_header(title: str, caption: str, healthy: bool | None = None) -> None:
    with st.container(
        horizontal=True,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    ):
        st.markdown(f"#### {title}")
        if healthy is not None:
            st.badge(
                "Trong ngưỡng" if healthy else "Vượt ngưỡng",
                icon=":material/check_circle:" if healthy else ":material/warning:",
                color="green" if healthy else "red",
            )
    st.caption(caption)


def render_overview(snapshot: dict[str, Any], trends: dict[str, pd.DataFrame], slo: dict[str, Any]) -> None:
    slis = slo.get("slis", {})
    latency_limit = float(slis.get("latency_p95_ms", {}).get("objective", 3000))
    error_limit = float(slis.get("error_rate_pct", {}).get("objective", 2))
    cost_limit = float(slis.get("daily_cost_usd", {}).get("objective", 2.5))
    quality_floor = float(slis.get("quality_score_avg", {}).get("objective", 0.75))

    latency_values = trends["latency"].get("p95", pd.Series(dtype=float)).tolist()
    traffic_values = trends["traffic"].get("requests", pd.Series(dtype=float)).tolist()
    error_values = trends["errors"].get("error_rate_pct", pd.Series(dtype=float)).tolist()
    cost_values = trends["cost"].get("cumulative_cost_usd", pd.Series(dtype=float)).tolist()
    token_values = (
        trends["tokens"].get("tokens_in", pd.Series(dtype=float))
        + trends["tokens"].get("tokens_out", pd.Series(dtype=float))
    ).tolist()
    quality_values = trends["quality"].get("quality_score", pd.Series(dtype=float)).tolist()
    remaining_budget = cost_limit - snapshot["total_cost_usd"]

    with st.container(horizontal=True, gap="small"):
        st.metric(
            "Latency P95",
            f"{snapshot['latency_p95']:,.0f} ms",
            f"{snapshot['latency_p95'] - latency_limit:+,.0f} ms so với SLO",
            delta_color="inverse",
            icon=":material/speed:",
            border=True,
            chart_data=latency_values or None,
        )
        st.metric(
            "Traffic",
            f"{snapshot['total_requests']:,}",
            "request trong cửa sổ",
            delta_color="off",
            delta_arrow="off",
            icon=":material/traffic:",
            border=True,
            chart_data=traffic_values or None,
            chart_type="bar",
        )
        st.metric(
            "Error rate",
            f"{snapshot['error_rate_pct']:.2f}%",
            f"{snapshot['error_rate_pct'] - error_limit:+.2f}% so với SLO",
            delta_color="inverse",
            icon=":material/error:",
            border=True,
            chart_data=error_values or None,
        )
        st.metric(
            "Tổng chi phí",
            f"${snapshot['total_cost_usd']:.4f}",
            (
                f"${remaining_budget:.4f} ngân sách còn lại"
                if remaining_budget >= 0
                else f"${abs(remaining_budget):.4f} vượt ngân sách"
            ),
            delta_color="green" if remaining_budget >= 0 else "red",
            delta_arrow="off",
            icon=":material/payments:",
            border=True,
            chart_data=cost_values or None,
            chart_type="area",
        )
        st.metric(
            "Tokens",
            f"{snapshot['tokens_in_total'] + snapshot['tokens_out_total']:,}",
            f"{snapshot['tokens_out_total']:,} output",
            delta_color="off",
            delta_arrow="off",
            icon=":material/token:",
            border=True,
            chart_data=token_values or None,
            chart_type="bar",
        )
        st.metric(
            "Quality",
            f"{snapshot['quality_avg']:.2f}",
            f"{snapshot['quality_avg'] - quality_floor:+.2f} so với SLO",
            icon=":material/verified:",
            border=True,
            chart_data=quality_values or None,
        )

    latency_col, traffic_col = st.columns([1.65, 1])
    with latency_col.container(border=True):
        panel_header(
            "Latency percentiles",
            f"P50 / P95 / P99 · SLO P95 ≤ {latency_limit:,.0f} ms",
            snapshot["latency_p95"] <= latency_limit,
        )
        chart_or_empty(
            line_chart(
                trends["latency"],
                y_columns=["p50", "p95", "p99"],
                labels=["P50", "P95", "P99"],
                y_title="Milliseconds",
                threshold=latency_limit,
            ),
            "Chưa có response thành công để vẽ latency.",
        )
    with traffic_col.container(border=True):
        panel_header("Request traffic", "Tổng request theo phút")
        chart_or_empty(
            area_chart(trends["traffic"], y_column="requests", y_title="Requests/phút"),
            "Chưa có request trong cửa sổ đã chọn.",
        )

    error_col, cost_col = st.columns(2)
    with error_col.container(border=True):
        panel_header(
            "Error rate & breakdown",
            f"Tỷ lệ lỗi theo phút · SLO ≤ {error_limit:.1f}%",
            snapshot["error_rate_pct"] <= error_limit,
        )
        chart_or_empty(
            area_chart(
                trends["errors"],
                y_column="error_rate_pct",
                y_title="Error rate (%)",
                threshold=error_limit,
            ),
            "Chưa có dữ liệu lỗi.",
        )
        if snapshot["error_breakdown"]:
            st.caption("Breakdown: " + " · ".join(f"{key}: {value}" for key, value in snapshot["error_breakdown"].items()))
    with cost_col.container(border=True):
        panel_header(
            "Cost over time",
            f"Chi phí cộng dồn · ngân sách ≤ ${cost_limit:.2f}/ngày",
            snapshot["total_cost_usd"] <= cost_limit,
        )
        chart_or_empty(
            area_chart(
                trends["cost"],
                y_column="cumulative_cost_usd",
                y_title="USD",
                threshold=cost_limit,
            ),
            "Chưa có dữ liệu chi phí.",
        )

    tokens_col, quality_col = st.columns(2)
    with tokens_col.container(border=True):
        panel_header("Input & output tokens", "Mức tiêu thụ token theo phút")
        chart_or_empty(
            line_chart(
                trends["tokens"],
                y_columns=["tokens_in", "tokens_out"],
                labels=["Input", "Output"],
                y_title="Tokens",
            ),
            "Chưa có dữ liệu token.",
        )
    with quality_col.container(border=True):
        panel_header(
            "Quality proxy",
            f"Điểm chất lượng trung bình · SLO ≥ {quality_floor:.2f}",
            snapshot["quality_avg"] >= quality_floor,
        )
        chart_or_empty(
            line_chart(
                trends["quality"],
                y_columns=["quality_score"],
                labels=["Quality"],
                y_title="Score (0–1)",
                threshold=quality_floor,
            ),
            "Chưa có dữ liệu chất lượng.",
        )


def render_slo_card(
    title: str,
    value: float,
    objective: float,
    target: float,
    *,
    unit: str,
    lower_is_better: bool,
) -> None:
    healthy = value <= objective if lower_is_better else value >= objective
    if lower_is_better:
        progress = min(value / objective, 1.0) if objective else 0.0
        progress_text = f"Đã dùng {value / objective * 100:.1f}% ngưỡng" if objective else "Chưa có ngưỡng"
    else:
        progress = min(value / objective, 1.0) if objective else 0.0
        progress_text = f"Đạt {value / objective * 100:.1f}% ngưỡng" if objective else "Chưa có ngưỡng"

    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.markdown(f"#### {title}")
            st.badge(
                "Đạt SLO" if healthy else "Vi phạm SLO",
                icon=":material/check_circle:" if healthy else ":material/crisis_alert:",
                color="green" if healthy else "red",
            )
        st.metric("Hiện tại", f"{value:,.3f} {unit}", border=False)
        st.progress(progress, text=progress_text)
        comparator = "≤" if lower_is_better else "≥"
        st.caption(f"Objective {comparator} {objective:g} {unit} · target {target:g}%")


def render_reliability(snapshot: dict[str, Any], slo: dict[str, Any], alerts: dict[str, Any]) -> None:
    slis = slo.get("slis", {})
    cards = [
        ("Latency P95", snapshot["latency_p95"], "latency_p95_ms", "ms", True),
        ("Error rate", snapshot["error_rate_pct"], "error_rate_pct", "%", True),
        ("Daily cost", snapshot["total_cost_usd"], "daily_cost_usd", "USD", True),
        ("Quality score", snapshot["quality_avg"], "quality_score_avg", "score", False),
    ]
    first_row = st.columns(2)
    second_row = st.columns(2)
    for column, (title, value, key, unit, lower_is_better) in zip(first_row + second_row, cards, strict=True):
        config = slis.get(key, {})
        with column:
            render_slo_card(
                title,
                float(value),
                float(config.get("objective", 0)),
                float(config.get("target", 0)),
                unit=unit,
                lower_is_better=lower_is_better,
            )

    st.markdown("### :material/notifications_active: Alert rules")
    st.caption("Cảnh báo dựa trên triệu chứng người dùng nhìn thấy, liên kết trực tiếp tới runbook.")
    alert_rows = []
    for alert in alerts.get("alerts", []):
        name = alert.get("name", "unknown")
        if name == "high_latency_p95":
            firing = snapshot["latency_p95"] > 3000
        elif name == "elevated_error_rate":
            firing = snapshot["error_rate_pct"] > 5
        elif name == "cost_budget_exceeded":
            firing = snapshot["total_cost_usd"] > 2.5
        else:
            firing = False
        severity = str(alert.get("severity", "warning"))
        alert_rows.append(
            {
                "Trạng thái": "● FIRING" if firing else "✓ NORMAL",
                "Alert": name,
                "Severity": f"{'●' if severity == 'critical' else '▲'} {severity.upper()}",
                "Điều kiện": alert.get("condition", ""),
                "Owner": alert.get("owner", ""),
                "Runbook": alert.get("runbook", ""),
            }
        )
    alert_frame = pd.DataFrame(alert_rows)

    def alert_color(value: str) -> str:
        if "FIRING" in value or "CRITICAL" in value:
            return "color: #F87171; font-weight: 700"
        if "WARNING" in value:
            return "color: #FBBF24; font-weight: 700"
        if "NORMAL" in value:
            return "color: #34D399; font-weight: 700"
        return ""

    styled_alerts = alert_frame.style.map(alert_color, subset=["Trạng thái", "Severity"])
    st.dataframe(
        styled_alerts,
        hide_index=True,
        column_config={
            "Trạng thái": st.column_config.TextColumn(pinned=True),
            "Alert": st.column_config.TextColumn(pinned=True),
            "Severity": st.column_config.TextColumn(),
            "Điều kiện": st.column_config.TextColumn(width="large"),
            "Runbook": st.column_config.TextColumn(width="medium"),
        },
    )


def render_investigation(requests: pd.DataFrame, logs: pd.DataFrame) -> None:
    st.markdown("### :material/troubleshoot: Request explorer")
    st.caption("Chọn một correlation ID để lần theo toàn bộ hành trình request trong log.")
    if requests.empty:
        st.info("Chưa có request để điều tra. Hãy chạy API và load test trước.", icon=":material/info:")
        return

    lookup = requests.set_index("correlation_id").to_dict("index")
    selected_id = st.selectbox(
        "Correlation ID",
        requests["correlation_id"].tolist(),
        format_func=lambda item: f"{item}  ·  {lookup[item]['feature']}  ·  {lookup[item]['status']}",
    )
    selected = lookup[selected_id]
    with st.container(horizontal=True, gap="small"):
        st.metric("Trạng thái", selected["status"], icon=":material/task_alt:" if selected["status"] == "Success" else ":material/error:", border=True)
        st.metric("Feature", selected["feature"], icon=":material/category:", border=True)
        st.metric("Latency", f"{selected['latency_ms']:,.0f} ms", icon=":material/timer:", border=True)
        st.metric("Cost", f"${selected['cost_usd']:.6f}", icon=":material/payments:", border=True)
        st.metric("Quality", f"{selected['quality_score']:.2f}", icon=":material/verified:", border=True)

    journey = logs[logs["correlation_id"] == selected_id].copy()
    journey["Thời điểm"] = journey["timestamp"]
    journey["Sự kiện"] = journey["event"]
    journey["Mức độ"] = journey["level"].str.upper()
    details = journey.get("payload_detail", pd.Series(index=journey.index, dtype="object"))
    details = details.combine_first(
        journey.get("payload_message_preview", pd.Series(index=journey.index, dtype="object"))
    )
    journey["Chi tiết"] = details.combine_first(
        journey.get("payload_answer_preview", pd.Series(index=journey.index, dtype="object"))
    ).fillna("")
    latency_values = pd.to_numeric(journey.get("latency_ms", pd.NA), errors="coerce")
    journey["Latency"] = latency_values.map(
        lambda value: f"{value:,.0f} ms" if pd.notna(value) else "—"
    )

    with st.container(border=True):
        panel_header("Log journey", f"{len(journey)} sự kiện có cùng correlation ID")
        st.dataframe(
            journey[["Thời điểm", "Sự kiện", "Mức độ", "Chi tiết", "Latency"]],
            hide_index=True,
            column_config={
                "Thời điểm": st.column_config.DatetimeColumn(format="HH:mm:ss.SSS", pinned=True),
                "Sự kiện": st.column_config.TextColumn(pinned=True),
                "Chi tiết": st.column_config.TextColumn(width="large"),
                "Latency": st.column_config.TextColumn(),
            },
        )

    with st.expander(":material/data_object: Xem JSON log đã chuẩn hóa"):
        for record in journey.drop(columns=["Thời điểm", "Sự kiện", "Mức độ", "Chi tiết", "Latency"]).to_dict("records"):
            record["timestamp"] = str(record.get("timestamp", ""))
            st.json({key: value for key, value in record.items() if not pd.isna(value)}, expanded=False)


def render_recent_requests(requests: pd.DataFrame) -> None:
    st.markdown("### :material/history: Request gần đây")
    if requests.empty:
        st.info("Chưa có dữ liệu request.", icon=":material/info:")
        return
    recent = requests.head(100).copy()
    recent["status"] = recent["status"].map(
        {
            "Success": ":green-badge[:material/check_circle: SUCCESS]",
            "Error": ":red-badge[:material/error: ERROR]",
            "Pending": ":yellow-badge[:material/pending: PENDING]",
        }
    )
    st.dataframe(
        recent,
        hide_index=True,
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Thời gian", format="DD/MM HH:mm:ss"),
            "correlation_id": st.column_config.TextColumn("Correlation ID", pinned=True),
            "status": st.column_config.MarkdownColumn("Trạng thái", pinned=True),
            "feature": st.column_config.TextColumn("Feature"),
            "session_id": st.column_config.TextColumn("Session"),
            "model": None,
            "latency_ms": st.column_config.NumberColumn("Latency", format="%.0f ms"),
            "tokens_in": st.column_config.NumberColumn("Input tokens", format="%d"),
            "tokens_out": st.column_config.NumberColumn("Output tokens", format="%d"),
            "cost_usd": st.column_config.NumberColumn("Cost", format="$%.6f"),
            "quality_score": st.column_config.ProgressColumn("Quality", min_value=0, max_value=1, format="%.2f"),
            "error_type": st.column_config.TextColumn("Lỗi"),
            "message_preview": st.column_config.TextColumn("Message preview", width="large"),
        },
    )


def render_dashboard(
    api_url: str,
    window_minutes: int | None,
    selected_features: list[str],
) -> None:
    log_version = DEFAULT_LOG_PATH.stat().st_mtime_ns if DEFAULT_LOG_PATH.exists() else 0
    logs = filter_logs(
        cached_logs(str(DEFAULT_LOG_PATH), log_version),
        minutes=window_minutes,
        features=selected_features,
    )
    requests = build_requests(logs)
    snapshot = calculate_snapshot(requests)
    trends = build_trends(requests)
    slo = load_yaml(SLO_PATH)
    alerts = load_yaml(ALERTS_PATH)
    health, api_metrics = probe_api(api_url)

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        with st.container(horizontal=True, vertical_alignment="center"):
            if health:
                st.badge("API online", icon=":material/wifi:", color="green")
                st.badge(
                    "Tracing on" if health.get("tracing_enabled") else "Tracing off",
                    icon=":material/account_tree:",
                    color="violet" if health.get("tracing_enabled") else "gray",
                )
            else:
                st.badge("API offline · log fallback", icon=":material/cloud_off:", color="orange")
            st.badge(f"{len(logs):,} log events", icon=":material/database:", color="blue")
        newest = logs["timestamp"].max() if not logs.empty else None
        st.caption(f"Cập nhật cuối: {newest.strftime('%d/%m/%Y %H:%M:%S UTC') if pd.notna(newest) else 'chưa có dữ liệu'}")

    if api_metrics is not None and requests.empty:
        snapshot.update(api_metrics)

    overview_tab, reliability_tab, investigation_tab = st.tabs(
        [
            ":material/dashboard: Tổng quan",
            ":material/health_and_safety: SLO & cảnh báo",
            ":material/troubleshoot: Điều tra",
        ]
    )
    with overview_tab:
        render_overview(snapshot, trends, slo)
        render_recent_requests(requests)
    with reliability_tab:
        render_reliability(snapshot, slo, alerts)
    with investigation_tab:
        render_investigation(requests, logs)


with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.markdown("# :material/monitoring: AI Observability Control Center")
    if st.button(":material/refresh: Làm mới", type="primary"):
        st.cache_data.clear()
        st.rerun()

st.caption("Theo dõi sức khỏe AI API theo thời gian thực · Metrics → Traces → Logs")

initial_version = DEFAULT_LOG_PATH.stat().st_mtime_ns if DEFAULT_LOG_PATH.exists() else 0
initial_logs = cached_logs(str(DEFAULT_LOG_PATH), initial_version)
feature_options = sorted(
    str(value) for value in initial_logs.get("feature", pd.Series(dtype="object")).dropna().unique()
)

with st.sidebar:
    st.markdown("## :material/tune: Bộ lọc")
    st.caption("Điều khiển toàn bộ dashboard từ một nơi.")
    api_url = st.text_input("API endpoint", value="http://127.0.0.1:8000")
    selected_window = st.segmented_control(
        "Khoảng thời gian",
        options=list(WINDOWS),
        default="60 phút",
        required=True,
        width="stretch",
    )
    selected_features = st.multiselect(
        "Feature",
        feature_options,
        default=feature_options,
        placeholder="Tất cả feature",
    )
    auto_refresh = st.toggle("Tự làm mới mỗi 30 giây", value=True)
    st.divider()
    st.markdown("**Nguồn dữ liệu**")
    st.caption("KPI và biểu đồ: `data/logs.jsonl`\n\nHeartbeat: `/health` và `/metrics`")
    st.markdown("**SLO & alerts**")
    st.caption("`config/slo.yaml`\n\n`config/alert_rules.yaml`")

window_minutes = WINDOWS[selected_window or "60 phút"]
live_dashboard = st.fragment(run_every=30 if auto_refresh else None)(render_dashboard)
live_dashboard(api_url, window_minutes, selected_features)
