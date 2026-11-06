"""Success and failure notices after button actions."""

import pytest
from django.urls import reverse

from accounts.models import Account, Contact
from accounts.services import create_account, create_contact
from activities.models import Task
from leads.services import create_lead
from tests.test_pipeline import make_user

pytestmark = pytest.mark.django_db


def test_account_and_task_actions_show_success_and_failure(client):
    admin = make_user("jordan", admin=True)
    client.force_login(admin)
    saved = client.post(
        reverse("accounts:create"),
        {"name": "Acme", "account_type": "CUSTOMER"},
        follow=True,
    )
    assert b"Account Acme added." in saved.content
    account = Account.objects.get(name="Acme")
    edited = client.post(
        reverse("accounts:edit", args=[account.pk]),
        {
            "name": "Acme Co",
            "account_type": "CUSTOMER",
            "version": account.version,
        },
        follow=True,
    )
    assert b"Account Acme Co saved." in edited.content
    refused = client.post(reverse("accounts:create"), {"name": "", "account_type": ""})
    assert refused.status_code == 422
    assert b"Could not add the account." in refused.content
    lead = create_lead(
        actor=admin,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company_name": "Analytical Engines",
            "email": "ada.notice@example.test",
            "source": "WEB",
            "stage": "NEW",
        },
    )
    added = client.post(
        reverse("activities:task_create"),
        {
            "title": "Call back",
            "due_at": "2026-10-20 15:00:00",
            "priority": "NORMAL",
            "lead_id": lead.pk,
        },
        follow=True,
    )
    assert b"Task Call back added." in added.content
    task = Task.objects.get(title="Call back")
    cancelled = client.post(
        reverse("activities:cancel", args=[task.pk]),
        {"version": task.version},
        follow=True,
    )
    assert b"Task Call back cancelled." in cancelled.content


def test_delete_requires_a_reason_and_clears_dependents_first(client):
    admin = make_user("morgan", admin=True)
    client.force_login(admin)
    account = create_account(
        actor=admin,
        data={"name": "Northwind", "account_type": "CUSTOMER"},
    )
    contact = create_contact(
        actor=admin,
        data={
            "first_name": "Drew",
            "last_name": "Singh",
            "email": "drew.singh@example.test",
            "account": account.pk,
        },
    )
    page = client.get(reverse("accounts:detail", args=[account.pk]))
    assert page.content.index(b"Delete account") > page.content.index(b"Contacts")
    assert b'<details class="fold">' in page.content
    assert b"<summary>Contacts</summary>" in page.content
    assert b'class="fold" open' not in page.content
    assert page.content.index(b"Drew Singh") > page.content.index(b"<summary>Contacts</summary>")
    assert b"Confirmed to delete" in page.content
    assert b"confirm_delete_again" not in page.content
    blocked = client.post(
        reverse("accounts:delete", args=[account.pk]),
        {
            "version": account.version,
            "delete_reason": "No longer a customer",
            "confirm_delete": "yes",
        },
    )
    assert blocked.status_code == 422
    assert b"Could not delete the account." in blocked.content
    assert b"contacts before deleting the account." in blocked.content
    assert Account.objects.filter(pk=account.pk).exists()
    unconfirmed = client.post(
        reverse("accounts:contact_delete", args=[contact.pk]),
        {"version": contact.version, "delete_reason": "Left the company"},
    )
    assert unconfirmed.status_code == 422
    assert b"Check the confirmation" in unconfirmed.content
    assert Contact.objects.filter(pk=contact.pk).exists()
    missing = client.post(
        reverse("accounts:contact_delete", args=[contact.pk]),
        {
            "version": contact.version,
            "delete_reason": "no",
            "confirm_delete": "yes",
        },
    )
    assert missing.status_code == 422
    assert Contact.objects.filter(pk=contact.pk).exists()
    removed = client.post(
        reverse("accounts:contact_delete", args=[contact.pk]),
        {
            "version": contact.version,
            "delete_reason": "Left the company",
            "confirm_delete": "yes",
        },
        follow=True,
    )
    assert b"Contact Drew Singh deleted." in removed.content
    assert Contact.objects.filter(pk=contact.pk).exists() is False
    account.refresh_from_db()
    gone = client.post(
        reverse("accounts:delete", args=[account.pk]),
        {
            "version": account.version,
            "delete_reason": "No longer a customer",
            "confirm_delete": "yes",
        },
        follow=True,
    )
    assert b"Account Northwind deleted." in gone.content
    assert Account.objects.filter(pk=account.pk).exists() is False
    lead = create_lead(
        actor=admin,
        data={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "company_name": "Analytical Engines",
            "email": "ada.delete@example.test",
            "source": "WEB",
            "stage": "NEW",
        },
    )
    lead_page = client.get(reverse("leads:detail", args=[lead.pk]))
    assert lead_page.content.index(b"Delete lead") > lead_page.content.index(
        b"Stage history"
    )
    assert lead_page.content.index(b"Stage history") > lead_page.content.index(
        b"Timeline"
    )
    assert b'<details class="stage-history">' in lead_page.content
    assert b'<details class="stage-history" open' not in lead_page.content
    assert b"Confirmed to delete" in lead_page.content
    assert lead_page.content.index(b'name="delete_reason"') < lead_page.content.index(
        b'class="delete-line"'
    )
    assert lead_page.content.index(b'class="delete-line"') < lead_page.content.index(
        b">Delete lead</button>"
    )
    assert b"confirm_delete_again" not in lead_page.content
