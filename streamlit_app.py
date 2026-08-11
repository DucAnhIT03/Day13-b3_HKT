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
    build_feature_summary,
    build_requests,
    build_trends,
    calculate_snapshot,
    filter_logs,
    load_logs,
    load_yaml,
)


st.set_page_config(
    page_title="AI operations · Observability",
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
SLO_PATH = REPO_ROOT / "config" / "slo.yaml"
ALERTS_PATH = REPO_ROOT / "config" / "alert_rules.yaml"
CHART_HEIGHT = 300
SUCCESS_COLOR = "#10B981"
ERROR_COLOR = "#EF4444"
WARNING_COLOR = "#F59E0B"
PRIMARY_COLOR = "#4F46E5"
VIOLET_COLOR = "#7C3AED"
MUTED_COLOR = "#94A3B8"


@st.cache_data(ttl=30, max_entries=20, show_spinner=False)
def cached_logs(path: str, version: int) -> pd.DataFrame:
    del version
    return load_logs(Path(path))


@st.cache_data(ttl=10, max_entries=10, show_spinner=False)
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


def get_slo_values(slo: dict[str, Any]) -> dict[str, float]:
    slis = slo.get("slis", {})
    return {
        "latency": float(slis.get("latency_p95_ms", {}).get("objective", 3000)),
        "error": float(slis.get("error_rate_pct", {}).get("objective", 2)),
        "cost": float(slis.get("daily_cost_usd", {}).get("objective", 2.5)),
        "quality": float(slis.get("quality_score_avg", {}).get("objective", 0.75)),
    }


def get_slo_health(snapshot: dict[str, Any], limits: dict[str, float]) -> dict[str, bool]:
    return {
        "Latency": snapshot["latency_p95"] <= limits["latency"],
        "Errors": snapshot["error_rate_pct"] <= limits["error"],
        "Cost": snapshot["total_cost_usd"] <= limits["cost"],
        "Quality": snapshot["quality_avg"] >= limits["quality"],
    }


def panel_header(
    title: str,
    caption: str,
    *,
    status: str | None = None,
    status_color: str = "green",
) -> None:
    with st.container(
        horizontal=True,
        horizontal_alignment="distribute",
        vertical_alignment="center",
    ):
        st.markdown(f"#### {title}")
        if status:
            icon = ":material/check_circle:" if status_color == "green" else ":material/warning:"
            st.badge(status, icon=icon, color=status_color)
    st.caption(caption)


def chart_or_empty(chart: alt.Chart | alt.LayerChart | None, message: str) -> None:
    if chart is None:
        st.info(message, icon=":material/info:")
    else:
        st.altair_chart(chart)


def latency_chart(series: pd.DataFrame, threshold: float) -> alt.LayerChart | None:
    if series.empty:
        return None
    source = series.sort_values("timestamp").copy()
    actual = (
        alt.Chart(source)
        .mark_line(point=alt.OverlayMarkDef(size=65), strokeWidth=2.8, color=PRIMARY_COLOR)
        .encode(
            x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%H:%M:%S")),
            y=alt.Y("latency_ms:Q", title="Latency (ms)", scale=alt.Scale(zero=True)),
            tooltip=[
                alt.Tooltip("timestamp:T", title="Thời gian", format="%H:%M:%S"),
                alt.Tooltip("correlation_id:N", title="Correlation ID"),
                alt.Tooltip("feature:N", title="Feature"),
                alt.Tooltip("latency_ms:Q", title="Latency", format=",.0f"),
            ],
        )
    )
    rolling = (
        alt.Chart(source)
        .mark_line(strokeDash=[7, 5], strokeWidth=2.2, color=VIOLET_COLOR)
        .encode(
            x="timestamp:T",
            y="rolling_p95_ms:Q",
            tooltip=[alt.Tooltip("rolling_p95_ms:Q", title="Rolling P95", format=",.0f")],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"threshold": [threshold]}))
        .mark_rule(color=ERROR_COLOR, strokeDash=[8, 5], strokeWidth=2)
        .encode(
            y="threshold:Q",
            tooltip=[alt.Tooltip("threshold:Q", title="SLO P95", format=",.0f")],
        )
    )
    return (actual + rolling + rule).properties(height=CHART_HEIGHT).interactive(bind_y=False)


def traffic_chart(outcomes: pd.DataFrame) -> alt.Chart | None:
    if outcomes.empty:
        return None
    return (
        alt.Chart(outcomes)
        .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
        .encode(
            x=alt.X("minute:T", title=None, axis=alt.Axis(format="%H:%M")),
            y=alt.Y("requests:Q", title="Requests/phút", stack="zero"),
            color=alt.Color(
                "status:N",
                title=None,
                scale=alt.Scale(
                    domain=["Success", "Error", "Pending"],
                    range=[SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR],
                ),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("minute:T", title="Phút", format="%H:%M"),
                alt.Tooltip("status:N", title="Trạng thái"),
                alt.Tooltip("requests:Q", title="Requests"),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )


def outcomes_donut(requests: pd.DataFrame) -> alt.Chart | None:
    if requests.empty:
        return None
    source = requests["status"].value_counts().rename_axis("status").reset_index(name="requests")
    return (
        alt.Chart(source)
        .mark_arc(innerRadius=72, outerRadius=116, cornerRadius=6, padAngle=0.025)
        .encode(
            theta=alt.Theta("requests:Q"),
            color=alt.Color(
                "status:N",
                title=None,
                scale=alt.Scale(
                    domain=["Success", "Error", "Pending"],
                    range=[SUCCESS_COLOR, ERROR_COLOR, WARNING_COLOR],
                ),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("status:N", title="Trạng thái"),
                alt.Tooltip("requests:Q", title="Requests"),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )


def feature_volume_chart(summary: pd.DataFrame) -> alt.Chart | None:
    if summary.empty:
        return None
    return (
        alt.Chart(summary)
        .mark_bar(cornerRadiusEnd=7, height=24)
        .encode(
            x=alt.X("requests:Q", title="Requests"),
            y=alt.Y("feature:N", title=None, sort="-x"),
            color=alt.Color(
                "error_rate_pct:Q",
                title="Error rate",
                scale=alt.Scale(domain=[0, max(float(summary["error_rate_pct"].max()), 5)], range=[PRIMARY_COLOR, ERROR_COLOR]),
            ),
            tooltip=[
                alt.Tooltip("feature:N", title="Feature"),
                alt.Tooltip("requests:Q", title="Requests"),
                alt.Tooltip("latency_p95_ms:Q", title="P95", format=",.0f"),
                alt.Tooltip("error_rate_pct:Q", title="Error rate", format=".2f"),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )


def cost_chart(series: pd.DataFrame, budget: float) -> alt.LayerChart | None:
    if series.empty:
        return None
    area = (
        alt.Chart(series)
        .mark_area(
            line={"color": PRIMARY_COLOR, "strokeWidth": 2.8},
            color=PRIMARY_COLOR,
            opacity=0.16,
        )
        .encode(
            x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%H:%M:%S")),
            y=alt.Y("cumulative_cost_usd:Q", title="Cumulative cost (USD)"),
            tooltip=[
                alt.Tooltip("timestamp:T", title="Thời gian", format="%H:%M:%S"),
                alt.Tooltip("correlation_id:N", title="Correlation ID"),
                alt.Tooltip("cost_usd:Q", title="Request cost", format="$.6f"),
                alt.Tooltip("cumulative_cost_usd:Q", title="Cộng dồn", format="$.6f"),
            ],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"budget": [budget]}))
        .mark_rule(color=ERROR_COLOR, strokeDash=[8, 5], strokeWidth=2)
        .encode(y="budget:Q", tooltip=[alt.Tooltip("budget:Q", title="Daily budget", format="$.2f")])
    )
    return (area + rule).properties(height=CHART_HEIGHT).interactive(bind_y=False)


def tokens_chart(series: pd.DataFrame) -> alt.Chart | None:
    if series.empty:
        return None
    source = series.melt(
        id_vars=["timestamp", "correlation_id", "feature"],
        value_vars=["tokens_in", "tokens_out"],
        var_name="token_type",
        value_name="tokens",
    )
    source["token_type"] = source["token_type"].map(
        {"tokens_in": "Input", "tokens_out": "Output"}
    )
    return (
        alt.Chart(source)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%H:%M:%S")),
            y=alt.Y("tokens:Q", title="Tokens", stack="zero"),
            color=alt.Color(
                "token_type:N",
                title=None,
                scale=alt.Scale(domain=["Input", "Output"], range=[VIOLET_COLOR, PRIMARY_COLOR]),
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("correlation_id:N", title="Correlation ID"),
                alt.Tooltip("feature:N", title="Feature"),
                alt.Tooltip("token_type:N", title="Loại"),
                alt.Tooltip("tokens:Q", title="Tokens"),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )


def quality_chart(series: pd.DataFrame, floor: float) -> alt.LayerChart | None:
    if series.empty:
        return None
    points = (
        alt.Chart(series)
        .mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=2.8, color=SUCCESS_COLOR)
        .encode(
            x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%H:%M:%S")),
            y=alt.Y("quality_score:Q", title="Quality score", scale=alt.Scale(domain=[0, 1])),
            tooltip=[
                alt.Tooltip("correlation_id:N", title="Correlation ID"),
                alt.Tooltip("feature:N", title="Feature"),
                alt.Tooltip("quality_score:Q", title="Quality", format=".2f"),
            ],
        )
    )
    rule = (
        alt.Chart(pd.DataFrame({"floor": [floor]}))
        .mark_rule(color=ERROR_COLOR, strokeDash=[8, 5], strokeWidth=2)
        .encode(y="floor:Q", tooltip=[alt.Tooltip("floor:Q", title="Quality SLO", format=".2f")])
    )
    return (points + rule).properties(height=CHART_HEIGHT).interactive(bind_y=False)


def render_health_summary(
    snapshot: dict[str, Any],
    slo_health: dict[str, bool],
    health: dict[str, Any] | None,
) -> None:
    incidents = health.get("incidents", {}) if health else {}
    active_incidents = [name for name, enabled in incidents.items() if enabled]
    violations = [name for name, healthy in slo_health.items() if not healthy]

    if active_incidents:
        st.error(
            f"Incident đang hoạt động: {', '.join(active_incidents)}. Ưu tiên kiểm tra latency, error và request explorer.",
            icon=":material/crisis_alert:",
        )
    elif violations:
        st.warning(
            f"Phát hiện {len(violations)} SLO ngoài ngưỡng: {', '.join(violations)}.",
            icon=":material/warning:",
        )
    elif health:
        st.success(
            f"Hệ thống ổn định · {sum(slo_health.values())}/4 SLO trong ngưỡng · {snapshot['success_rate_pct']:.1f}% request thành công.",
            icon=":material/verified_user:",
        )
    else:
        st.warning(
            "API đang offline. Dashboard vẫn hiển thị đầy đủ bằng dữ liệu log gần nhất.",
            icon=":material/cloud_off:",
        )


def render_kpis(
    snapshot: dict[str, Any],
    trends: dict[str, pd.DataFrame],
    limits: dict[str, float],
    slo_health: dict[str, bool],
) -> None:
    series = trends["request_series"]
    slo_score = int(sum(slo_health.values()) / max(len(slo_health), 1) * 100)
    first_row = st.columns(4)
    first_row[0].metric(
        "SLO health",
        f"{sum(slo_health.values())}/4",
        f"{slo_score}% operational score",
        delta_color="green" if slo_score == 100 else "orange",
        delta_arrow="off",
        icon=":material/health_and_safety:",
        border=True,
    )
    first_row[1].metric(
        "Requests",
        snapshot["total_requests"],
        f"{snapshot['request_rate_per_min']:.2f} req/phút",
        delta_color="blue",
        delta_arrow="off",
        icon=":material/traffic:",
        border=True,
        chart_data=trends["traffic"].get("requests", pd.Series(dtype=float)).tolist() or None,
        chart_type="bar",
    )
    first_row[2].metric(
        "Latency P95",
        f"{snapshot['latency_p95']:,.0f} ms",
        f"{snapshot['latency_p95'] - limits['latency']:+,.0f} ms so với SLO",
        delta_color="inverse",
        icon=":material/speed:",
        border=True,
        chart_data=series.get("latency_ms", pd.Series(dtype=float)).tolist() or None,
    )
    first_row[3].metric(
        "Error rate",
        f"{snapshot['error_rate_pct']:.2f}%",
        f"{snapshot['error_rate_pct'] - limits['error']:+.2f}% so với SLO",
        delta_color="inverse",
        icon=":material/error:",
        border=True,
        chart_data=trends["errors"].get("error_rate_pct", pd.Series(dtype=float)).tolist() or None,
    )

    second_row = st.columns(4)
    second_row[0].metric(
        "Success rate",
        f"{snapshot['success_rate_pct']:.1f}%",
        f"{snapshot['successful_requests']} thành công · {snapshot['failed_requests']} lỗi",
        delta_color="green" if snapshot["failed_requests"] == 0 else "red",
        delta_arrow="off",
        icon=":material/task_alt:",
        border=True,
    )
    remaining_budget = limits["cost"] - snapshot["total_cost_usd"]
    second_row[1].metric(
        "Total cost",
        f"${snapshot['total_cost_usd']:.4f}",
        f"${abs(remaining_budget):.4f} {'còn lại' if remaining_budget >= 0 else 'vượt ngân sách'}",
        delta_color="green" if remaining_budget >= 0 else "red",
        delta_arrow="off",
        icon=":material/payments:",
        border=True,
        chart_data=series.get("cumulative_cost_usd", pd.Series(dtype=float)).tolist() or None,
        chart_type="area",
    )
    second_row[2].metric(
        "Total tokens",
        f"{snapshot['tokens_in_total'] + snapshot['tokens_out_total']:,}",
        f"{snapshot['tokens_avg']:.1f} token/request",
        delta_color="violet",
        delta_arrow="off",
        icon=":material/token:",
        border=True,
        chart_data=series.get("total_tokens", pd.Series(dtype=float)).tolist() or None,
        chart_type="bar",
    )
    second_row[3].metric(
        "Quality",
        f"{snapshot['quality_avg']:.2f}",
        f"{snapshot['quality_avg'] - limits['quality']:+.2f} so với SLO",
        delta_color="normal",
        icon=":material/verified:",
        border=True,
        chart_data=series.get("quality_score", pd.Series(dtype=float)).tolist() or None,
    )


def style_status_table(frame: pd.DataFrame, columns: list[str]) -> pd.io.formats.style.Styler:
    def color(value: Any) -> str:
        text = str(value).upper()
        if any(token in text for token in ("FIRING", "CRITICAL", "ERROR", "VI PHẠM")):
            return f"color: {ERROR_COLOR}; font-weight: 700"
        if any(token in text for token in ("WARNING", "PENDING", "CẢNH BÁO")):
            return f"color: {WARNING_COLOR}; font-weight: 700"
        if any(token in text for token in ("NORMAL", "SUCCESS", "HEALTHY", "ĐẠT")):
            return f"color: {SUCCESS_COLOR}; font-weight: 700"
        return ""

    return frame.style.map(color, subset=columns)


def render_recent_requests(requests: pd.DataFrame) -> None:
    st.markdown("### Request gần đây")
    st.caption("Danh sách request đã chuẩn hóa, sắp xếp từ mới nhất và không hiển thị dữ liệu nhạy cảm.")
    if requests.empty:
        st.info("Chưa có request trong phạm vi lọc.", icon=":material/info:")
        return
    recent = requests.head(100).copy()
    recent["status"] = recent["status"].map(
        {"Success": "● SUCCESS", "Error": "● ERROR", "Pending": "● PENDING"}
    )
    styled = style_status_table(recent, ["status"])
    st.dataframe(
        styled,
        hide_index=True,
        placeholder="—",
        key="recent_requests_table",
        column_order=[
            "timestamp",
            "status",
            "correlation_id",
            "feature",
            "latency_ms",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "quality_score",
            "message_preview",
        ],
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Thời gian", format="DD/MM HH:mm:ss"),
            "status": st.column_config.TextColumn("Trạng thái", pinned=True),
            "correlation_id": st.column_config.TextColumn("Correlation ID", pinned=True),
            "feature": st.column_config.TextColumn("Feature"),
            "latency_ms": st.column_config.NumberColumn("Latency", format="%,.0f ms"),
            "tokens_in": st.column_config.NumberColumn("Input", format="%d"),
            "tokens_out": st.column_config.NumberColumn("Output", format="%d"),
            "cost_usd": st.column_config.NumberColumn("Cost", format="$%.6f"),
            "quality_score": st.column_config.ProgressColumn(
                "Quality", min_value=0, max_value=1, format="%.2f"
            ),
            "message_preview": st.column_config.TextColumn("Message preview", width="large"),
        },
    )


def render_overview(
    snapshot: dict[str, Any],
    trends: dict[str, pd.DataFrame],
    requests: pd.DataFrame,
    feature_summary: pd.DataFrame,
    limits: dict[str, float],
    slo_health: dict[str, bool],
    health: dict[str, Any] | None,
) -> None:
    render_health_summary(snapshot, slo_health, health)
    render_kpis(snapshot, trends, limits, slo_health)

    st.markdown("### Live performance")
    latency_col, traffic_col = st.columns([1.65, 1], vertical_alignment="top")
    with latency_col.container(border=True):
        panel_header(
            "Request latency",
            f"Latency từng request và rolling P95 · đường đỏ là SLO {limits['latency']:,.0f} ms",
            status="Trong ngưỡng" if slo_health["Latency"] else "Vượt ngưỡng",
            status_color="green" if slo_health["Latency"] else "red",
        )
        chart_or_empty(
            latency_chart(trends["request_series"], limits["latency"]),
            "Chưa có response thành công để vẽ latency.",
        )
    with traffic_col.container(border=True):
        panel_header("Traffic outcomes", "Request theo phút, phân tách theo trạng thái")
        chart_or_empty(traffic_chart(trends["outcomes"]), "Chưa có traffic trong phạm vi lọc.")

    mix_col, outcome_col = st.columns([1.35, 1], vertical_alignment="top")
    with mix_col.container(border=True):
        panel_header("Feature demand", "Lưu lượng theo feature · màu đậm hơn khi error rate tăng")
        chart_or_empty(feature_volume_chart(feature_summary), "Chưa có dữ liệu feature.")
    with outcome_col.container(border=True):
        panel_header("Request health", "Phân bổ kết quả request trong cửa sổ hiện tại")
        chart_or_empty(outcomes_donut(requests), "Chưa có kết quả request.")

    render_recent_requests(requests)


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
    utilization = value / objective if objective else 0.0
    remaining = objective - value if lower_is_better else value - objective
    if unit == "ms":
        value_text = f"{value:,.0f} {unit}"
        remaining_text = f"{abs(remaining):,.0f} {unit}"
    elif unit == "USD":
        value_text = f"{value:,.4f} {unit}"
        remaining_text = f"{abs(remaining):,.4f} {unit}"
    else:
        value_text = f"{value:,.2f} {unit}"
        remaining_text = f"{abs(remaining):,.2f} {unit}"
    with st.container(border=True, height="stretch"):
        with st.container(
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        ):
            st.markdown(f"#### {title}")
            st.badge(
                "Healthy" if healthy else "Vi phạm",
                icon=":material/check_circle:" if healthy else ":material/crisis_alert:",
                color="green" if healthy else "red",
            )
        st.metric("Hiện tại", value_text, border=False)
        st.progress(
            min(max(utilization, 0.0), 1.0),
            text=f"{utilization * 100:.1f}% ngưỡng mục tiêu",
        )
        comparator = "≤" if lower_is_better else "≥"
        direction = "dư địa" if healthy else "còn thiếu"
        st.caption(
            f"Objective {comparator} {objective:g} {unit} · {remaining_text} {direction} · target {target:g}%"
        )


def platform_card(title: str, value: str, caption: str, *, healthy: bool | None, icon: str) -> None:
    with st.container(border=True, height="stretch"):
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.markdown(f"**{title}**")
            if healthy is not None:
                st.badge(
                    "OK" if healthy else "Attention",
                    icon=":material/check:" if healthy else ":material/warning:",
                    color="green" if healthy else "orange",
                )
        st.markdown(f"### {icon} {value}")
        st.caption(caption)


def render_alerts(snapshot: dict[str, Any], alerts: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    current_values = {
        "high_latency_p95": (snapshot["latency_p95"], "ms", snapshot["latency_p95"] > 3000),
        "elevated_error_rate": (snapshot["error_rate_pct"], "%", snapshot["error_rate_pct"] > 5),
        "cost_budget_exceeded": (snapshot["total_cost_usd"], "USD", snapshot["total_cost_usd"] > 2.5),
    }
    for alert in alerts.get("alerts", []):
        name = str(alert.get("name", "unknown"))
        value, unit, firing = current_values.get(name, (0.0, "", False))
        severity = str(alert.get("severity", "warning")).upper()
        rows.append(
            {
                "Trạng thái": "● FIRING" if firing else "✓ NORMAL",
                "Alert": name,
                "Severity": f"{'●' if severity == 'CRITICAL' else '▲'} {severity}",
                "Hiện tại": f"{value:,.3f} {unit}",
                "Điều kiện": alert.get("condition", ""),
                "Owner": alert.get("owner", ""),
                "Runbook": alert.get("runbook", ""),
            }
        )
    frame = pd.DataFrame(rows)
    st.dataframe(
        style_status_table(frame, ["Trạng thái", "Severity"]),
        hide_index=True,
        placeholder="—",
        key="alert_rules_table",
        column_config={
            "Trạng thái": st.column_config.TextColumn(pinned=True),
            "Alert": st.column_config.TextColumn(pinned=True),
            "Severity": st.column_config.TextColumn(),
            "Hiện tại": st.column_config.TextColumn(),
            "Điều kiện": st.column_config.TextColumn(width="large"),
            "Owner": st.column_config.TextColumn(),
            "Runbook": st.column_config.TextColumn(width="medium"),
        },
    )


def render_reliability(
    snapshot: dict[str, Any],
    logs: pd.DataFrame,
    feature_summary: pd.DataFrame,
    slo: dict[str, Any],
    alerts: dict[str, Any],
    health: dict[str, Any] | None,
    api_metrics: dict[str, Any] | None,
) -> None:
    incidents = health.get("incidents", {}) if health else {}
    active_incidents = [name for name, enabled in incidents.items() if enabled]
    tracing_on = bool(health and health.get("tracing_enabled"))
    request_logs = logs[logs["event"].isin(["request_received", "response_sent", "request_failed"])]
    correlation_coverage = (
        request_logs["correlation_id"].notna().mean() * 100 if not request_logs.empty else 0.0
    )

    st.markdown("### Platform posture")
    cards = st.columns(4)
    with cards[0]:
        platform_card(
            "API service",
            "Online" if health else "Log fallback",
            f"In-memory traffic: {(api_metrics or {}).get('traffic', 0)} request",
            healthy=health is not None,
            icon=":material/dns:",
        )
    with cards[1]:
        platform_card(
            "Tracing",
            "Enabled" if tracing_on else "Disabled",
            "Langfuse waterfall sẵn sàng" if tracing_on else "Cần cấu hình Langfuse credentials",
            healthy=tracing_on,
            icon=":material/account_tree:",
        )
    with cards[2]:
        platform_card(
            "Incidents",
            ", ".join(active_incidents) if active_incidents else "None active",
            f"{len(incidents)} scenario được theo dõi" if incidents else "Không đọc được incident state",
            healthy=not active_incidents if health else None,
            icon=":material/emergency_home:",
        )
    with cards[3]:
        platform_card(
            "Log coverage",
            f"{correlation_coverage:.0f}%",
            f"{len(logs):,} event · {snapshot['active_sessions']} session",
            healthy=correlation_coverage >= 99,
            icon=":material/database:",
        )

    st.markdown("### Service-level objectives")
    slis = slo.get("slis", {})
    definitions = [
        ("Latency P95", snapshot["latency_p95"], "latency_p95_ms", "ms", True),
        ("Error rate", snapshot["error_rate_pct"], "error_rate_pct", "%", True),
        ("Daily cost", snapshot["total_cost_usd"], "daily_cost_usd", "USD", True),
        ("Quality score", snapshot["quality_avg"], "quality_score_avg", "score", False),
    ]
    slo_columns = st.columns(2)
    for index, (title, value, key, unit, lower_is_better) in enumerate(definitions):
        config = slis.get(key, {})
        with slo_columns[index % 2]:
            render_slo_card(
                title,
                float(value),
                float(config.get("objective", 0)),
                float(config.get("target", 0)),
                unit=unit,
                lower_is_better=lower_is_better,
            )

    st.markdown("### Alert rules")
    st.caption("Cảnh báo dựa trên triệu chứng người dùng, kèm current value, owner và runbook.")
    render_alerts(snapshot, alerts)

    st.markdown("### Reliability theo feature")
    if feature_summary.empty:
        st.info("Chưa có feature để so sánh.", icon=":material/info:")
    else:
        reliability = feature_summary[
            ["feature", "requests", "success_rate_pct", "latency_p95_ms", "error_rate_pct", "quality_avg"]
        ]
        st.dataframe(
            reliability,
            hide_index=True,
            placeholder="—",
            column_config={
                "feature": st.column_config.TextColumn("Feature", pinned=True),
                "requests": st.column_config.NumberColumn("Requests", format="%d"),
                "success_rate_pct": st.column_config.ProgressColumn(
                    "Success rate", min_value=0, max_value=100, format="%.1f%%"
                ),
                "latency_p95_ms": st.column_config.NumberColumn("P95", format="%,.0f ms"),
                "error_rate_pct": st.column_config.NumberColumn("Error rate", format="%.2f%%"),
                "quality_avg": st.column_config.ProgressColumn(
                    "Quality", min_value=0, max_value=1, format="%.2f"
                ),
            },
        )


def render_economics(
    snapshot: dict[str, Any],
    trends: dict[str, pd.DataFrame],
    feature_summary: pd.DataFrame,
    limits: dict[str, float],
) -> None:
    total_tokens = snapshot["tokens_in_total"] + snapshot["tokens_out_total"]
    output_share = snapshot["tokens_out_total"] / total_tokens * 100 if total_tokens else 0.0
    average_cost_musd = snapshot["avg_cost_usd"] * 1000
    budget_remaining = limits["cost"] - snapshot["total_cost_usd"]
    cards = st.columns(4)
    cards[0].metric(
        "Average cost",
        f"{average_cost_musd:.3f} mUSD",
        "mỗi response thành công",
        delta_color="blue",
        delta_arrow="off",
        icon=":material/receipt_long:",
        border=True,
    )
    cards[1].metric(
        "Budget used",
        f"{snapshot['total_cost_usd'] / limits['cost'] * 100:.2f}%" if limits["cost"] else "0%",
        f"${abs(budget_remaining):.4f} {'còn lại' if budget_remaining >= 0 else 'vượt ngân sách'}",
        delta_color="green" if budget_remaining >= 0 else "red",
        delta_arrow="off",
        icon=":material/account_balance_wallet:",
        border=True,
    )
    cards[2].metric(
        "Output token share",
        f"{output_share:.1f}%",
        f"{snapshot['tokens_out_total']:,} / {total_tokens:,} token",
        delta_color="violet",
        delta_arrow="off",
        icon=":material/data_usage:",
        border=True,
    )
    cards[3].metric(
        "Quality efficiency",
        f"{snapshot['quality_avg']:.2f}",
        f"với {average_cost_musd:.3f} mUSD/request",
        delta_color="green",
        delta_arrow="off",
        icon=":material/auto_awesome:",
        border=True,
    )

    cost_col, token_col = st.columns(2)
    with cost_col.container(border=True):
        panel_header(
            "Cumulative cost",
            f"Chi phí theo từng request · đường đỏ là ngân sách ${limits['cost']:.2f}/ngày",
            status="Trong ngân sách" if snapshot["total_cost_usd"] <= limits["cost"] else "Vượt ngân sách",
            status_color="green" if snapshot["total_cost_usd"] <= limits["cost"] else "red",
        )
        chart_or_empty(
            cost_chart(trends["request_series"], limits["cost"]),
            "Chưa có dữ liệu chi phí.",
        )
    with token_col.container(border=True):
        panel_header("Token consumption", "Input và output token của từng request")
        chart_or_empty(tokens_chart(trends["request_series"]), "Chưa có dữ liệu token.")

    quality_col, feature_col = st.columns([1.15, 1])
    with quality_col.container(border=True):
        panel_header(
            "Quality trend",
            f"Quality proxy từng request · đường đỏ là SLO {limits['quality']:.2f}",
            status="Đạt SLO" if snapshot["quality_avg"] >= limits["quality"] else "Dưới SLO",
            status_color="green" if snapshot["quality_avg"] >= limits["quality"] else "red",
        )
        chart_or_empty(
            quality_chart(trends["request_series"], limits["quality"]),
            "Chưa có dữ liệu quality.",
        )
    with feature_col.container(border=True):
        panel_header("Cost by feature", "Feature đóng góp nhiều chi phí nhất trong cửa sổ")
        if feature_summary.empty:
            st.info("Chưa có dữ liệu feature.", icon=":material/info:")
        else:
            chart = (
                alt.Chart(feature_summary)
                .mark_bar(cornerRadiusEnd=7, height=24, color=PRIMARY_COLOR)
                .encode(
                    x=alt.X("total_cost_usd:Q", title="Total cost (USD)"),
                    y=alt.Y("feature:N", title=None, sort="-x"),
                    tooltip=[
                        alt.Tooltip("feature:N", title="Feature"),
                        alt.Tooltip("total_cost_usd:Q", title="Total", format="$.6f"),
                        alt.Tooltip("avg_cost_usd:Q", title="Average", format="$.6f"),
                    ],
                )
                .properties(height=CHART_HEIGHT)
            )
            st.altair_chart(chart)

    st.markdown("### Feature economics")
    st.dataframe(
        feature_summary,
        hide_index=True,
        placeholder="—",
        column_config={
            "feature": st.column_config.TextColumn("Feature", pinned=True),
            "requests": st.column_config.NumberColumn("Requests", format="%d"),
            "success_rate_pct": st.column_config.NumberColumn("Success", format="%.1f%%"),
            "latency_p95_ms": st.column_config.NumberColumn("P95", format="%,.0f ms"),
            "error_rate_pct": st.column_config.NumberColumn("Error", format="%.2f%%"),
            "total_cost_usd": st.column_config.NumberColumn("Total cost", format="$%.6f"),
            "avg_cost_usd": st.column_config.NumberColumn("Avg cost", format="$%.6f"),
            "tokens_total": st.column_config.NumberColumn("Tokens", format="%,d"),
            "quality_avg": st.column_config.ProgressColumn(
                "Quality", min_value=0, max_value=1, format="%.2f"
            ),
        },
    )


def render_explorer(requests: pd.DataFrame, logs: pd.DataFrame) -> None:
    st.markdown("### Request explorer")
    st.caption("Từ correlation ID, lần theo đầy đủ context, request outcome và structured log journey.")
    if requests.empty:
        st.info("Chưa có request để điều tra. Hãy chạy API và load test trước.", icon=":material/info:")
        return

    lookup = requests.set_index("correlation_id").to_dict("index")
    selected_id = st.selectbox(
        "Correlation ID",
        requests["correlation_id"].tolist(),
        format_func=lambda item: (
            f"{item}  ·  {lookup[item]['feature']}  ·  {lookup[item]['status']}  ·  "
            f"{lookup[item]['latency_ms']:,.0f} ms"
        ),
        key="correlation_selector",
    )
    selected = lookup[selected_id]

    with st.container(horizontal=True, gap="small"):
        st.badge(
            selected["status"],
            icon=":material/check_circle:" if selected["status"] == "Success" else ":material/error:",
            color="green" if selected["status"] == "Success" else "red",
        )
        st.badge(str(selected["feature"]), icon=":material/category:", color="blue")
        st.badge(str(selected["model"]), icon=":material/smart_toy:", color="violet")
        st.badge(str(selected["session_id"]), icon=":material/id_card:", color="gray")

    metrics = st.columns(4)
    metrics[0].metric("Latency", f"{selected['latency_ms']:,.0f} ms", icon=":material/timer:", border=True)
    metrics[1].metric(
        "Tokens",
        f"{selected['tokens_in'] + selected['tokens_out']:,.0f}",
        f"{selected['tokens_in']:,.0f} input · {selected['tokens_out']:,.0f} output",
        delta_color="violet",
        delta_arrow="off",
        icon=":material/token:",
        border=True,
    )
    metrics[2].metric(
        "Cost",
        f"{selected['cost_usd'] * 1000:.3f} mUSD",
        icon=":material/payments:",
        border=True,
    )
    metrics[3].metric("Quality", f"{selected['quality_score']:.2f}", icon=":material/verified:", border=True)

    journey = logs[logs["correlation_id"] == selected_id].sort_values("timestamp").copy()
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
    journey["Latency"] = latency_values.map(lambda value: f"{value:,.0f} ms" if pd.notna(value) else "—")

    context_col, message_col = st.columns([1, 1.45])
    with context_col.container(border=True, height="stretch"):
        panel_header("Request context", "Metadata dùng để liên kết metrics, traces và logs")
        st.code(selected_id, language=None)
        st.markdown(f"**Feature:** {selected['feature']}")
        st.markdown(f"**Session:** {selected['session_id']}")
        st.markdown(f"**Model:** {selected['model']}")
        if selected["error_type"]:
            st.error(f"Root error: {selected['error_type']}", icon=":material/error:")
    with message_col.container(border=True, height="stretch"):
        panel_header("Input preview", "Nội dung đã đi qua PII scrubber trước khi hiển thị")
        st.markdown(f"> {selected['message_preview'] or 'Không có message preview'}")
        st.caption(f"Bắt đầu lúc {pd.to_datetime(selected['timestamp']).strftime('%d/%m/%Y %H:%M:%S UTC')}")

    with st.container(border=True):
        panel_header("Structured log journey", f"{len(journey)} event có cùng correlation ID")
        st.dataframe(
            journey[["Thời điểm", "Sự kiện", "Mức độ", "Chi tiết", "Latency"]],
            hide_index=True,
            placeholder="—",
            key="log_journey_table",
            column_config={
                "Thời điểm": st.column_config.DatetimeColumn(format="HH:mm:ss.SSS", pinned=True),
                "Sự kiện": st.column_config.TextColumn(pinned=True),
                "Mức độ": st.column_config.TextColumn(),
                "Chi tiết": st.column_config.TextColumn(width="large"),
                "Latency": st.column_config.TextColumn(),
            },
        )

    details_expander = st.expander(
        "Raw JSON đã chuẩn hóa",
        icon=":material/data_object:",
        on_change="rerun",
    )
    if details_expander.open:
        with details_expander:
            dropped = ["Thời điểm", "Sự kiện", "Mức độ", "Chi tiết", "Latency"]
            for record in journey.drop(columns=dropped).to_dict("records"):
                record["timestamp"] = str(record.get("timestamp", ""))
                safe_record = {
                    key: value
                    for key, value in record.items()
                    if not (isinstance(value, float) and pd.isna(value)) and value is not pd.NA
                }
                st.json(safe_record, expanded=False)


def render_dashboard(
    api_url: str,
    window_minutes: int | None,
    selected_features: list[str],
    selected_statuses: list[str],
) -> None:
    log_version = DEFAULT_LOG_PATH.stat().st_mtime_ns if DEFAULT_LOG_PATH.exists() else 0
    logs = filter_logs(
        cached_logs(str(DEFAULT_LOG_PATH), log_version),
        minutes=window_minutes,
        features=selected_features,
    )
    all_requests = build_requests(logs)
    requests = (
        all_requests[all_requests["status"].isin(selected_statuses)].reset_index(drop=True)
        if selected_statuses
        else all_requests
    )
    if not requests.empty:
        visible_ids = requests["correlation_id"]
        visible_logs = logs[
            logs["correlation_id"].isin(visible_ids)
            | ~logs["event"].isin(["request_received", "response_sent", "request_failed"])
        ].reset_index(drop=True)
    else:
        visible_logs = logs.iloc[0:0].copy()

    snapshot = calculate_snapshot(requests)
    trends = build_trends(requests)
    feature_summary = build_feature_summary(requests)
    slo = load_yaml(SLO_PATH)
    alerts = load_yaml(ALERTS_PATH)
    limits = get_slo_values(slo)
    slo_health = get_slo_health(snapshot, limits)
    health, api_metrics = probe_api(api_url)

    if api_metrics is not None and requests.empty:
        snapshot.update(api_metrics)
        slo_health = get_slo_health(snapshot, limits)

    incidents = health.get("incidents", {}) if health else {}
    active_incidents = [name for name, enabled in incidents.items() if enabled]
    newest = logs["timestamp"].max() if not logs.empty else None
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge(
                "API online" if health else "API offline · log fallback",
                icon=":material/cloud_done:" if health else ":material/cloud_off:",
                color="green" if health else "orange",
            )
            st.badge(
                "Tracing on" if health and health.get("tracing_enabled") else "Tracing off",
                icon=":material/account_tree:",
                color="violet" if health and health.get("tracing_enabled") else "gray",
            )
            st.badge(
                f"{len(logs):,} log events",
                icon=":material/database:",
                color="blue",
            )
            if active_incidents:
                st.badge(
                    f"Incident: {', '.join(active_incidents)}",
                    icon=":material/crisis_alert:",
                    color="red",
                )
        st.caption(
            f"Dữ liệu cuối: {newest.strftime('%d/%m/%Y %H:%M:%S UTC') if pd.notna(newest) else 'chưa có'}"
        )

    overview_tab, reliability_tab, economics_tab, explorer_tab = st.tabs(
        [
            ":material/space_dashboard: Command center",
            ":material/health_and_safety: Reliability",
            ":material/paid: AI economics",
            ":material/troubleshoot: Request explorer",
        ],
        key="dashboard_tabs",
    )
    with overview_tab:
        render_overview(
            snapshot,
            trends,
            requests,
            feature_summary,
            limits,
            slo_health,
            health,
        )
    with reliability_tab:
        render_reliability(
            snapshot,
            visible_logs,
            feature_summary,
            slo,
            alerts,
            health,
            api_metrics,
        )
    with economics_tab:
        render_economics(snapshot, trends, feature_summary, limits)
    with explorer_tab:
        render_explorer(requests, visible_logs)


with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    with st.container(gap=None):
        st.markdown("# :material/monitoring: AI operations")
        st.caption("Production observability workspace · Metrics → Traces → Logs")
    if st.button(":material/refresh: Làm mới dữ liệu", type="primary"):
        st.cache_data.clear()
        st.rerun()

initial_version = DEFAULT_LOG_PATH.stat().st_mtime_ns if DEFAULT_LOG_PATH.exists() else 0
initial_logs = cached_logs(str(DEFAULT_LOG_PATH), initial_version)
feature_options = sorted(
    str(value) for value in initial_logs.get("feature", pd.Series(dtype="object")).dropna().unique()
)

with st.sidebar:
    st.markdown("## :material/tune: Control room")
    st.caption("Bộ lọc áp dụng đồng thời cho mọi góc nhìn.")
    api_url = st.text_input(
        "API endpoint",
        value="http://127.0.0.1:8000",
        icon=":material/link:",
        key="api_endpoint",
    )
    selected_window = st.segmented_control(
        "Khoảng thời gian",
        options=list(WINDOWS),
        default="60 phút",
        required=True,
        width="stretch",
        key="time_window",
    )
    selected_features = st.pills(
        "Feature",
        options=feature_options,
        default=feature_options,
        selection_mode="multi",
        key="feature_filter",
    )
    selected_statuses = st.pills(
        "Trạng thái",
        options=["Success", "Error", "Pending"],
        default=["Success", "Error", "Pending"],
        selection_mode="multi",
        key="status_filter",
    )
    auto_refresh = st.toggle("Tự làm mới mỗi 30 giây", value=True, key="auto_refresh")
    st.space("medium")
    st.markdown("**Workspace context**")
    st.caption(
        f"{len(feature_options)} feature · JSONL + live API\n\n"
        "SLO: 4 · Alert rules: 3 · PII scrubber: enabled"
    )
    st.space("medium")
    st.caption("Day 13 · AI System Observability Lab")

window_minutes = WINDOWS[selected_window or "60 phút"]
live_dashboard = st.fragment(run_every=30 if auto_refresh else None)(render_dashboard)
live_dashboard(
    api_url,
    window_minutes,
    list(selected_features or []),
    list(selected_statuses or []),
)
