"""Structured logging helpers that avoid serializing request content."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")

_STANDARD_LOG_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
_SENSITIVE_FIELD_PARTS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
}


class RequestContextFilter(logging.Filter):
    """Attach the current correlation ID to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


class JsonFormatter(logging.Formatter):
    """Emit one safe JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_FIELDS or key == "request_id":
                continue
            if any(part in key.lower() for part in _SENSITIVE_FIELD_PARTS):
                payload[key] = "[REDACTED]"
            elif isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))
