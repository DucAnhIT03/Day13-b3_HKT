# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: HKT
- Repository URL: [https://github.com/DucAnhIT03/Day13-b3_HKT](https://github.com/DucAnhIT03/Day13-b3_HKT)
- Commit SHA triển khai chính: [`13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f)
- Thành viên và vai trò:
  - Nguyễn Đức Anh — mã học viên `2A202601063` — Developer/Observability Engineer.
  - **Phan Văn Hiếu — mã sinh viên `2A202601227` — Thành viên C (Metrics & Dashboard); phụ trách đo `error_rate_pct`, thiết kế spec 6 nhóm chỉ số, triển khai dashboard runtime và phân tích metrics CP3.**

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: 100/100 (kết quả cuối: 43 log records, 20 correlation IDs, không thiếu metadata) — [`evidence/final-validation.txt`](evidence/final-validation.txt)
- Tổng số traces có evidence trong nhánh hiện tại: 0 — Langfuse credentials đã được cấu hình cục bộ nhưng nhóm chưa tạo và đưa danh sách trace hợp lệ vào `submission/evidence/`; không tạo evidence giả
- Số PII leak còn lại: 0
- Link/đường dẫn dashboard: runtime `GET /dashboard`, [`docs/dashboard-spec.md`](../docs/dashboard-spec.md) và [`config/dashboard.yaml`](../config/dashboard.yaml)

## 3. Logging và tracing

- Evidence correlation ID: [`evidence/cp1-redacted-log.jsonl`](evidence/cp1-redacted-log.jsonl), [`evidence/cp3-correlation-log.jsonl`](evidence/cp3-correlation-log.jsonl) và [ảnh log correlation](evidence/cp3-log-correlation.png)
- Evidence PII redaction: [`evidence/cp1-redacted-log.jsonl`](evidence/cp1-redacted-log.jsonl)
- Evidence trace waterfall: Chưa có; [`evidence/cp3-runtime-status.json`](evidence/cp3-runtime-status.json) ghi nhận trạng thái của lần chạy challenge cũ là `tracing_enabled=false`. Credentials hiện đã được cấu hình cục bộ, vì vậy nhóm cần chạy lại và chụp waterfall thật. Code đã instrument span `run → retrieve → generate`.
- Giải thích một span đáng chú ý: span `retrieve` là điểm cần quan sát trong incident `rag_slow`; metrics và code cho thấy retrieval thêm 2,5 giây, còn `generate` không có cost/token spike. Input/output capture của hai sub-span được tắt để tránh gửi prompt chứa PII lên trace.

## 4. Prompt versioning

- Prompt name: `day13-chat`
- Version/label baseline: `local-v1` / `production`, source `local` khi Langfuse chưa khả dụng
- Version/label candidate: Chưa tạo và chưa có evidence trên Langfuse
- Trace ID của mỗi version: Chưa có; runtime không xuất trace
- Bằng chứng đổi label hoặc rollback: Chưa có; cần hoàn thành trên Langfuse project thật, không thể thay bằng dữ liệu local hoặc ảnh giả

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: 6/6 panel hợp lệ — [`evidence/cp2-dashboard-validator.txt`](evidence/cp2-dashboard-validator.txt)
- Evidence dashboard: [dashboard runtime 6 nhóm chỉ số](evidence/cp2-dashboard-runtime.png), [payload runtime máy đọc được](evidence/cp2-dashboard-runtime.json), [ảnh dashboard spec](evidence/cp2-dashboard-six-panels.png), [`docs/dashboard-spec.md`](../docs/dashboard-spec.md) và [`config/dashboard.yaml`](../config/dashboard.yaml)
- SLO đã chọn và lý do: P95 ≤ 3 giây, error rate ≤ 2%, daily cost ≤ 2,50 USD và quality trung bình ≥ 0,75; các ngưỡng cân bằng trải nghiệm người dùng, độ tin cậy, ngân sách và chất lượng câu trả lời.
- Alert rules và runbook: [`config/alert_rules.yaml`](../config/alert_rules.yaml) và [`docs/alerts.md`](../docs/alerts.md)

## 6. Điều tra challenge

- Challenge ID: `day13-k3-observability-v1` — official scenario `rag_slow`, affected feature `refund`; `config/challenge.json` giữ nguyên SHA-256 `F909028D04C9722A5C566C268742D1732CE929438E2DC5D471B06C75393A8A73`.
- Triệu chứng từ metrics: với cùng 5 query và concurrency 5, P95 tăng từ **151 ms** lên **2.652 ms** (+2.501 ms, 17,6 lần), vượt challenge threshold 2.000 ms khoảng 652 ms. Error rate vẫn 0%, quality 0,86 và cost không tăng đáng kể, vì vậy sự cố là latency chứ không phải error/cost/quality. Evidence: [`evidence/cp3-metrics-comparison.png`](evidence/cp3-metrics-comparison.png) và [`evidence/cp3-metrics-comparison.json`](evidence/cp3-metrics-comparison.json).
- Trace ID liên quan: Không có trace ID trong evidence của lần chạy challenge cũ vì khi đó `tracing_enabled=false`. Điều tra dùng fallback correlation ID từ log; sau khi đã cấu hình Langfuse, nhóm vẫn cần chạy lại challenge để bổ sung trace ID và waterfall.
- Log line/correlation ID liên quan: `req-36c03d88` nối `request_received` của feature `refund` với `response_sent latency_ms=2651`; log control trước đó xác nhận `incident_enabled` có payload `rag_slow`. Evidence: [`evidence/cp3-correlation-log.jsonl`](evidence/cp3-correlation-log.jsonl), [ảnh log raw](evidence/cp3-log-correlation.png) và [`evidence/cp3-incident-load-test.txt`](evidence/cp3-incident-load-test.txt).
- Root cause: challenge bật `STATE["rag_slow"]`; `retrieve()` trong `app/mock_rag.py` thực thi `time.sleep(2.5)`. Mức tăng P95 đo được là 2.501 ms, khớp gần như chính xác delay 2,5 giây. Vì lời gọi đồng bộ này nằm trong async request handler, nó còn chặn event loop và gây head-of-line blocking: client latency ở concurrency 5 tăng tới 10,6–13,3 giây dù agent latency từng request khoảng 2,65 giây. Evidence: [`evidence/cp3-root-cause.txt`](evidence/cp3-root-cause.txt).
- Fix action: thay retrieval blocking bằng async I/O có timeout; nếu SDK chỉ hỗ trợ đồng bộ thì chạy qua thread pool. Thêm circuit breaker/cache/fallback cho RAG để vẫn trả lời có kiểm soát khi dependency chậm, đồng thời giới hạn concurrency để ngăn queue tăng không giới hạn.
- Preventive measure: theo dõi riêng latency span `retrieve` và end-to-end response time ở middleware, alert theo P95/SLO, đặt timeout budget cho từng dependency, chạy regression load test có concurrency và diễn tập fallback định kỳ. Luôn giữ `correlation_id` trong trace metadata để nối Metrics → Trace → Log.

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| Nguyễn Đức Anh (`2A202601063`) | Hoàn thiện correlation ID, structured logging, PII scrubbing, trace metadata/sub-spans, error-rate metrics, dashboard 6 panel, SLO, alert rules/runbook; chạy official challenge `rag_slow`, phân tích Metrics → Logs và tổng hợp evidence/report. | [Commit `13bca82`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f) | Correlation ID giúp nối request xuyên lớp; symptom-based alert ổn định hơn implementation alert; metrics phát hiện triệu chứng còn trace/log mới khoanh vùng được root cause; blocking I/O trong async handler gây head-of-line blocking. |
| **Phan Văn Hiếu (`2A202601227`) — Thành viên C** | CP1/CP2: bổ sung và kiểm thử `error_rate_pct`, thiết kế dashboard spec đủ 6 nhóm chỉ số, triển khai `/dashboard` đọc log runtime; CP3: phân tích biến động metrics và bằng chứng nguyên nhân latency. | [Nhánh `2A202601227-PhanVanHieu`](https://github.com/DucAnhIT03/Day13-b3_HKT/tree/2A202601227-PhanVanHieu), [commit metrics `a1dc36b`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/a1dc36b76f314b85500e31b9871f2b60158131e3) | Biết tính error rate với mẫu số đúng, phân biệt snapshot trong bộ nhớ với time series từ log, và dùng Metrics → Traces → Logs để điều tra thay vì suy đoán từ một chỉ số. |
