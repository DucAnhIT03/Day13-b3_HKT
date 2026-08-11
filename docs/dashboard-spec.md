# Dashboard specification — Day 13 AI Observability

## 1. Mục tiêu và công cụ

Dashboard cung cấp một màn hình tổng hợp để phát hiện triệu chứng trước khi chuyển sang trace và log điều tra nguyên nhân. Lớp chính có đúng 6 panel: latency, traffic, errors, cost, tokens và quality.

Spec này độc lập với công cụ hiển thị và có thể triển khai bằng Grafana, Streamlit hoặc notebook. Contract chấm điểm bằng máy nằm tại [`config/dashboard.yaml`](../config/dashboard.yaml); hướng dẫn dựng và kiểm tra runtime nằm tại [`DASHBOARD_SETUP.md`](DASHBOARD_SETUP.md).

## 2. Nguồn dữ liệu và phạm vi

- **Nguồn chuẩn để chấm và tạo time series:** `data/logs.jsonl`.
- **Nguồn snapshot để smoke test:** `GET /metrics`.
- **Langfuse:** dùng để mở trace và waterfall khi cần drill-down, không thay thế nguồn dữ liệu của 6 panel.
- **Khoảng thời gian mặc định:** 60 phút gần nhất.
- **Refresh:** 30 giây.
- **Số panel lớp chính:** đúng 6.

Endpoint `/metrics` cung cấp snapshot trong bộ nhớ nhưng không lưu lịch sử. Dashboard runtime dùng log làm nguồn chính để tạo chuỗi thời gian; endpoint được dùng để đối chiếu nhanh giá trị hiện tại.

## 3. Mapping `/metrics` và log

| Nhóm | Field tại `/metrics` | Field/event chuẩn trong log |
|---|---|---|
| Latency | `latency_p50`, `latency_p95`, `latency_p99` | `response_sent.latency_ms` |
| Traffic | `traffic` | số event `request_received` |
| Errors | `error_rate_pct`, `error_breakdown` | `request_failed`, `request_received`, `error_type` |
| Cost | `total_cost_usd`, `avg_cost_usd` | `response_sent.cost_usd` |
| Tokens | `tokens_in_total`, `tokens_out_total` | `response_sent.tokens_in`, `response_sent.tokens_out` |
| Quality | `quality_avg` | `response_sent.quality_score` |

`traffic` tại `/metrics` là số request đã hoàn tất thành công; panel Traffic dùng số `request_received` để phản ánh toàn bộ lưu lượng đến, bao gồm request có thể thất bại.

## 4. Đặc tả 6 panel

| # | ID và tên panel | Hiển thị đề xuất | Event và field | Phép tổng hợp / query giả mã | Đơn vị | Threshold/SLO line |
|---|---|---|---|---|---|---|
| 1 | `latency` — Latency percentiles | Time series 3 đường P50/P95/P99 | `response_sent.latency_ms` | `percentile(latency_ms, [50, 95, 99])` | `ms` | P95 ≤ 3000 ms |
| 2 | `traffic` — Request traffic | Time series hoặc stat kèm rate | `request_received` | `count() by 1m` | `requests/minute` | Rate ≥ 1 request/phút để xác nhận có dữ liệu |
| 3 | `errors` — Error rate and breakdown | Gauge tỷ lệ lỗi kèm bảng theo loại lỗi | `request_received`, `request_failed`, `request_failed.error_type` | `failed / received * 100`; `count_by(error_type)` | `%`, errors | SLO ≤ 2%; critical khi > 5% trong 3 phút |
| 4 | `cost` — Cost over time | Time series chi phí/phút kèm stat tổng | `response_sent.cost_usd` | `sum(cost_usd) by 1m`; `sum(cost_usd)` | `USD` | Ngân sách ngày ≤ 2.5 USD |
| 5 | `tokens` — Input and output tokens | Time series hoặc stacked bar gồm hai series | `response_sent.tokens_in`, `response_sent.tokens_out` | `sum(tokens_in)`; `sum(tokens_out)` | `tokens` | Mỗi tổng theo field ≤ 50,000 token |
| 6 | `quality` — Quality proxy | Gauge hoặc time series trung bình | `response_sent.quality_score` | `mean(quality_score)` | `score 0–1` | Trung bình ≥ 0.75 |

### 4.1 Latency

- Chỉ nhận event `response_sent` có `latency_ms` hợp lệ.
- Hiển thị đồng thời P50, P95 và P99 để quan sát trải nghiệm điển hình và tail latency.
- Đường threshold đặt tại 3000 ms và áp dụng cho P95.
- Khi không có mẫu trong cửa sổ, hiển thị `No data`, không diễn giải thành latency bằng 0.

### 4.2 Traffic

- Mỗi `request_received` được tính một lần.
- Bucket theo phút để có `requests_per_minute`.
- Threshold 1 request/phút kiểm tra tính tươi của dữ liệu, không phải cam kết tải tối thiểu của dịch vụ.

### 4.3 Errors

Tỷ lệ lỗi từ log được tính như sau:

```text
error_rate_pct = count(event == "request_failed")
                 / count(event == "request_received")
                 * 100
```

Khi mẫu số bằng 0, trả về `0.0` và đánh dấu panel chưa có traffic. Bảng breakdown nhóm các event `request_failed` theo `error_type`. Giá trị snapshot trong `app/metrics.py` dùng công thức tương đương:

```text
sum(ERRORS) / (TRAFFIC + sum(ERRORS)) * 100
```

### 4.4 Cost

- Một series biểu diễn tổng `cost_usd` theo phút.
- Một stat biểu diễn tổng chi phí trong cửa sổ.
- Không dùng `avg_cost_usd` thay cho tổng khi so với threshold ngân sách.

### 4.5 Tokens

- Giữ riêng hai series input và output để phát hiện loại token gây tăng sử dụng.
- Tổng hợp bằng `sum`, không dùng trung bình.
- Legend ghi rõ `tokens_in` và `tokens_out`.

### 4.6 Quality

- Dùng trung bình `quality_score` của event `response_sent` trong cửa sổ.
- Miền hiển thị cố định từ 0 đến 1.
- Đường threshold đặt tại 0.75; giá trị thấp hơn threshold được đánh dấu cảnh báo.

## 5. Quy tắc trình bày và drill-down

- Tên panel, đơn vị, time range và threshold phải nhìn thấy trong evidence.
- Latency, error, cost và quality phải có SLO line và nhãn trạng thái `OK`, `Warning` hoặc `Critical`; không chỉ dựa vào màu.
- Tooltip hiển thị timestamp, giá trị và đơn vị. Cả 6 panel dùng cùng time range.
- Không đưa PII hoặc message thô vào label, legend hay tooltip.
- `error_breakdown` dùng để khoanh vùng sau khi tỷ lệ lỗi bất thường; không tạo alert theo tên hàm hoặc implementation nội bộ.
- Khi một panel bất thường, lọc log theo cùng khoảng thời gian, lấy `correlation_id`, rồi mở trace Langfuse tương ứng.
- Trace waterfall và log raw là màn hình drill-down, không phải panel bổ sung.

## 6. SLO được sử dụng

Các SLO chính thức nằm tại [`config/slo.yaml`](../config/slo.yaml): P95 dưới 3 giây, error rate dưới 2%, chi phí ngày không vượt 2.50 USD và quality trung bình tối thiểu 0.75. Alert có thể dùng ngưỡng cao hơn SLO để tránh paging vì dao động ngắn, nhưng dashboard vẫn phải thể hiện mọi SLO violation.

## 7. Kiểm tra và evidence

```powershell
python scripts/validate_dashboard.py
curl http://127.0.0.1:8000/metrics
```

Kết quả validator hợp lệ phải chứa:

```text
HỢP LỆ: 6/6 panel có trong dashboard contract.
```

Checklist evidence:

- Dashboard có đúng 6 panel và cùng time range 60 phút.
- Mỗi panel hiển thị đúng tên, đơn vị và threshold.
- Latency có đủ P50/P95/P99; Errors có cả tỷ lệ và breakdown.
- Cost và Tokens dùng phép tổng; Quality dùng mean.
- Ảnh baseline nhìn rõ P95, error rate và total cost.
- Screenshot runtime được lưu trong `submission/evidence/` và dẫn bằng đường dẫn tương đối trong `submission/REPORT.md`.
- Nếu chỉ nộp spec, đính kèm validator output cùng commit chứa `dashboard-spec.md`, `dashboard.yaml` và `slo.yaml`.
