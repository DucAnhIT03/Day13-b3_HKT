# Rubric Day 13 — Tối đa 100 điểm

## A. Điểm nhóm — 60 điểm

### A1. Triển khai kỹ thuật — 30 điểm

- 10 điểm: JSON logging, correlation ID, metadata và PII redaction đúng.
- 10 điểm: traces đầy đủ; prompt v1/v2 có label, version metadata và bằng chứng rollback.
- 10 điểm: dashboard contract/validator, 6 panel, SLO, alert rules và runbook hợp lý.

### A2. Điều tra incident — 10 điểm

- Xác định đúng triệu chứng và root cause.
- Chứng minh được luồng Metrics → Traces → Logs.
- Có fix action và preventive measure phù hợp.

### A3. Demo và giải thích — 20 điểm

- Hệ thống chạy được trong buổi chấm.
- Demo đúng evidence đã nộp.
- Thành viên giải thích được phần mình triển khai.

## B. Điểm cá nhân — 40 điểm

### B1. Báo cáo và mức độ hiểu bài — 20 điểm

- Mô tả rõ phần việc cá nhân.
- Trả lời được câu hỏi về logging, tracing, prompt version, PII, percentile hoặc alert liên quan đến phần việc.

### B2. Bằng chứng đóng góp — 20 điểm

- Có commit/PR cụ thể và có thể kiểm tra.
- Phần khai báo trong report khớp với thay đổi trong Git.

## Bonus

Có thể cộng tối đa 10 điểm cho cost optimization có before/after, automation hữu ích hoặc audit log riêng. Điểm cuối cùng luôn được tính bằng:

```text
min(100, điểm nhóm + điểm cá nhân + bonus)
```

`validate_logs.py` là kiểm tra kỹ thuật nhanh. Điểm do script in ra không phải điểm cuối của rubric này.
