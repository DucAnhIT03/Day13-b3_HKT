# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: HKT
- Repository URL: [https://github.com/DucAnhIT03/Day13-b3_HKT](https://github.com/DucAnhIT03/Day13-b3_HKT)
- Commit SHA triển khai chính: [`13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f)
- Thành viên và vai trò:
  - **Nguyễn Đức Anh** — `2A202601063` — Thành viên A, API & Middleware.
  - **Phan Văn Hiếu** — `2A202601227` — Thành viên B, Security Engineer.
  - **Nguyễn Huy Tỏa** — `2A202601697` — Thành viên C, Metrics & Dashboard.
  - **Tạ Long Khánh** — `2A202601197` — Thành viên D, SRE & Alerts Engineer.
  - **Vũ Đăng Huy** — `2A202601761` — Thành viên E, QA & Chief Investigator.

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: 100/100 (kết quả cuối: 13 log records, 7 correlation IDs, không thiếu metadata) — [`evidence/final-validation.txt`](evidence/final-validation.txt)
- Tổng số traces: 0 — runtime xác nhận `tracing_enabled=false` vì chưa có Langfuse credentials; không tạo evidence giả
- Số PII leak còn lại: 0
- Link/đường dẫn dashboard: [`docs/dashboard-spec.md`](../docs/dashboard-spec.md) và [`config/dashboard.yaml`](../config/dashboard.yaml)

## 3. Logging và tracing

- Evidence correlation ID: [`evidence/cp1-redacted-log.jsonl`](evidence/cp1-redacted-log.jsonl), [`evidence/cp3-correlation-log.jsonl`](evidence/cp3-correlation-log.jsonl) và [ảnh log correlation](evidence/cp3-log-correlation.png)
- Evidence PII redaction: [`evidence/cp1-redacted-log.jsonl`](evidence/cp1-redacted-log.jsonl)
- Evidence trace waterfall: Chưa có; [`evidence/cp3-runtime-status.json`](evidence/cp3-runtime-status.json) ghi nhận `tracing_enabled=false`. Code đã instrument span `run → retrieve → generate`, nhưng cần Langfuse credentials để tạo trace ID và ảnh waterfall thật.
- Giải thích một span đáng chú ý: span `retrieve` là điểm cần quan sát trong incident `rag_slow`; metrics và code cho thấy retrieval thêm 2,5 giây, còn `generate` không có cost/token spike. Input/output capture của hai sub-span được tắt để tránh gửi prompt chứa PII lên trace.

## 4. Prompt versioning

- Prompt name: `day13-chat`
- Version/label baseline: `local-v1` / `production`, source `local` khi Langfuse chưa khả dụng
- Version/label candidate: Chưa tạo trên Langfuse vì chưa có project credentials
- Trace ID của mỗi version: Chưa có; runtime không xuất trace
- Bằng chứng đổi label hoặc rollback: Chưa có; cần hoàn thành trên Langfuse project thật, không thể thay bằng dữ liệu local hoặc ảnh giả

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: 6/6 panel hợp lệ — [`evidence/cp2-dashboard-validator.txt`](evidence/cp2-dashboard-validator.txt)
- Evidence dashboard: [dashboard 6 nhóm chỉ số](evidence/cp2-dashboard-six-panels.png), [`docs/dashboard-spec.md`](../docs/dashboard-spec.md) và [`config/dashboard.yaml`](../config/dashboard.yaml)
- SLO đã chọn và lý do: P95 ≤ 3 giây, error rate ≤ 2%, daily cost ≤ 2,50 USD và quality trung bình ≥ 0,75; các ngưỡng cân bằng trải nghiệm người dùng, độ tin cậy, ngân sách và chất lượng câu trả lời.
- Alert rules và runbook: [`config/alert_rules.yaml`](../config/alert_rules.yaml) và [`docs/alerts.md`](../docs/alerts.md)

## 6. Điều tra challenge

- Challenge ID: `day13-k3-observability-v1` — official scenario `rag_slow`, affected feature `refund`; `config/challenge.json` giữ nguyên SHA-256 `F909028D04C9722A5C566C268742D1732CE929438E2DC5D471B06C75393A8A73`.
- Triệu chứng từ metrics: với cùng 5 query và concurrency 5, P95 tăng từ **151 ms** lên **2.652 ms** (+2.501 ms, 17,6 lần), vượt challenge threshold 2.000 ms khoảng 652 ms. Error rate vẫn 0%, quality 0,86 và cost không tăng đáng kể, vì vậy sự cố là latency chứ không phải error/cost/quality. Evidence: [`evidence/cp3-metrics-comparison.png`](evidence/cp3-metrics-comparison.png) và [`evidence/cp3-metrics-comparison.json`](evidence/cp3-metrics-comparison.json).
- Trace ID liên quan: Không có trace ID vì `tracing_enabled=false` khi chạy challenge (Langfuse credentials chưa được cấu hình). Điều tra dùng fallback correlation ID từ log; instrumentation `run → retrieve/generate` đã sẵn sàng cho lần chạy lại sau khi cấu hình Langfuse.
- Log line/correlation ID liên quan: `req-36c03d88` nối `request_received` của feature `refund` với `response_sent latency_ms=2651`; log control trước đó xác nhận `incident_enabled` có payload `rag_slow`. Evidence: [`evidence/cp3-correlation-log.jsonl`](evidence/cp3-correlation-log.jsonl), [ảnh log raw](evidence/cp3-log-correlation.png) và [`evidence/cp3-incident-load-test.txt`](evidence/cp3-incident-load-test.txt).
- Root cause: challenge bật `STATE["rag_slow"]`; `retrieve()` trong `app/mock_rag.py` thực thi `time.sleep(2.5)`. Mức tăng P95 đo được là 2.501 ms, khớp gần như chính xác delay 2,5 giây. Vì lời gọi đồng bộ này nằm trong async request handler, nó còn chặn event loop và gây head-of-line blocking: client latency ở concurrency 5 tăng tới 10,6–13,3 giây dù agent latency từng request khoảng 2,65 giây. Evidence: [`evidence/cp3-root-cause.txt`](evidence/cp3-root-cause.txt).
- Fix action: thay retrieval blocking bằng async I/O có timeout; nếu SDK chỉ hỗ trợ đồng bộ thì chạy qua thread pool. Thêm circuit breaker/cache/fallback cho RAG để vẫn trả lời có kiểm soát khi dependency chậm, đồng thời giới hạn concurrency để ngăn queue tăng không giới hạn.
- Preventive measure: theo dõi riêng latency span `retrieve` và end-to-end response time ở middleware, alert theo P95/SLO, đặt timeout budget cho từng dependency, chạy regression load test có concurrency và diễn tập fallback định kỳ. Luôn giữ `correlation_id` trong trace metadata để nối Metrics → Trace → Log.

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

Repo sử dụng một integration commit chung cho phần triển khai; bảng dưới đây dẫn cùng commit và ghi rõ phạm vi file/nhiệm vụ của từng thành viên, không thay thế bằng lịch sử commit cá nhân giả.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| Nguyễn Đức Anh (`2A202601063`) | CP1 API & Middleware: hoàn thiện [`app/middleware.py`](../app/middleware.py), gán/propagate Correlation ID, response-time header và generic exception handler trong [`app/main.py`](../app/main.py). | [Integration commit `13bca82`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f) | `clear_contextvars()` ngăn request mới kế thừa context cũ; correlation ID phải xuất hiện cả response thành công lẫn lỗi để truy vết được toàn trình. |
| Phan Văn Hiếu (`2A202601227`) | CP1 Security: bật scrub processor trong [`app/logging_config.py`](../app/logging_config.py), mở rộng regex email/phone/CCCD/thẻ/passport/địa chỉ tại [`app/pii.py`](../app/pii.py), kiểm chứng log không còn PII thô. | [Integration commit `13bca82`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f) | PII cần được giảm thiểu từ đầu bằng hash/summarize và scrub lần cuối trước khi ghi file; regex địa chỉ phải xử lý cả chữ hoa/thường. |
| Nguyễn Huy Tỏa (`2A202601697`) | CP1/CP2 Metrics & Dashboard: bổ sung `error_rate_pct` trong [`app/metrics.py`](../app/metrics.py), hoàn thiện [`docs/dashboard-spec.md`](../docs/dashboard-spec.md) và dashboard evidence đủ 6 nhóm chỉ số. | [Integration commit `13bca82`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f) | Error rate phải dùng cả request thành công và thất bại làm mẫu số; dashboard cần cùng time range, đơn vị và SLO line để so sánh đúng incident. |
| Tạ Long Khánh (`2A202601197`) | CP2 SRE & Alerts: thiết lập [`config/slo.yaml`](../config/slo.yaml), ba symptom-based rules trong [`config/alert_rules.yaml`](../config/alert_rules.yaml) và runbook Metrics → Traces → Logs tại [`docs/alerts.md`](../docs/alerts.md). | [Integration commit `13bca82`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f) | Alert theo triệu chứng/SLO phản ánh tác động người dùng và ít nhiễu hơn alert phụ thuộc tên hàm hoặc implementation có thể thay đổi. |
| Vũ Đăng Huy (`2A202601761`) | CP2/CP3 QA & Investigation: chạy load test, instrument sub-spans RAG/LLM trong [`app/mock_rag.py`](../app/mock_rag.py) và [`app/mock_llm.py`](../app/mock_llm.py), điều tra official challenge `rag_slow`, tổng hợp evidence và báo cáo. | [Integration commit `13bca82`](https://github.com/DucAnhIT03/Day13-b3_HKT/commit/13bca8203d0fa0d431ebdf6c0147f7e4530e2b6f) | Metrics phát hiện latency spike, trace giúp khoanh vùng `retrieve`, log/correlation ID chứng minh hành trình request; blocking I/O trong async handler gây head-of-line blocking. |
