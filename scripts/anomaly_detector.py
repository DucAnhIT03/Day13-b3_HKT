#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

LOG_PATH = Path("data/logs.jsonl")

# Ngưỡng SLO cảnh báo độ trễ
LATENCY_THRESHOLD_MS = 3000

# Regex nhận diện PII
PII_PATTERNS = {
    "email": re.compile(r"[\w.-]+@[\w.-]+\.\w+"),
    "phone_vn": re.compile(r"(?:\+84|0)(?:[ .-]?\d){9}(?!\d)"),
    "cccd": re.compile(r"\b\d{12}\b"),
    "credit_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
    "passport": re.compile(r"\b[A-Z]\d{7,8}\b"),
    "address_vn": re.compile(r"\b(?:số nhà|đường|phường|quận|huyện|tỉnh|thành phố)\b", re.IGNORECASE),
}


def check_record(rec: dict) -> list[str]:
    anomalies = []

    # 1. Kiểm tra vi phạm SLO độ trễ (Latency > 3000ms)
    latency = rec.get("latency_ms")
    if latency is not None and latency > LATENCY_THRESHOLD_MS:
        anomalies.append(
            f"[SLO VIOLATION] Request {rec.get('correlation_id', 'unknown')} latency "
            f"exceeded SLO: {latency}ms (Threshold: {LATENCY_THRESHOLD_MS}ms)"
        )

    # 2. Kiểm tra rò rỉ PII
    raw = json.dumps(rec, ensure_ascii=False)
    # Loại trừ các chuỗi đã được redact để tránh alert giả
    for name, pattern in PII_PATTERNS.items():
        matches = pattern.findall(raw)
        # Lọc ra các match không phải là chuỗi REDACTED
        actual_leaks = [m for m in matches if "[REDACTED_" not in str(m)]
        if actual_leaks:
            anomalies.append(
                f"[PII LEAK ALERT] Detected unredacted PII of type '{name}' in log: {actual_leaks}"
            )

    # 3. Kiểm tra Error status
    if rec.get("level") == "error" or rec.get("event") == "request_failed":
        anomalies.append(
            f"[SYSTEM ERROR] Request failed: {rec.get('correlation_id', 'unknown')} - "
            f"Error type: {rec.get('error_type', 'unknown')} | Detail: {rec.get('payload', {}).get('detail', 'N/A')}"
        )

    return anomalies


def main() -> None:
    print("=== STARTING CUSTOM ANOMALY DETECTOR ===")
    print(f"Monitoring: {LOG_PATH.absolute()}")
    print(f"SLO Latency Threshold: {LATENCY_THRESHOLD_MS}ms")
    print("Press Ctrl+C to stop.")
    print("========================================")

    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.touch()

    # Di chuyển đến cuối file log
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        f.seek(0, 2)  # Go to end of file
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                anomalies = check_record(rec)
                for anomaly in anomalies:
                    print(f"\033[91m⚠️  ANOMALY DETECTED: {anomaly}\033[0m")
            except json.JSONDecodeError:
                continue
            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopping detector. Goodbye!")
        sys.exit(0)
