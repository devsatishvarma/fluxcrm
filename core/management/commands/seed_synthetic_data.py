"""Create idempotent synthetic data for walkthroughs. Never loads production data."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import JobRun
from identity.models import User
from leads.seed import seed_phase2


class Command(BaseCommand):
    help = "Load idempotent synthetic data. Never loads production data."

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
        admin = (
            User.objects.filter(role__key="ADMIN", is_active=True)
            .order_by("pk")
            .first()
        )
        if admin is None:
            self.stdout.write("Skipped leads and deals: no active administrator.")
            return
        sdr = (
            User.objects.filter(is_active=True)
            .exclude(pk=admin.pk)
            .order_by("pk")
            .first()
        ) or admin
        created_ids = seed_phase2(actor=admin, sdr=sdr, executive=admin)
        if created_ids:
            self.stdout.write(self.style.SUCCESS("Created: " + ", ".join(created_ids)))
        else:
            self.stdout.write("Leads and deals were already present.")
