import pytest
from django.core.management.base import CommandError

from core.services import ensure_roles
from identity.models import User
from leads.workload import load_lead_volume, require_workload_database, time_lead_list

pytestmark = pytest.mark.django_db


def test_workload_refuses_the_application_database():
    with pytest.raises(CommandError):
        require_workload_database("glidecrm")


def test_lead_volume_loads_and_the_list_path_returns_a_page():
    admin_role, _standard = ensure_roles()
    owner = User.objects.create_user(
        username="perf-admin",
        email="perf-admin@example.test",
        password="another-strong-pass",
        display_name="Perf Admin",
        role=admin_role,
    )
    assert load_lead_volume(owner, 30) == 30
    assert load_lead_volume(owner, 30) == 0
    result = time_lead_list(owner, {"stage": "NEW"})
    assert result["page_rows"] == result["total"]
    assert result["total"] == 10
    assert result["seconds"] >= 0
