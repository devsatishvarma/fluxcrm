"""Idempotent activity and task fixtures. Account-only sample deals are omitted."""

from datetime import UTC, datetime

from activities.services import create_activity, create_task
from leads.models import Lead

ACTIVITIES = (
    {
        "external_id": "act-3001",
        "activity_type": "CALL",
        "subject": "Intro call with Jamie Ng",
        "occurred_at": datetime(2026, 10, 8, 16, 30, tzinfo=UTC),
        "lead_external_id": "lead-1001",
    },
    {
        "external_id": "act-3003",
        "activity_type": "NOTE",
        "subject": "Northstar note",
        "occurred_at": datetime(2026, 10, 9, 18, 0, tzinfo=UTC),
        "lead_external_id": "lead-1002",
    },
)

TASKS = (
    {
        "external_id": "task-4001",
        "title": "Reconnect with Drew Singh",
        "due_at": datetime(2026, 11, 15, 18, 0, tzinfo=UTC),
        "lead_external_id": "lead-1003",
    },
)


def seed_phase4(*, actor):
    """Create the synthetic follow-ups that do not depend on an account deal."""
    created = []
    from activities.models import Activity, Task

    for spec in ACTIVITIES:
        if Activity.all_objects.filter(external_id=spec["external_id"]).exists():
            continue
        lead = Lead.objects.get(external_id=spec["lead_external_id"])
        create_activity(
            actor=actor,
            data=spec,
            links=[{"kind": "lead", "id": lead.pk}],
            request_id="seed",
        )
        created.append(spec["external_id"])
    for spec in TASKS:
        if Task.all_objects.filter(external_id=spec["external_id"]).exists():
            continue
        lead = Lead.objects.get(external_id=spec["lead_external_id"])
        create_task(
            actor=actor,
            data=spec,
            links=[{"kind": "lead", "id": lead.pk}],
            request_id="seed",
        )
        created.append(spec["external_id"])
    return created
