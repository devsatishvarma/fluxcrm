"""Request correlation middleware."""

import logging
import re
import time
import uuid

from django.http import HttpRequest, HttpResponse

from core.logging import request_id_context

logger = logging.getLogger(__name__)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware:
    """Provide a safe request ID to responses and structured logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_id if _SAFE_REQUEST_ID.fullmatch(supplied_id) else uuid.uuid4().hex
        )
        request.request_id = request_id
        token = request_id_context.set(request_id)
        started_at = time.monotonic()
        try:
            response = self.get_response(request)
            duration_ms = (time.monotonic() - started_at) * 1000
            response.headers["X-Request-ID"] = request_id
            response.headers["Server-Timing"] = f"app;dur={duration_ms:.2f}"
            logger.info(
                "Request completed",
                extra={
                    "http_method": request.method,
                    "http_path": request.path,
                    "http_status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return response
        finally:
            request_id_context.reset(token)
