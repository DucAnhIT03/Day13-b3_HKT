# Dashboard specification — Day 13 AI Observability

Dashboard runtime được triển khai bằng Streamlit tại [`streamlit_app.py`](../streamlit_app.py). Giao diện kiểm tra trạng thái qua `GET /health` và `GET /metrics`, đồng thời dùng `data/logs.jsonl` để tái tính toán biểu đồ theo thời gian và drill-down theo correlation ID. Contract máy đọc nằm tại [`config/dashboard.yaml`](../config/dashboard.yaml), time range mặc định là **60 phút** và refresh mỗi **30 giây**. Hướng dẫn chạy nằm tại [`docs/STREAMLIT_DASHBOARD.md`](STREAMLIT_DASHBOARD.md).

## Bố cục 6 panel chính

| # | Panel | Nguồn và phép tính | Hiển thị | Đơn vị | Threshold/SLO line |
|---|---|---|---|---|---|
| 1 | Latency percentiles | `/metrics`: `latency_p50`, `latency_p95`, `latency_p99` | Ba single value kèm line chart theo thời gian | ms | P95 ≤ 3.000 ms |
| 2 | Request traffic | `/metrics`: `traffic`; khi có time-series dùng chênh lệch counter theo phút | Counter tổng và request/phút | requests, requests/min | Activity baseline ≥ 1 request/phút; không coi lưu lượng thấp là lỗi SLO |
| 3 | Error rate and breakdown | `/metrics`: `error_rate_pct`, `error_breakdown` | Gauge tỷ lệ lỗi và bảng theo `error_type` | %, errors | SLO ≤ 2%; critical alert khi > 5% trong 3 phút |
| 4 | Cost over time | `/metrics`: `total_cost_usd`, `avg_cost_usd`; daily cost là tổng trong rolling 24 giờ | Line tổng chi phí và single value chi phí trung bình | USD | Ngân sách ngày ≤ 2,50 USD |
| 5 | Input and output tokens | `/metrics`: `tokens_in_total`, `tokens_out_total` | Hai series/counter input và output | tokens | Guardrail 50.000 tokens trong cửa sổ 60 phút |
| 6 | Quality proxy | `/metrics`: `quality_avg` | Single value và trend | score 0–1 | Trung bình ≥ 0,75 |

## Quy tắc hiển thị và điều tra

- Panel latency, error, cost và quality phải luôn vẽ SLO line; màu không phải tín hiệu duy nhất, mỗi trạng thái phải có nhãn `OK`, `Warning` hoặc `Critical`.
- Hover/tooltip phải hiển thị timestamp, giá trị và đơn vị. Mọi panel dùng cùng time range để đối chiếu được cùng một incident.
- Từ một điểm bất thường, điều tra theo luồng **Metrics → Trace → Log**: lấy khung thời gian và feature từ panel, mở trace Langfuse tương ứng, sau đó dùng `metadata.correlation_id` để tìm log JSON.
- `error_breakdown` chỉ dùng để khoanh vùng sau khi alert tỷ lệ lỗi đã kích hoạt; không tạo alert theo tên hàm hay implementation nội bộ.
- Dashboard cấp cao chỉ có đúng 6 panel trên; trace waterfall và log raw là màn hình drill-down, không phải panel bổ sung.

## SLO được sử dụng

Các SLO chính thức nằm tại [`config/slo.yaml`](../config/slo.yaml): P95 dưới 3 giây, error rate dưới 2%, chi phí ngày không vượt 2,50 USD và quality trung bình tối thiểu 0,75. Alert có thể dùng ngưỡng cao hơn SLO để tránh paging vì dao động ngắn, nhưng không được che giấu SLO violation trên dashboard.

## Kiểm tra và evidence

Chạy:

```bash
python scripts/validate_dashboard.py
curl http://127.0.0.1:8000/metrics
```

Evidence cần cho thấy đủ tên 6 panel, time range 60 phút, đơn vị và threshold. Ảnh runtime hiện tại nằm tại [`submission/evidence/cp2-streamlit-dashboard.png`](../submission/evidence/cp2-streamlit-dashboard.png); file validator vẫn được giữ để chứng minh contract cấu hình hợp lệ.
