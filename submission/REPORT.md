# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm:
- Repository URL:
- Commit SHA cuối:
- Thành viên và vai trò: **VŨ ĐĂNG HUY — 2A202601761 — Thành viên A (API & Middleware)**

## 2. Kết quả kỹ thuật

- Điểm baseline `validate_logs.py`: **30/100** (22 bản ghi; 20 bản ghi thiếu trường bắt buộc; 20 bản ghi thiếu enrichment; 0 correlation ID duy nhất; 0 PII leak)
- Tổng số traces:
- Số PII leak còn lại:
- Link/đường dẫn dashboard:

## 3. Logging và tracing

- Evidence correlation ID: `tests/test_middleware.py` kiểm chứng cùng một Correlation ID xuất hiện trong response body, header `x-request-id`, log `request_received`, log `response_sent` và response lỗi.
- Evidence PII redaction:
- Evidence trace waterfall:
- Giải thích một span đáng chú ý:

## 4. Prompt versioning

- Prompt name:
- Version/label baseline:
- Version/label candidate:
- Trace ID của mỗi version:
- Bằng chứng đổi label hoặc rollback:

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`:
- Evidence dashboard:
- SLO đã chọn và lý do:
- Alert rules và runbook:

## 6. Điều tra challenge

- Challenge ID:
- Triệu chứng từ metrics:
- Trace ID liên quan:
- Log line/correlation ID liên quan:
- Root cause:
- Fix action:
- Preventive measure:

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| VŨ ĐĂNG HUY — 2A202601761 | Hoàn thiện `CorrelationIdMiddleware`; tiếp nhận hoặc sinh Correlation ID dạng `req-xxxxxxxx`; bind ID vào `structlog.contextvars`; truyền ID qua request state, log, response body/header; bổ sung `x-response-time-ms`; thêm handler cho HTTP exception và unhandled exception; viết test middleware. | [`c489015`](https://github.com/DucAnhIT03/Day13-K3-Observability/commit/c48901597063c72e26957e9f2114366b2995a72d) | Correlation ID giúp nối các log của cùng request nhưng không thay thế trace/span ID; context phải được xóa sau request để tránh lẫn dữ liệu; response lỗi cần giữ mã điều tra nhưng không làm lộ chi tiết nội bộ. |

### 7.1. Báo cáo cá nhân — VŨ ĐĂNG HUY (2A202601761)

**Vai trò:** Thành viên A — API & Middleware.

**Phần việc đã thực hiện**

- Hoàn thiện `app/middleware.py`: kiểm tra `x-request-id`, giữ ID hợp lệ hoặc sinh ID mới theo định dạng `req-<8 ký tự hex>`.
- Bind Correlation ID vào `structlog.contextvars` để các log trong cùng request tự động nhận cùng ID; gọi `clear_contextvars()` ở đầu và cuối request để tránh rò rỉ context.
- Gắn Correlation ID vào `request.state`, response header `x-request-id` và thêm thời gian xử lý tại `x-response-time-ms`.
- Bổ sung handler trong `app/main.py` cho cả `HTTPException` và lỗi không dự kiến. Response lỗi trả Correlation ID để điều tra, chỉ log loại lỗi thay vì nội dung exception nhạy cảm.
- Viết `tests/test_middleware.py` để kiểm tra luồng sinh ID, tái sử dụng ID từ client, propagation qua log/response và exception handler.

**Kết quả kiểm chứng**

- Lệnh: `.\.venv\Scripts\python.exe -m pytest -q --basetemp=.codex-pytest-tmp-verify -p no:cacheprovider`
- Kết quả: **25 passed**.
- Baseline `validate_logs.py` vẫn là **30/100 trên 22 log cũ**; đây không phải điểm cuối rubric và chưa phản ánh middleware mới cho đến khi tạo lại log bằng load test.

**Mức độ hiểu bài**

- Logging ghi lại từng sự kiện; tracing biểu diễn đường đi và thời gian của request qua các span. Correlation ID là khóa tìm kiếm xuyên log, còn trace ID/span ID mô tả quan hệ trong distributed trace.
- Context variable được dùng để tự động bổ sung Correlation ID vào mọi log trong request. Phải xóa context sau request vì worker có thể phục vụ nhiều request liên tiếp.
- Không tin hoàn toàn ID do client gửi: middleware chỉ nhận đúng định dạng quy định, nếu sai sẽ sinh ID an toàn mới.
- Exception handler không trả stack trace hoặc thông báo lỗi nội bộ cho client. Client chỉ nhận thông báo chung và Correlation ID; kỹ sư dùng ID đó để tìm log liên quan.
- PII scrubbing vẫn cần chạy trên log lỗi. Việc chỉ log `error_type` thay vì nguyên văn exception giúp giảm nguy cơ email, số điện thoại hoặc secret xuất hiện trong log.
- Percentile như p95/p99 phản ánh tail latency tốt hơn trung bình. `x-response-time-ms` của middleware tạo dữ liệu thời gian ở mức request, còn alert nên dựa trên metric tổng hợp và SLO thay vì cảnh báo từ một request đơn lẻ.
