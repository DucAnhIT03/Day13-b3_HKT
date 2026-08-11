# Observability Control Center

Dashboard Streamlit là giao diện vận hành trực tiếp cho sáu nhóm chỉ số của CP2. Giao diện đọc log JSONL đã scrub PII để dựng biểu đồ theo thời gian, đồng thời kiểm tra `/health` và `/metrics` để hiển thị trạng thái API.

## Khởi chạy

Mở API ở terminal thứ nhất:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload --env-file .env
```

Mở dashboard ở terminal thứ hai:

```powershell
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

Truy cập `http://localhost:8501`. Nếu API chưa chạy, dashboard vẫn dùng `data/logs.jsonl` ở chế độ log fallback.

## Các khu vực chính

- **Tổng quan:** Latency, Traffic, Error, Cost, Tokens và Quality với đường ngưỡng SLO.
- **SLO & cảnh báo:** trạng thái bốn SLI và ba alert rules lấy trực tiếp từ file cấu hình.
- **Điều tra:** chọn correlation ID để xem KPI của request và toàn bộ log journey liên quan.

Bộ lọc thời gian neo theo log mới nhất, vì vậy evidence cũ vẫn có thể mở lại để demo. Khi bật tự làm mới, dashboard cập nhật mỗi 30 giây.
