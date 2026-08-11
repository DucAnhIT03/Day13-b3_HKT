# Alert runbooks

Mọi alert bên dưới đều dựa trên triệu chứng hoặc SLO mà người dùng cảm nhận được. Sau khi alert kích hoạt, điều tra theo cùng một luồng **Metrics → Traces → Logs** và ghi lại timestamp, trace ID cùng correlation ID trước khi thay đổi hệ thống.

## Alert 1

- **Tên:** `high_latency_p95`
- **Severity:** warning
- **SLI/SLO liên quan:** `latency_p95_ms`; P95 ≤ 3.000 ms cho 99,5% request trong cửa sổ SLO 28 ngày.
- **Điều kiện và thời gian duy trì:** `latency_p95 > 3000ms for 5 minutes`.
- **Ảnh hưởng tới người dùng:** phần lớn request vẫn thành công nhưng ít nhất 5% request chậm hơn 3 giây; người dùng thấy chat phản hồi chậm hoặc timeout phía client.
- **Ba bước kiểm tra đầu tiên:**
  1. Mở panel Latency trong đúng cửa sổ alert; xác nhận P50/P95/P99, traffic và error rate để phân biệt chậm toàn hệ thống với tail latency.
  2. Trong Langfuse, lọc trace theo thời gian và feature; mở các trace chậm nhất, so sánh thời gian span `retrieve` và `generate`, ghi lại trace ID cùng `metadata.correlation_id`.
  3. Tìm `correlation_id` đó trong `data/logs.jsonl`; kiểm tra `latency_ms`, feature, model và event lỗi liền kề để xác nhận thành phần gây chậm.
- **Mitigation tạm thời:** giảm concurrency hoặc rate-limit lưu lượng mới; chuyển feature bị ảnh hưởng sang fallback nhanh/cached response; vô hiệu hóa dependency chậm bằng circuit breaker nếu có. Không xóa log hoặc restart trước khi lưu trace/correlation ID.
- **Owner:** on-call-engineer.

## Alert 2

- **Tên:** `elevated_error_rate`
- **Severity:** critical
- **SLI/SLO liên quan:** `error_rate_pct`; error rate ≤ 2% cho 99% cửa sổ SLO.
- **Điều kiện và thời gian duy trì:** `error_rate_pct > 5 for 3 minutes`.
- **Ảnh hưởng tới người dùng:** hơn 5% request thất bại trong ít nhất 3 phút; người dùng nhận HTTP 5xx hoặc không nhận được câu trả lời.
- **Ba bước kiểm tra đầu tiên:**
  1. Xác nhận error rate, traffic và `error_breakdown` trên dashboard; kiểm tra alert có đủ mẫu request và không phải một lần lỗi đơn lẻ.
  2. Mở các trace lỗi trong Langfuse ở cùng cửa sổ; xác định span thất bại đầu tiên (`retrieve` hoặc `generate`) và ghi trace ID/correlation ID.
  3. Tra log theo correlation ID; đọc `request_failed.error_type` và các event trước đó, đồng thời so sánh health/dependency status để xác nhận root cause.
- **Mitigation tạm thời:** rollback bản phát hành gần nhất hoặc tắt feature gây lỗi; kích hoạt fallback cho dependency; giới hạn request retry để tránh khuếch đại sự cố. Theo dõi error rate trở lại dưới 2% trước khi đóng incident.
- **Owner:** on-call-engineer.

## Alert 3

- **Tên:** `cost_budget_exceeded`
- **Severity:** warning
- **SLI/SLO liên quan:** `daily_cost_usd`; chi phí rolling 24 giờ ≤ 2,50 USD.
- **Điều kiện và thời gian duy trì:** `daily_cost_usd > 2.5`.
- **Ảnh hưởng tới người dùng:** không nhất thiết có lỗi tức thời, nhưng ngân sách bị vượt có thể dẫn tới hết quota, throttling hoặc phải dừng dịch vụ sau đó.
- **Ba bước kiểm tra đầu tiên:**
  1. Xác nhận rolling 24-hour cost, `avg_cost_usd`, traffic và tổng input/output tokens; phân biệt tăng do traffic hợp lệ với tăng chi phí trên mỗi request.
  2. Trong Langfuse, nhóm trace theo feature/model và sắp xếp theo cost/tokens; mở trace đắt nhất, ghi trace ID, token usage và correlation ID.
  3. Tìm correlation ID trong log; đối chiếu `tokens_in`, `tokens_out`, `cost_usd`, feature và session để phát hiện response quá dài, retry hoặc workload bất thường.
- **Mitigation tạm thời:** áp token/output cap, rate-limit feature không thiết yếu và chuyển sang model/fallback rẻ hơn nếu policy cho phép; không xóa trace chi phí cao vì đó là evidence để tối ưu sau incident.
- **Owner:** team-lead.
