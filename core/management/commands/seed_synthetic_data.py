"""Create the minimal synthetic marker used by the Phase 0 walkthrough."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import JobRun


class Command(BaseCommand):
    help = "Load idempotent synthetic Phase 0 data. Never loads production data."

    def handle(self, *args, **options):
        marker, created = JobRun.objects.get_or_create(
            name="synthetic_fixture",
            run_key="phase-0-v1",
            defaults={
                "status": JobRun.Status.SUCCEEDED,
                "finished_at": timezone.now(),
                "detail": {"synthetic": True, "fixture_version": 1},
            },
        )
        action = "Created" if created else "Already present"
        self.stdout.write(
            self.style.SUCCESS(f"{action}: synthetic fixture marker {marker.run_key}")
        )
