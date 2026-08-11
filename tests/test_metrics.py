from collections import Counter

from app import metrics
from app.metrics import percentile


def test_percentile_basic() -> None:
    assert percentile([100, 200, 300, 400], 50) >= 100


def test_snapshot_error_rate_is_zero_without_requests(monkeypatch) -> None:
    monkeypatch.setattr(metrics, "TRAFFIC", 0)
    monkeypatch.setattr(metrics, "ERRORS", Counter())

    result = metrics.snapshot()

    assert result["error_rate_pct"] == 0.0


def test_snapshot_error_rate_includes_all_error_types(monkeypatch) -> None:
    monkeypatch.setattr(metrics, "TRAFFIC", 6)
    monkeypatch.setattr(
        metrics,
        "ERRORS",
        Counter({"RuntimeError": 2, "TimeoutError": 1}),
    )

    result = metrics.snapshot()

    assert result["error_rate_pct"] == 33.33
    assert result["error_breakdown"] == {
        "RuntimeError": 2,
        "TimeoutError": 1,
    }
