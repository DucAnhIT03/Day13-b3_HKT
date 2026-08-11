# CP3 metrics analysis — Thành viên C

## Challenge

- Challenge ID: `day13-k3-observability-v1`
- Cohort: `K3`
- Incident do Coach cung cấp: `rag_slow`
- Feature bị ảnh hưởng: `refund`
- Ngưỡng latency của challenge: `2000 ms`
- Input: 5 query chính thức, concurrency 5

File `config/challenge.json` chỉ được đọc để chạy challenge và không bị chỉnh sửa.

## Phương pháp đo

Hai lần đo dùng cùng 5 query chính thức và cùng concurrency:

1. Baseline trên một tiến trình API sạch, không bật incident.
2. Incident trên một tiến trình API sạch khác, bật `rag_slow` trước khi gửi query.

Mỗi tiến trình bắt đầu với metrics trong bộ nhớ bằng 0. Tracing được tắt trong phép đo này để chỉ thu thập bằng chứng metrics nội bộ và không upload payload ra dịch vụ ngoài.

## Snapshot `/metrics`

| Chỉ số | Baseline | `rag_slow` | Thay đổi | Nhận định |
|---|---:|---:|---:|---|
| Traffic | 5 | 5 | 0 | Cùng số request, so sánh hợp lệ |
| Latency P50 | 158 ms | 2663 ms | +2505 ms | Tăng khoảng 16.9 lần |
| Latency P95 | 164 ms | 2671 ms | +2507 ms | Tăng khoảng 16.3 lần; vượt ngưỡng challenge 2000 ms |
| Latency P99 | 164 ms | 2671 ms | +2507 ms | Tail latency tăng cùng hướng với P95 |
| Error rate | 0.0% | 0.0% | 0 điểm % | Không phải incident lỗi HTTP |
| Input tokens | 162 | 162 | 0 | Không có token input spike |
| Output tokens | 713 | 552 | -161 | Không có token output spike |
| Total cost | 0.0112 USD | 0.0088 USD | -0.0024 USD | Không có cost spike |
| Quality average | 0.86 | 0.86 | 0 | Không có quality regression trong mẫu đo |

Baseline snapshot:

```json
{
  "traffic": 5,
  "latency_p50": 158.0,
  "latency_p95": 164.0,
  "latency_p99": 164.0,
  "avg_cost_usd": 0.0022,
  "total_cost_usd": 0.0112,
  "tokens_in_total": 162,
  "tokens_out_total": 713,
  "error_rate_pct": 0.0,
  "error_breakdown": {},
  "quality_avg": 0.86
}
```

Incident snapshot:

```json
{
  "traffic": 5,
  "latency_p50": 2663.0,
  "latency_p95": 2671.0,
  "latency_p99": 2671.0,
  "avg_cost_usd": 0.0018,
  "total_cost_usd": 0.0088,
  "tokens_in_total": 162,
  "tokens_out_total": 552,
  "error_rate_pct": 0.0,
  "error_breakdown": {},
  "quality_avg": 0.86
}
```

## Kết luận từ metrics

Triệu chứng chính là **latency regression** trên bộ query của feature `refund`. P95 tăng từ 164 ms lên 2671 ms và vượt ngưỡng challenge 2000 ms, trong khi traffic, error rate và quality không xấu đi. Cost và token cũng không tăng, nên metrics không ủng hộ giả thuyết `tool_fail` hoặc `cost_spike`.

Ngưỡng 2000 ms ở trên là ngưỡng riêng của challenge. Dashboard contract hiện dùng SLO line P95 3000 ms; không sửa contract chỉ để khớp incident. Dù chưa vượt SLO 3000 ms, mức tăng 16.3 lần so với baseline vẫn là bất thường rõ ràng.

Metrics chỉ chứng minh triệu chứng, chưa đủ để khẳng định root cause. Thành viên E cần dùng trace trong cùng cửa sổ thời gian để kiểm tra span `run`/`retrieve`, sau đó dùng log có cùng `correlation_id` để hoàn tất chuỗi bằng chứng Metrics → Traces → Logs.

## Evidence còn phải bổ sung khi tích hợp nhóm

- Screenshot dashboard thể hiện P95 baseline và P95 khi incident.
- Trace ID và waterfall của một request `refund` chậm.
- Correlation ID cùng log line chứng minh root cause.
- Đường dẫn các evidence trên trong `submission/REPORT.md` do Thành viên E tổng hợp.
