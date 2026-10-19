"""Phase 6 role, scope, export, and audit gates."""

from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from audit.models import AuditEvent
from core.policy import ACTIONS, OBJECTS, ROLE_SPECS, allows
from core.services import ensure_roles, set_user_manager
from core.taxonomy import ensure_picklists
from identity.models import Role, Team, User
from leads.models import Lead
from leads.services import create_lead
from sales.services import create_deal

pytestmark = pytest.mark.django_db


def make_user(username, role_key, *, manager=None):
    ensure_roles()
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="another-strong-pass",
        display_name=username.title(),
        role=Role.objects.get(key=role_key),
        manager=manager,
    )


def make_lead(actor, **overrides):
    ensure_picklists()
    payload = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "company_name": "Analytical Engines",
        "email": f"{actor.username}@lead.example",
        "source": "WEB",
        "stage": "NEW",
        "notes": "private notebook",
    }
    payload.update(overrides)
    return create_lead(actor=actor, data=payload)


def test_every_matrix_cell_is_positive_or_negative():
    for key, spec in ROLE_SPECS.items():
        user = make_user(key.lower(), key)
        objects = spec["permissions"]["objects"]
        for object_key in OBJECTS:
            granted = set(objects[object_key]["actions"])
            for action in ACTIONS:
                assert allows(user, object_key, action) is (action in granted)
    sdr = User.objects.get(username="sdr")
    assert allows(sdr, "deal", "C", lead=SimpleNamespace(stage="NEW")) is False
    assert allows(sdr, "deal", "C", lead=SimpleNamespace(stage="SQL")) is True


def test_managers_see_descendants_and_not_the_other_branch(client):
    director = make_user("jordan", "SALES_DIRECTOR")
    child = make_user("riley", "ACCOUNT_EXECUTIVE", manager=director)
    grandchild = make_user("morgan", "SDR", manager=child)
    other = make_user("alex", "ACCOUNT_EXECUTIVE")
    child_lead = make_lead(child, company_name="Child Co", email="child@example.test")
    grand_lead = make_lead(
        grandchild, company_name="Grand Co", email="grand@example.test"
    )
    other_lead = make_lead(other, company_name="Other Co", email="other@example.test")

    client.force_login(director)
    page = client.get(reverse("leads:list"))
    assert b"Child Co" in page.content
    assert b"Grand Co" in page.content
    assert b"Other Co" not in page.content
    assert client.get(reverse("leads:detail", args=[child_lead.pk])).status_code == 200
    assert client.get(reverse("leads:detail", args=[grand_lead.pk])).status_code == 200
    assert client.get(reverse("leads:detail", args=[other_lead.pk])).status_code == 403

    api = APIClient()
    api.force_authenticate(user=director)
    assert api.get("/api/v1/leads/?q=Other").json()["count"] == 0
    assert api.get("/api/v1/leads/?q=Grand").json()["count"] == 1


def test_team_scope_includes_teammates_only(client):
    west_a = make_user("west-a", "ACCOUNT_EXECUTIVE")
    west_b = make_user("west-b", "ACCOUNT_EXECUTIVE")
    east = make_user("east-a", "ACCOUNT_EXECUTIVE")
    team = Team.objects.create(name="West", manager=west_a, active=True)
    team.members.add(west_a, west_b)
    Team.objects.create(name="East", manager=east, active=True).members.add(east)
    from accounts.services import create_account

    create_account(actor=west_b, data={"name": "West Co", "account_type": "CUSTOMER"})
    create_account(actor=east, data={"name": "East Co", "account_type": "CUSTOMER"})
    client.force_login(west_a)
    page = client.get(reverse("accounts:list"))
    assert b"West Co" in page.content
    assert b"East Co" not in page.content


def test_read_only_cannot_mutate_by_form_htmx_or_api(client):
    owner = make_user("owner", "STANDARD_USER")
    reader = make_user("executive", "READ_ONLY")
    lead = make_lead(owner)
    client.force_login(reader)
    assert client.get(reverse("leads:detail", args=[lead.pk])).status_code == 200
    assert (
        client.post(
            reverse("leads:create"),
            {
                "first_name": "New",
                "last_name": "Person",
                "company_name": "Nope",
                "source": "WEB",
                "stage": "NEW",
            },
        ).status_code
        == 403
    )
    edited = client.post(
        reverse("leads:edit", args=[lead.pk]),
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company_name": "Stolen",
            "source": "WEB",
            "version": lead.version,
        },
    )
    assert edited.status_code == 403
    moved = client.post(
        reverse("leads:transition", args=[lead.pk]),
        {"version": lead.version, "to_stage": "CONTACTED", "reason": "Called"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert moved.status_code == 403
    removed = client.post(
        reverse("leads:delete", args=[lead.pk]),
        {"version": lead.version, "delete_reason": "nope"},
    )
    assert removed.status_code == 403
    api = APIClient()
    api.force_authenticate(user=reader)
    assert (
        api.patch(
            f"/api/v1/leads/{lead.pk}/",
            {"version": lead.version, "company_name": "Stolen"},
            format="json",
        ).status_code
        == 403
    )
    assert api.post("/api/v1/activities/", {}, format="json").status_code == 403
    lead.refresh_from_db()
    assert lead.company_name == "Analytical Engines"
    assert lead.stage == "NEW"
    denial = AuditEvent.objects.filter(action="access.denied").first()
    assert denial is not None
    assert "private notebook" not in str(denial.after_json)
    assert "Analytical" not in str(denial.after_json)


def test_export_is_separately_permissioned(client):
    director = make_user("jordan", "SALES_DIRECTOR")
    child = make_user("riley", "ACCOUNT_EXECUTIVE", manager=director)
    outsider = make_user("alex", "ACCOUNT_EXECUTIVE")
    make_lead(child, company_name="Visible Co", email="visible@example.test")
    make_lead(outsider, company_name="Hidden Co", email="hidden@example.test")
    api = APIClient()
    api.force_authenticate(user=child)
    denied = api.post("/api/v1/exports/", {"object": "lead"}, format="json")
    assert denied.status_code == 403
    assert not AuditEvent.objects.filter(action="export.requested").exists()
    api.force_authenticate(user=director)
    exported = api.post(
        "/api/v1/exports/",
        {"object": "lead", "q": "Visible"},
        format="json",
    )
    assert exported.status_code == 200
    assert exported.json()["row_count"] == 1
    event = AuditEvent.objects.get(action="export.requested")
    assert event.after_json["row_count"] == 1
    assert event.after_json["q"] == "Visible"
    assert "private notebook" not in str(event.after_json)
    form = client
    form.force_login(child)
    assert client.post(reverse("core:export"), {"object": "lead"}).status_code == 403


def test_privilege_changes_are_logged_without_crm_content():
    admin = make_user("ada", "ADMIN")
    make_lead(admin)
    role = Role.objects.get(key="STANDARD_USER")
    from core.services import update_role_grants

    update_role_grants(
        actor=admin,
        role=role,
        permissions=role.permissions,
    )
    event = AuditEvent.objects.get(action="role.grants_updated")
    assert event.after_json["grants_version"] == 2
    assert "private notebook" not in str(event.after_json)
    assert "private notebook" not in str(event.before_json)


def test_audit_page_shows_only_changed_fields(client):
    admin = make_user("ada", "ADMIN")
    AuditEvent.objects.create(
        actor=admin,
        action="leads.lead.updated",
        object_type="leads.lead",
        object_id="1",
        before_json={"stage": "NEW", "company_name": "Acme", "version": 1},
        after_json={"stage": "CONTACTED", "company_name": "Acme", "version": 2},
    )
    client.force_login(admin)
    page = client.get(reverse("core:audit"))
    assert b"Stage" in page.content
    assert b"NEW" in page.content
    assert b"CONTACTED" in page.content
    assert b"Acme" not in page.content


def test_audit_rows_cannot_be_changed_through_user_paths(client):
    admin = make_user("ada", "ADMIN")
    event = AuditEvent.objects.create(
        actor=admin,
        action="probe.created",
        object_type="identity.user",
        object_id=str(admin.pk),
        after_json={"role": "ADMIN"},
    )
    with pytest.raises(PermissionDenied):
        event.save()
    with pytest.raises(PermissionDenied):
        event.delete()
    with pytest.raises(PermissionDenied):
        AuditEvent.objects.update(action="changed")
    with pytest.raises(PermissionDenied):
        AuditEvent.objects.all().delete()
    api = APIClient()
    api.force_authenticate(user=admin)
    assert api.post("/api/v1/audit-events/", {}, format="json").status_code == 405
    assert api.patch("/api/v1/audit-events/", {}, format="json").status_code == 405
    assert api.delete("/api/v1/audit-events/").status_code == 405
    client.force_login(admin)
    assert client.post(reverse("core:audit")).status_code == 405
    listed = api.get("/api/v1/audit-events/")
    assert listed.status_code == 200
    assert "before" in listed.json()["results"][0]
    reader = make_user("executive", "READ_ONLY")
    api.force_authenticate(user=reader)
    summary = api.get("/api/v1/audit-events/").json()["results"][0]
    assert "before" not in summary
    assert "after" not in summary


def test_administrator_review_lists_active_admins(client):
    admin = make_user("ada", "ADMIN")
    disabled = make_user("old-admin", "ADMIN")
    disabled.is_active = False
    disabled.save(update_fields=("is_active",))
    make_user("riley", "STANDARD_USER")
    client.force_login(admin)
    page = client.get(reverse("core:administrator_review"))
    assert page.status_code == 200
    assert b"ada" in page.content
    assert b"old-admin" in page.content
    recorded = client.post(reverse("core:administrator_review"))
    assert recorded.status_code == 200
    event = AuditEvent.objects.get(action="administrators.reviewed")
    assert event.after_json["active_admin_ids"] == [admin.pk]
    assert "private" not in str(event.after_json)
    client.force_login(User.objects.get(username="riley"))
    assert client.get(reverse("core:administrator_review")).status_code == 403


def test_manager_cycles_are_rejected_and_bulk_assign_stays_in_scope():
    director = make_user("jordan", "SALES_DIRECTOR")
    child = make_user("riley", "ACCOUNT_EXECUTIVE", manager=director)
    grandchild = make_user("morgan", "SDR", manager=child)
    outsider = make_user("alex", "ACCOUNT_EXECUTIVE")
    admin = make_user("ada", "ADMIN")
    with pytest.raises(ValidationError):
        set_user_manager(actor=admin, user=director, manager=grandchild)
    lead = make_lead(child, company_name="Assignable", email="assign@example.test")
    api = APIClient()
    api.force_authenticate(user=director)
    moved = api.post(
        "/api/v1/leads/bulk-assign/",
        {"leads": [str(lead.pk)], "owner": grandchild.pk},
        format="json",
    )
    assert moved.status_code == 200
    lead.refresh_from_db()
    assert lead.owner_id == grandchild.pk
    refused = api.post(
        "/api/v1/leads/bulk-assign/",
        {"leads": [str(lead.pk)], "owner": outsider.pk},
        format="json",
    )
    assert refused.status_code == 422
    reader = make_user("executive", "READ_ONLY")
    api.force_authenticate(user=reader)
    assert (
        api.post(
            "/api/v1/leads/bulk-assign/",
            {"leads": [str(lead.pk)], "owner": reader.pk},
            format="json",
        ).status_code
        == 403
    )
    lead.refresh_from_db()
    assert lead.owner_id == grandchild.pk


def test_import_authorization_does_not_create_records():
    before = Lead.objects.count()
    executive = make_user("executive", "READ_ONLY")
    seller = make_user("seller", "ACCOUNT_EXECUTIVE")
    api = APIClient()
    api.force_authenticate(user=executive)
    assert (
        api.post(
            "/api/v1/imports/authorize/", {"object": "lead"}, format="json"
        ).status_code
        == 403
    )
    api.force_authenticate(user=seller)
    assert (
        api.post(
            "/api/v1/imports/authorize/", {"object": "lead"}, format="json"
        ).status_code
        == 204
    )
    assert Lead.objects.count() == before
    assert AuditEvent.objects.filter(action="import.authorized").exists()


def test_sdr_can_create_a_deal_only_for_sql_ready():
    sdr = make_user("sdr-deal", "SDR")
    lead = make_lead(sdr, company_name="SQL Co", email="sql@example.test")
    payload = {
        "title": "SQL deal",
        "lead": str(lead.pk),
        "deal_type": "CONSULTING_SERVICES",
        "currency": "USD",
        "confidence": "MEDIUM",
        "stage": "NEW",
    }
    with pytest.raises(PermissionDenied):
        create_deal(actor=sdr, data=payload)
    lead.stage = "SQL"
    lead.save(update_fields=("stage",))
    deal = create_deal(actor=sdr, data=payload)
    assert deal.lead_id == lead.pk


def test_settings_menu_and_help(client):
    admin = make_user("jordan", "ADMIN")
    client.force_login(admin)
    home = client.get(reverse("core:home"))
    assert reverse("core:settings") in home.content.decode()
    assert reverse("core:help") in home.content.decode()
    assert home.content.decode().index("Help") < home.content.decode().index("Log out")
    assert reverse("core:audit") not in home.content.decode()
    assert b"Log out" in home.content
    settings_page = client.get(reverse("core:settings"))
    body = settings_page.content.decode()
    for path in (
        reverse("core:company_settings"),
        reverse("core:teams"),
        reverse("core:user_list"),
        reverse("core:roles"),
        reverse("core:audit"),
    ):
        assert path in body
    help_page = client.get(reverse("core:help"))
    assert help_page.status_code == 200
    assert b"Overdue" in help_page.content

    director = make_user("casey", "SALES_DIRECTOR")
    client.force_login(director)
    director_settings = client.get(reverse("core:settings")).content.decode()
    assert reverse("core:teams") in director_settings
    assert reverse("core:user_list") in director_settings
    assert reverse("core:audit") in director_settings
    assert reverse("core:company_settings") not in director_settings
    assert reverse("core:roles") not in director_settings

    reader = make_user("executive", "READ_ONLY")
    client.force_login(reader)
    reader_settings = client.get(reverse("core:settings")).content.decode()
    assert reverse("core:audit") in reader_settings
    assert reverse("core:teams") not in reader_settings
    assert reverse("core:company_settings") not in reader_settings
    assert client.get(reverse("core:help")).status_code == 200
    assert client.get(reverse("core:settings")).status_code == 200
    anonymous = client.__class__()
    assert anonymous.get(reverse("core:help")).status_code == 302
