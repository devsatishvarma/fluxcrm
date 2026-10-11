import json
import logging
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError
from django.urls import reverse

from core.logging import JsonFormatter
from core.models import JobRun


def test_health_does_not_require_database(client):
    response = client.get(reverse("core:health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fluxcrm"}
    assert response.headers["X-Request-ID"]


def test_safe_request_id_is_preserved(client):
    response = client.get(
        reverse("core:health"),
        headers={"X-Request-ID": "test-request-123"},
    )

    assert response.headers["X-Request-ID"] == "test-request-123"


def test_readiness_reports_database_failure_without_details(client):
    with patch(
        "core.views.connection.cursor",
        side_effect=DatabaseError("secret connection detail"),
    ):
        response = client.get(reverse("core:readiness"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "unhealthy",
        "database": "unavailable",
    }
    assert b"secret connection detail" not in response.content


@pytest.mark.django_db
def test_readiness_checks_database(client):
    response = client.get(reverse("core:readiness"))

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}


@pytest.mark.django_db
def test_due_job_command_is_idempotent():
    call_command("run_due_jobs")
    call_command("run_due_jobs")

    assert JobRun.objects.filter(name="due_jobs").count() == 1
    assert JobRun.objects.get(name="due_jobs").status == JobRun.Status.SUCCEEDED


def test_json_logging_redacts_sensitive_extra_fields():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="safe message",
        args=(),
        exc_info=None,
    )
    record.api_token = "must-not-appear"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["api_token"] == "[REDACTED]"
    assert "must-not-appear" not in json.dumps(payload)
