"""Run the current minute's scheduled work exactly once."""

import logging

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import JobRun

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run due FluxCRM jobs once using a database-backed idempotency key."

    def handle(self, *args, **options):
        minute = timezone.now().replace(second=0, microsecond=0)
        run_key = minute.isoformat()
        try:
            with transaction.atomic():
                job_run, created = JobRun.objects.get_or_create(
                    name="due_jobs",
                    run_key=run_key,
                )
        except IntegrityError:
            created = False
            job_run = JobRun.objects.get(name="due_jobs", run_key=run_key)

        if not created:
            self.stdout.write(f"Skipped duplicate due_jobs run {run_key}")
            return

        try:
            # Phase 4 registers reminder and stale-record handlers here.
            job_run.status = JobRun.Status.SUCCEEDED
            job_run.finished_at = timezone.now()
            job_run.detail = {"handlers_run": 0}
            job_run.save(update_fields=("status", "finished_at", "detail"))
        except Exception:
            job_run.status = JobRun.Status.FAILED
            job_run.finished_at = timezone.now()
            job_run.save(update_fields=("status", "finished_at"))
            logger.exception(
                "Scheduled job run failed", extra={"job_run_id": job_run.pk}
            )
            raise

        self.stdout.write(self.style.SUCCESS(f"Completed due_jobs run {run_key}"))
