import logging

from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)


def health(request: HttpRequest) -> JsonResponse:
    """Liveness check; deliberately does not depend on external services."""
    return JsonResponse({"status": "ok", "service": "fluxcrm"})


def readiness(request: HttpRequest) -> JsonResponse:
    """Readiness check that proves the configured database is reachable."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.warning("Database readiness check failed")
        return JsonResponse(
            {"status": "unhealthy", "database": "unavailable"},
            status=503,
        )
    return JsonResponse({"status": "ready", "database": "available"})
