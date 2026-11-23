"""Request correlation middleware."""

import logging
import re
import time
import uuid

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

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
            log_path = request.path
            if "/password-reset/" in log_path and log_path.count("/") >= 4:
                log_path = "/password-reset/<redacted>/"
            logger.info(
                "Request completed",
                extra={
                    "http_method": request.method,
                    "http_path": log_path,
                    "http_status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return response
        finally:
            request_id_context.reset(token)


class AccessDenialMiddleware:
    """Write denial rows after the request transaction has finished."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from core.policy import begin_denial_scope, end_denial_scope, flush_denials

        token = begin_denial_scope()
        try:
            response = self.get_response(request)
        finally:
            pending = end_denial_scope(token)
            flush_denials(pending, getattr(request, "request_id", ""))
        return response


class SetupRequiredMiddleware:
    """Send an unconfigured installation to first-run setup."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(
            ("/health", "/ready", "/setup", "/static", "/brand/")
        ):
            return self.get_response(request)
        from identity.models import User

        if not User.objects.exists():
            return redirect("core:setup")
        return self.get_response(request)


class MFAEnforcementMiddleware:
    """Require TOTP enrollment and verification when MFA_REQUIRED is on."""

    _PUBLIC_PREFIXES = (
        "/health",
        "/ready",
        "/setup",
        "/static",
        "/brand/",
        "/login",
        "/logout",
        "/password-reset",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from core.mfa import mfa_enabled, user_has_mfa, user_is_mfa_verified

        if not mfa_enabled():
            return self.get_response(request)
        path = request.path
        if path.startswith(self._PUBLIC_PREFIXES):
            return self.get_response(request)
        user = request.user
        if not user.is_authenticated:
            return self.get_response(request)
        if user_is_mfa_verified(request):
            return self.get_response(request)
        if user_has_mfa(user):
            if path.startswith("/mfa/verify"):
                return self.get_response(request)
            return redirect("core:mfa_verify")
        if path.startswith("/mfa/enroll") or path.startswith("/mfa/backup-codes"):
            return self.get_response(request)
        return redirect("core:mfa_enroll")
