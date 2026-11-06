"""Phase 8 CSV templates, preview, commit, rollback, and export."""

import csv
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Account, Contact
from accounts.services import create_account, create_contact
from audit.models import AuditEvent
from core.models import PicklistValue
from core.taxonomy import ensure_picklists
from imports.columns import template_csv
from imports.services import CHUNK_SIZE, commit_import, export_csv, preview_import
from leads.models import Lead
from leads.services import create_lead, update_lead
from tests.test_access import make_user as make_role_user
from tests.test_pipeline import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def staging(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    ensure_picklists()


def _csv(text):
    return SimpleUploadedFile("leads.csv", text.encode(), content_type="text/csv")


def _lead_csv(*rows, header=None):
    columns = header or "external_id,first_name,last_name,company_name,source,email"
    lines = [columns, *rows]
    return "\n".join(lines) + "\n"


def test_templates_mark_required_optional_and_format(client):
    admin = make_user("jordan", admin=True)
    client.force_login(admin)
    page = client.get(reverse("imports:home"))
    assert page.status_code == 200
    assert b"Required" in page.content
    assert b"Optional" in page.content
    assert b"YYYY-MM-DD" in page.content or b"true or false" in page.content
    downloaded = client.get(reverse("imports:template", args=["lead"]))
    body = downloaded.content.decode()
    assert "first_name: required" in body
    assert "email: required" in body
    assert "title: optional" in body
    assert "email: required" in template_csv("contact")
    assert "WEB" in body
    assert "row_action,external_id,first_name" in body
    assert template_csv("account").splitlines()[0].startswith("# ")
    assert "account_type: required" in template_csv("account")
    assert "account_external_id: required" in template_csv("contact")


def test_preview_does_not_create_records_and_explains_invalid_rows(client):
    admin = make_user("jordan", admin=True)
    before = Lead.objects.count()
    client.force_login(admin)
    response = client.post(
        reverse("imports:preview"),
        {
            "entity": "lead",
            "policy": "skip",
            "file": _csv(
                _lead_csv(
                    "L-1,Ada,Lovelace,Analytical,WEB,ada@example.com",
                    "L-2,Grace,Hopper,Navy,NOT_A_SOURCE,grace@example.com",
                    "L-3,Formula,Cell,Bad,WEB,=SUM(1)",
                )
            ),
        },
    )
    assert response.status_code == 302
    assert Lead.objects.count() == before
    assert not AuditEvent.objects.filter(action="lead.created").exists()
    detail = client.get(response["Location"])
    assert (
        b"NOT_A_SOURCE" in detail.content or b"Select an active value" in detail.content
    )
    assert b"cannot start with" in detail.content
    assert b"Ready to add" in detail.content


def test_duplicate_policies_are_deterministic():
    admin = make_user("jordan", admin=True)
    create_lead(
        actor=admin,
        data={
            "external_id": "L-1",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company_name": "Old Co",
            "source": "WEB",
            "email": "ada@example.com",
            "stage": "NEW",
        },
    )
    skipped = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=_lead_csv("L-9,Ada,Lovelace,New Co,WEB,ada@example.com").encode(),
        policy="skip",
    )
    commit_import(actor=admin, batch_id=skipped.pk)
    assert Lead.objects.count() == 1
    assert Lead.objects.get().company_name == "Old Co"
    updated = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=_lead_csv("L-1,Ada,Lovelace,Updated Co,WEB,ada@example.com").encode(),
        policy="update",
    )
    commit_import(actor=admin, batch_id=updated.pk)
    assert Lead.objects.get().company_name == "Updated Co"
    created = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=_lead_csv("L-2,Ada,Lovelace,Second Co,WEB,ada@example.com").encode(),
        policy="create",
    )
    commit_import(actor=admin, batch_id=created.pk)
    assert Lead.objects.count() == 2
    again = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=_lead_csv("L-2,Ada,Lovelace,Nope,WEB,ada@example.com").encode(),
        policy="create",
        idempotency_key="same-file",
    )
    commit_import(actor=admin, batch_id=again.pk)
    commit_import(actor=admin, batch_id=again.pk)
    assert Lead.objects.filter(external_id="L-2").count() == 1


def test_retry_of_a_failed_chunk_does_not_duplicate_saved_rows(monkeypatch):
    admin = make_user("jordan", admin=True)
    calls = {"n": 0}
    real = create_lead

    def wrapped(**kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("stop the third row")
        return real(**kwargs)

    monkeypatch.setattr("imports.services.create_lead", wrapped)
    monkeypatch.setattr("imports.services.CHUNK_SIZE", 2)
    batch = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=_lead_csv(
            "A-1,One,Person,Co,WEB,one@example.test",
            "A-2,Two,Person,Co,WEB,two@example.test",
            "A-3,Three,Person,Co,WEB,three@example.test",
        ).encode(),
        policy="create",
    )
    first = commit_import(actor=admin, batch_id=batch.pk)
    assert first.status == "incomplete"
    assert Lead.objects.count() == 2
    monkeypatch.setattr("imports.services.create_lead", real)
    second = commit_import(actor=admin, batch_id=batch.pk)
    assert second.status == "committed"
    assert Lead.objects.count() == 3
    assert CHUNK_SIZE == 200


def test_rollback_keeps_audit_and_flags_later_edits():
    admin = make_user("jordan", admin=True)
    batch = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=_lead_csv(
            "R-1,Ada,Lovelace,Analytical,WEB,ada@example.com",
            "R-2,Grace,Hopper,Navy,WEB,grace@example.com",
        ).encode(),
        policy="create",
    )
    commit_import(actor=admin, batch_id=batch.pk)
    created = AuditEvent.objects.filter(action="lead.created").count()
    grace = Lead.objects.get(external_id="R-2")
    update_lead(
        actor=admin,
        lead_id=grace.pk,
        version=grace.version,
        data={"company_name": "Changed after import"},
    )
    from imports.services import rollback_import

    rollback_import(actor=admin, batch_id=batch.pk)
    assert AuditEvent.objects.filter(action="lead.created").count() == created
    assert AuditEvent.objects.filter(action="import.rolled_back").exists()
    assert not Lead.objects.filter(external_id="R-1").exists()
    grace.refresh_from_db()
    assert grace.company_name == "Changed after import"
    assert grace.deleted_at is None


def test_limits_permissions_and_formula_export(client):
    reader = make_role_user("executive", "READ_ONLY")
    owner = make_user("owner")
    client.force_login(reader)
    refused = client.post(
        reverse("imports:preview"),
        {
            "entity": "lead",
            "policy": "skip",
            "file": _csv(_lead_csv("Z-1,A,B,Co,WEB,")),
        },
    )
    assert refused.status_code == 403
    client.force_login(owner)
    huge = "external_id,first_name,last_name,company_name,source\n" + (
        "\n".join(f"H-{i},A,B,Co,WEB" for i in range(50_001))
    )
    too_many = client.post(
        reverse("imports:preview"),
        {"entity": "lead", "policy": "skip", "file": _csv(huge)},
    )
    assert too_many.status_code == 422
    assert Lead.objects.count() == 0
    workbook = SimpleUploadedFile(
        "leads.xlsx", b"not a csv", content_type="application/vnd.ms-excel"
    )
    rejected = client.post(
        reverse("imports:preview"),
        {"entity": "lead", "policy": "skip", "file": workbook},
    )
    assert rejected.status_code == 422
    create_lead(
        actor=owner,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company_name": "=Analytical",
            "email": "ada.export@example.test",
            "source": "WEB",
            "stage": "NEW",
        },
    )
    denied = client.get(reverse("imports:export", args=["lead"]))
    assert denied.status_code == 403
    admin = make_user("jordan", admin=True)
    client.force_login(admin)
    exported = client.get(reverse("imports:export", args=["lead"]))
    assert exported.status_code == 200
    assert b"'=Analytical" in exported.content
    assert AuditEvent.objects.filter(action="export.completed").exists()


def test_account_and_contact_templates_import_in_order():
    admin = make_user("jordan", admin=True)
    accounts = preview_import(
        actor=admin,
        entity="account",
        upload_name="accounts.csv",
        content_type="text/csv",
        content=(
            b"external_id,name,account_type,parent_external_id\n"
            b"parent-1,Parent Co,CUSTOMER,\n"
            b"child-1,Child Co,PROSPECT,parent-1\n"
        ),
        policy="create",
    )
    commit_import(actor=admin, batch_id=accounts.pk)
    child = Account.objects.get(external_id="child-1")
    assert child.parent.external_id == "parent-1"
    contacts = preview_import(
        actor=admin,
        entity="contact",
        upload_name="contacts.csv",
        content_type="text/csv",
        content=(
            b"external_id,account_external_id,first_name,last_name,email,is_primary\n"
            b"person-1,parent-1,Ada,Lovelace,ada@example.com,true\n"
        ),
        policy="create",
    )
    commit_import(actor=admin, batch_id=contacts.pk)
    contact = Contact.objects.get(external_id="person-1")
    assert contact.account_id == Account.objects.get(external_id="parent-1").pk
    assert contact.is_primary is True


def test_fifty_thousand_row_preview_stays_inside_a_short_budget():
    admin = make_user("jordan", admin=True)
    started = time.perf_counter()
    body = "first_name,last_name,company_name,source,email\n" + "".join(
        f"Ada,Lovelace,Company {index},WEB,ada{index}@example.test\n"
        for index in range(50_000)
    )
    batch = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=body.encode(),
        policy="skip",
    )
    elapsed = time.perf_counter() - started
    assert batch.summary["row_count"] == 50_000
    assert batch.summary["error_count"] == 0
    assert Lead.objects.count() == 0
    assert elapsed < 30


def test_account_and_contact_edit_keeps_ids_off_the_form_and_in_the_export(client):
    admin = make_user("jordan", admin=True)
    client.force_login(admin)
    created = client.post(
        reverse("accounts:create"),
        {"name": "Acme", "account_type": "CUSTOMER", "phone": "9495550111"},
    )
    assert created.status_code == 302
    account = Account.objects.get(name="Acme")
    original_id = account.external_id
    form = client.get(reverse("accounts:edit", args=[account.pk]))
    body = form.content.decode()
    assert 'name="name"' in body
    assert "Required" in body
    assert 'name="id"' not in body
    assert "external_id" not in body
    assert ">Account id<" not in body
    saved = client.post(
        reverse("accounts:edit", args=[account.pk]),
        {
            "name": "Acme Updated",
            "account_type": "PROSPECT",
            "phone": "9495550222",
            "version": account.version,
            "id": "ignore-me",
            "external_id": "ignore-me",
        },
    )
    assert saved.status_code == 302
    account.refresh_from_db()
    assert account.name == "Acme Updated"
    assert account.account_type == "PROSPECT"
    assert account.external_id == original_id
    person = create_contact(
        actor=admin,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "account": account.pk,
            "email": "ada@example.test",
        },
    )
    contact_form = client.get(reverse("accounts:contact_edit", args=[person.pk]))
    contact_body = contact_form.content.decode()
    assert "First name" in contact_body
    assert "Required" in contact_body
    assert 'class="choice-line"' in contact_body
    assert 'id="contact-primary"' in contact_body
    assert "form-check-input" not in contact_body
    assert 'name="id"' not in contact_body
    assert "external_id" not in contact_body
    edited = client.post(
        reverse("accounts:contact_edit", args=[person.pk]),
        {
            "account": str(account.pk),
            "first_name": "Ada",
            "last_name": "Byron",
            "email": "ada@example.test",
            "version": person.version,
        },
    )
    assert edited.status_code == 302
    person.refresh_from_db()
    assert person.last_name == "Byron"
    accounts = export_csv(actor=admin, entity="account")
    contacts = export_csv(actor=admin, entity="contact")
    leads = export_csv(actor=admin, entity="lead")
    assert accounts.splitlines()[0].startswith("id,external_id,")
    assert str(account.pk) in accounts
    assert contacts.splitlines()[0].startswith("id,account_id,")
    assert str(person.pk) in contacts
    assert str(account.pk) in contacts
    assert leads.splitlines()[0].startswith("id,external_id,")


def test_client_accounts_are_rewritten_to_customer():
    import importlib

    from imports.models import ImportRow

    merge_client_into_customer = importlib.import_module(
        "accounts.migrations.0003_merge_client_into_customer"
    ).merge_client_into_customer
    admin = make_user("jordan", admin=True)
    account = create_account(
        actor=admin, data={"name": "Former Client", "account_type": "CUSTOMER"}
    )
    Account.objects.filter(pk=account.pk).update(account_type="CLIENT")

    class Apps:
        def get_model(self, app_label, model_name):
            if model_name == "Account":
                return Account
            return ImportRow

    merge_client_into_customer(Apps(), None)
    account.refresh_from_db()
    assert account.account_type == "CUSTOMER"


def test_client_type_and_industry_labels_are_available():
    assert "CLIENT" not in Account.Type.values
    accounts = template_csv("account")
    assert "CLIENT" not in accounts
    assert "CUSTOMER (Customer)" in accounts
    assert "RETAIL (Retail & E-Commerce)" in accounts
    labels = {
        row.key: row.label
        for row in PicklistValue.objects.filter(list_key="INDUSTRY", active=True)
    }
    assert labels["RETAIL"] == "Retail & E-Commerce"
    assert labels["INSURANCE"] == "Insurance"
    assert labels["AUTOMOTIVE"] == "Automotive"
    assert labels["HOSPITALITY_TRAVEL"] == "Hospitality & Travel"
    assert labels["TECHNOLOGY_SAAS"] == "Technology & SaaS"
    guide = template_csv("lead")
    assert "TECHNOLOGY_SAAS (Technology & SaaS)" in guide
    assert "HOSPITALITY_TRAVEL (Hospitality & Travel)" in guide
    assert "RETAIL (Retail & E-Commerce)" in guide


def test_import_and_export_owner_use_the_display_name():
    admin = make_user("jordan", admin=True)
    person = make_user("satish")
    person.display_name = "Satish Varma"
    person.save(update_fields=["display_name"])
    account_batch = preview_import(
        actor=admin,
        entity="account",
        upload_name="accounts.csv",
        content_type="text/csv",
        content=(
            b"external_id,name,account_type,owner\nacme,Acme,CUSTOMER,Satish Varma\n"
        ),
        policy="create",
    )
    assert account_batch.summary["error_count"] == 0
    commit_import(actor=admin, batch_id=account_batch.pk)
    assert Account.objects.get(external_id="acme").owner_id == person.pk
    lead_batch = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=(
            b"external_id,first_name,last_name,company_name,source,email,owner\n"
            b"L-1,Ada,Lovelace,Acme,WEB,ada@example.test,Satish Varma\n"
        ),
        policy="create",
    )
    assert lead_batch.summary["error_count"] == 0
    commit_import(actor=admin, batch_id=lead_batch.pk)
    assert Lead.objects.get(external_id="L-1").owner_id == person.pk
    contact_batch = preview_import(
        actor=admin,
        entity="contact",
        upload_name="contacts.csv",
        content_type="text/csv",
        content=(
            b"external_id,account_external_id,first_name,last_name,email,owner\n"
            b"c1,acme,Ada,Lovelace,ada@example.test,Satish Varma\n"
        ),
        policy="create",
    )
    assert contact_batch.summary["error_count"] == 0
    commit_import(actor=admin, batch_id=contact_batch.pk)
    assert Contact.objects.get(external_id="c1").owner_id == person.pk
    for entity in ("lead", "account", "contact"):
        table = list(csv.reader(export_csv(actor=admin, entity=entity).splitlines()))
        owner_index = table[0].index("owner")
        assert table[1][owner_index] == "Satish Varma"
    rejected = preview_import(
        actor=admin,
        entity="account",
        upload_name="accounts.csv",
        content_type="text/csv",
        content=(b"external_id,name,account_type,owner\nother,Other,CUSTOMER,satish\n"),
        policy="create",
    )
    assert "No active user has that name." in rejected.summary["errors"][0]["message"]
    twin = make_user("lee")
    twin.display_name = "Satish Varma"
    twin.save(update_fields=["display_name"])
    duplicate = preview_import(
        actor=admin,
        entity="account",
        upload_name="accounts.csv",
        content_type="text/csv",
        content=(
            b"external_id,name,account_type,owner\n"
            b"dup,Duplicate,CUSTOMER,Satish Varma\n"
        ),
        policy="create",
    )
    assert (
        "More than one active user has that name."
        in duplicate.summary["errors"][0]["message"]
    )


def test_address_columns_are_optional_and_round_trip():
    for entity in ("lead", "account", "contact"):
        guide = template_csv(entity)
        assert "street: optional" in guide
        assert "region: optional" in guide
        assert "postal_code: optional" in guide
    assert "employee_count" not in template_csv("lead")
    admin = make_user("jordan", admin=True)
    batch = preview_import(
        actor=admin,
        entity="lead",
        upload_name="leads.csv",
        content_type="text/csv",
        content=(
            b"external_id,first_name,last_name,company_name,source,email,street,city,"
            b"region,postal_code,country\n"
            b"L-addr,Ada,Lovelace,Analytical Engines,WEB,ada@example.test,26040 Acero,"
            b"Mission Viejo,CA,92691,US\n"
        ),
        policy="create",
    )
    assert batch.summary["error_count"] == 0
    commit_import(actor=admin, batch_id=batch.pk)
    lead = Lead.objects.get(external_id="L-addr")
    assert lead.address["street"] == "26040 Acero"
    assert lead.address["region"] == "CA"
    table = list(csv.reader(export_csv(actor=admin, entity="lead").splitlines()))
    row = table[1]
    assert row[table[0].index("street")] == "26040 Acero"
    assert row[table[0].index("city")] == "Mission Viejo"
    assert row[table[0].index("postal_code")] == "92691"
    assert row[table[0].index("country")] == "US"
