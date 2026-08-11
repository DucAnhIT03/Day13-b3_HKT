from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars


CORRELATION_ID_PATTERN = re.compile(r"^req-[0-9a-fA-F]{8}$")


def _correlation_id(request: Request) -> str:
    """Reuse a valid client request ID, otherwise create a safe local one."""
    supplied_id = request.headers.get("x-request-id", "").strip()
    if CORRELATION_ID_PATTERN.fullmatch(supplied_id):
        return supplied_id.lower()
    return f"req-{uuid.uuid4().hex[:8]}"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()
        correlation_id = _correlation_id(request)
        bind_contextvars(correlation_id=correlation_id)

        request.state.correlation_id = correlation_id
        request.state.request_started_at = time.perf_counter()

        start = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            response.headers["x-request-id"] = correlation_id
            response.headers["x-response-time-ms"] = f"{elapsed_ms:.2f}"
            return response
        finally:
            clear_contextvars()
