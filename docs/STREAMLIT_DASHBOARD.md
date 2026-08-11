# AI operations dashboard

Dashboard Streamlit là giao diện vận hành trực tiếp cho toàn bộ dữ liệu observability của CP2 và CP3. Giao diện đọc log JSONL đã scrub PII để dựng biểu đồ theo từng request, đồng thời kiểm tra `/health` và `/metrics` để hiển thị trạng thái API, tracing và incident.

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

## Bốn không gian vận hành

- **Command center:** trạng thái tổng thể, tám KPI quan trọng, latency từng request, traffic outcomes, feature demand và request gần đây.
- **Reliability:** trạng thái API/tracing/incident/log coverage, bốn SLO, ba alert rules và so sánh reliability theo feature.
- **AI economics:** average cost, budget utilization, token split, quality efficiency và bảng cost/quality theo feature.
- **Request explorer:** chọn correlation ID để xem context, KPI, input preview, structured log journey và raw JSON đã chuẩn hóa.

## Bộ lọc và dữ liệu

- Time range mặc định 60 phút, có lựa chọn 15 phút, 24 giờ hoặc toàn bộ dữ liệu.
- Có thể lọc đồng thời theo feature và trạng thái request.
- Cửa sổ thời gian neo theo log mới nhất để evidence lịch sử vẫn mở lại được khi demo.
- Khi bật tự làm mới, dữ liệu được cập nhật mỗi 30 giây.
- SLO và alert rules được đọc trực tiếp từ `config/slo.yaml` và `config/alert_rules.yaml`.
