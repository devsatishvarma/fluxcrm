"""Load synthetic leads and time the filtered list. Never touches glidecrm."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.services import ensure_roles
from identity.models import User
from leads.workload import (
    explain_lead_list,
    load_lead_volume,
    require_workload_database,
    time_lead_list,
)


class Command(BaseCommand):
    help = "Time the lead list against synthetic rows in a measurement database."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=500_000)

    def handle(self, *args, **options):
        name = connection.settings_dict["NAME"]
        require_workload_database(name)
        count = options["count"]
        if count < 1:
            raise CommandError("--count must be at least 1.")
        admin_role, _standard = ensure_roles()
        owner, _created = User.objects.get_or_create(
            username="perf-admin",
            defaults={
                "email": "perf-admin@example.test",
                "display_name": "Perf Admin",
                "role": admin_role,
                "is_active": True,
            },
        )
        inserted = load_lead_volume(
            owner,
            count,
            progress=lambda done: self.stdout.write(f"inserted={done}"),
        )
        self.stdout.write(f"database={name} inserted={inserted} target={count}")
        for params in ({}, {"stage": "NEW"}):
            result = time_lead_list(owner, params)
            self.stdout.write(
                "list "
                f"stage={params.get('stage', 'any')} "
                f"total={result['total']} "
                f"page_rows={result['page_rows']} "
                f"count_seconds={result['count_seconds']} "
                f"page_seconds={result['page_seconds']} "
                f"freshness_seconds={result['freshness_seconds']} "
                f"seconds={result['seconds']}"
            )
        for row in explain_lead_list(owner, {}):
            self.stdout.write(
                "explain "
                f"type={row.get('type')} "
                f"key={row.get('key')} "
                f"rows={row.get('rows')} "
                f"extra={row.get('Extra')}"
            )
