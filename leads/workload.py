"""Synthetic lead volume for the list-timing measurement.

This writes only to the database named in the environment. Callers must refuse
the application database before loading a large volume.
"""

import time
import uuid
from datetime import timedelta

from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from activities.services import attach_freshness
from leads.models import Lead
from leads.services import filter_leads, page_leads

APPLICATION_DATABASE = "glidecrm"
BATCH_SIZE = 2000
PAGE_SIZE = 50


def require_workload_database(name: str) -> None:
    if name == APPLICATION_DATABASE:
        raise CommandError(
            "Refusing to load measurement leads into the application database. "
            "Create glidecrm_perf and set MYSQL_DATABASE=glidecrm_perf."
        )


def load_lead_volume(owner, count: int, progress=None) -> int:
    """Insert leads until ``count`` performance rows exist. Returns new rows."""
    existing = Lead.objects.filter(external_id__startswith="perf-").count()
    if existing >= count:
        return 0
    now = timezone.now()
    inserted = 0
    pending = []
    for number in range(existing, count):
        stage = ("NEW", "CONTACTED", "NURTURING")[number % 3]
        pending.append(
            Lead(
                id=uuid.uuid4(),
                external_id=f"perf-{number:08d}",
                created_at=now - timedelta(seconds=number),
                updated_at=now,
                created_by=owner,
                updated_by=owner,
                version=1,
                first_name="Perf",
                last_name=f"Lead {number}",
                email=f"perf-{number}@example.test",
                company_name=f"Perf Co {number % 1000}",
                source="WEB",
                rating="WARM",
                stage=stage,
                stage_entered_at=now - timedelta(seconds=number),
                owner=owner,
                address={},
            )
        )
        if len(pending) >= BATCH_SIZE:
            Lead.objects.bulk_create(pending, batch_size=BATCH_SIZE)
            inserted += len(pending)
            pending = []
            if progress is not None and inserted % 50_000 == 0:
                progress(inserted)
    if pending:
        Lead.objects.bulk_create(pending, batch_size=BATCH_SIZE)
        inserted += len(pending)
    return inserted


def time_lead_list(user, params):
    """Time the list path the page uses: count, id page, then those rows."""
    queryset = filter_leads(user, params)
    started = time.perf_counter()
    total = queryset.count()
    counted = time.perf_counter()
    page = page_leads(queryset, 1, PAGE_SIZE)
    fetched = time.perf_counter()
    attach_freshness(list(page.object_list), "lead")
    finished = time.perf_counter()
    return {
        "params": dict(params),
        "total": total,
        "page_rows": len(page.object_list),
        "count_seconds": round(counted - started, 3),
        "page_seconds": round(fetched - counted, 3),
        "freshness_seconds": round(finished - fetched, 3),
        "seconds": round(finished - started, 3),
    }


def explain_lead_list(user, params):
    queryset = filter_leads(user, params).values_list("pk", flat=True)[:PAGE_SIZE]
    sql, sql_params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN {sql}", sql_params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
