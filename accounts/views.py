"""HTML pages for accounts, contacts, and lead conversion."""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.conversion import ConversionChoiceRequired, convert_lead
from accounts.models import Account, Contact
from accounts.services import (
    account_candidates,
    contacts_for_user,
    create_account,
    create_contact,
    delete_account,
    delete_contact,
    update_account,
    update_contact,
)
from activities.services import timeline
from core.access import activate_viewer_timezone, get_scoped, scoped
from core.display import format_phone
from core.exceptions import VersionConflict
from core.notices import fail_with, failed, succeeded, validation_text
from core.policy import assignable_users, require_action
from core.taxonomy import choice_pairs
from core.validation import clean_phone, require_delete_confirmation
from leads.models import Lead
from sales.models import Deal

PAGE_SIZE = 50


def _request_id(request):
    return getattr(request, "request_id", "")


def _errors(exc):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"detail": exc.messages}


def _account_values(account, posted):
    if posted:
        return posted
    if account is None:
        return {}
    return {
        "name": account.name,
        "account_type": account.account_type,
        "website_url": account.website_url,
        "phone": format_phone(account.phone, empty=""),
        "street": (account.address or {}).get("street", ""),
        "city": (account.address or {}).get("city", ""),
        "region": (account.address or {}).get("region", ""),
        "postal_code": (account.address or {}).get("postal_code", ""),
        "country": (account.address or {}).get("country", ""),
        "industry": account.industry,
        "notes": account.notes,
        "parent": "" if account.parent_id is None else str(account.parent_id),
        "owner": str(account.owner_id),
        "status": account.status,
        "version": account.version,
    }


def _contact_values(contact, posted):
    if posted:
        return posted
    if contact is None:
        return {}
    return {
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "title": contact.title,
        "email": contact.email,
        "work_phone": format_phone(contact.work_phone, empty=""),
        "mobile_phone": format_phone(contact.mobile_phone, empty=""),
        "street": (contact.address or {}).get("street", ""),
        "city": (contact.address or {}).get("city", ""),
        "region": (contact.address or {}).get("region", ""),
        "postal_code": (contact.address or {}).get("postal_code", ""),
        "country": (contact.address or {}).get("country", ""),
        "notes": contact.notes,
        "reports_to": (
            "" if contact.reports_to_id is None else str(contact.reports_to_id)
        ),
        "account": str(contact.account_id),
        "owner": str(contact.owner_id),
        "is_primary": "1" if contact.is_primary else "",
        "version": contact.version,
    }


def _account_form_context(user, account, posted):
    parents = scoped(Account.objects.order_by("name"), user)
    if account is not None:
        parents = parents.exclude(pk=account.pk)
    owners = assignable_users(user, "account")
    return {
        "account": account,
        "errors": None,
        "values": _account_values(account, posted),
        "types": Account.Type.choices,
        "statuses": Account.Status.choices,
        "industries": choice_pairs("INDUSTRY"),
        "parents": parents,
        "owners": owners if owners.count() > 1 else (),
    }


def _contact_form_context(user, account, contact, posted):
    reports = scoped(
        Contact.objects.filter(account=account).order_by("last_name"), user
    )
    if contact is not None:
        reports = reports.exclude(pk=contact.pk)
    owners = assignable_users(user, "contact")
    accounts = scoped(Account.objects.order_by("name"), user)
    return {
        "account": account,
        "contact": contact,
        "errors": None,
        "values": _contact_values(contact, posted),
        "reports": reports,
        "owners": owners if owners.count() > 1 else (),
        "accounts": accounts if contact is not None else (),
    }


def account_list(request):
    activate_viewer_timezone(request.user)
    queryset = scoped(Account.objects.select_related("owner"), request.user)
    query = str(request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(name__icontains=query)
    ordering = request.GET.get("ordering") or "name"
    account_order = {
        "name": "name",
        "-name": "-name",
        "type": "account_type",
        "-type": "-account_type",
        "owner": "owner__display_name",
        "-owner": "-owner__display_name",
    }
    if ordering not in account_order:
        ordering = "name"
    paginator = Paginator(queryset.order_by(account_order[ordering], "pk"), PAGE_SIZE)
    return render(
        request,
        "accounts/account_list.html",
        {
            "page_obj": paginator.get_page(request.GET.get("page") or 1),
            "query": query,
            "ordering": ordering,
        },
    )


def contact_list(request):
    activate_viewer_timezone(request.user)
    contacts = contacts_for_user(request.user)
    params = request.GET
    query = str(params.get("q") or "").strip()
    errors = None
    status = 200
    if len(query) > 100:
        contacts = Contact.objects.none()
        errors = {"q": ["Use 100 characters or fewer."]}
        status = 422
    elif query:
        phone_match = Q(work_phone__icontains=query) | Q(mobile_phone__icontains=query)
        try:
            formatted = clean_phone(query)
        except ValidationError:
            formatted = ""
        if formatted and formatted != query:
            phone_match = (
                phone_match
                | Q(work_phone__icontains=formatted)
                | Q(mobile_phone__icontains=formatted)
            )
        contacts = contacts.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email_normalized__icontains=query)
            | Q(title__icontains=query)
            | phone_match
            | Q(account__name__icontains=query)
        )
    account_id = str(params.get("account") or "").strip()
    if account_id:
        try:
            uuid.UUID(account_id)
        except ValueError:
            contacts = Contact.objects.none()
            errors = {"account": ["Select an account."]}
            status = 422
        else:
            contacts = contacts.filter(account_id=account_id)
    if params.get("primary") == "1":
        contacts = contacts.filter(is_primary=True)
    ordering = params.get("ordering") or "account"
    account_order = "name"
    contact_order = ("last_name", "first_name")
    if ordering == "-account":
        account_order = "-name"
    elif ordering == "name":
        contact_order = ("last_name", "first_name")
    elif ordering == "-name":
        contact_order = ("-last_name", "-first_name")
    elif ordering == "title":
        contact_order = ("title", "last_name")
    account_rows = Account.objects.filter(
        pk__in=contacts.values("account_id")
    ).order_by(account_order, "pk")
    paginator = Paginator(account_rows, PAGE_SIZE)
    page = paginator.get_page(params.get("page") or 1)
    listed = contacts.filter(account__in=list(page.object_list)).order_by(
        *contact_order
    )
    by_account = {}
    for contact in listed:
        by_account.setdefault(contact.account_id, []).append(contact)
    groups = [
        {"account": account, "contacts": by_account.get(account.pk, [])}
        for account in page.object_list
    ]
    return render(
        request,
        "accounts/contact_list.html",
        {
            "groups": groups,
            "page_obj": page,
            "query": params,
            "errors": errors,
            "account_choices": scoped(Account.objects.order_by("name"), request.user),
        },
        status=status,
    )


@require_http_methods(["GET", "POST"])
def account_create(request):
    context = _account_form_context(
        request.user, None, request.POST if request.method == "POST" else None
    )
    status = 200
    if request.method == "POST":
        try:
            account = create_account(
                actor=request.user,
                data=request.POST,
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            context["errors"] = _errors(exc)
            fail_with(request, "Could not add the account.", validation_text(exc))
            status = 422
        else:
            succeeded(request, f"Account {account.name} added.")
            return redirect("accounts:detail", account.pk)
    return render(request, "accounts/account_form.html", context, status=status)


@require_http_methods(["GET", "POST"])
def account_edit(request, account_id):
    activate_viewer_timezone(request.user)
    try:
        account = get_scoped(
            Account, request.user, account_id, related=("owner", "parent")
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    posted = request.POST if request.method == "POST" else None
    context = _account_form_context(request.user, account, posted)
    status = 200
    if request.method == "POST":
        try:
            account = update_account(
                actor=request.user,
                account_id=account.pk,
                version=request.POST.get("version"),
                data=request.POST,
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            context["errors"] = _errors(exc)
            fail_with(request, "Could not save the account.", validation_text(exc))
            status = 422
        except VersionConflict:
            context["errors"] = {
                "version": ["This record was updated. Reload and retry."]
            }
            failed(
                request,
                "Could not save the account. "
                "This record was updated. Reload and retry.",
            )
            status = 409
        except PermissionDenied:
            return render(request, "crm/forbidden.html", status=403)
        else:
            succeeded(request, f"Account {account.name} saved.")
            return redirect("accounts:detail", account.pk)
    return render(request, "accounts/account_form.html", context, status=status)


def account_detail(request, account_id):
    activate_viewer_timezone(request.user)
    account = get_scoped(Account, request.user, account_id, related=("owner", "parent"))
    contacts = Contact.objects.filter(account=account).select_related(
        "owner", "reports_to", "converted_from_lead"
    )
    children = scoped(Account.objects.filter(parent=account), request.user)
    deals = scoped(
        Deal.objects.filter(account=account).select_related("primary_contact", "owner"),
        request.user,
    )
    activities, tasks = timeline(account)
    return render(
        request,
        "accounts/account_detail.html",
        {
            "account": account,
            "contacts": contacts,
            "deals": deals,
            "children": children,
            "activities": activities,
            "tasks": tasks,
            "types": Account.Type.choices,
            "industry_labels": {
                key: label for key, label in choice_pairs("INDUSTRY") if key
            },
        },
    )


@require_POST
def account_delete(request, account_id):
    try:
        require_action(request.user, "account", "D", object_id=account_id)
        require_delete_confirmation(request.POST)
        account = delete_account(
            actor=request.user,
            account_id=account_id,
            version=request.POST.get("version"),
            delete_reason=request.POST.get("delete_reason", ""),
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except Http404:
        raise
    except VersionConflict:
        failed(
            request,
            "Could not delete the account. This record was updated. Reload and retry.",
        )
        response = account_detail(request, account_id)
        response.status_code = 409
        return response
    except ValidationError as exc:
        fail_with(request, "Could not delete the account.", validation_text(exc))
        response = account_detail(request, account_id)
        response.status_code = 422
        return response
    succeeded(request, f"Account {account.name} deleted.")
    return redirect("accounts:list")


@require_http_methods(["GET", "POST"])
def contact_create(request, account_id):
    account = get_scoped(Account, request.user, account_id)
    posted = request.POST if request.method == "POST" else None
    context = _contact_form_context(request.user, account, None, posted)
    status = 200
    if request.method == "POST":
        payload = request.POST.copy()
        payload["account"] = str(account.pk)
        try:
            contact = create_contact(
                actor=request.user,
                data=payload,
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            context["errors"] = _errors(exc)
            fail_with(request, "Could not add the contact.", validation_text(exc))
            status = 422
        else:
            name = f"{contact.first_name} {contact.last_name}".strip()
            succeeded(request, f"Contact {name} added.")
            return redirect("accounts:detail", account.pk)
    return render(request, "accounts/contact_form.html", context, status=status)


@require_http_methods(["GET", "POST"])
def contact_edit(request, contact_id):
    activate_viewer_timezone(request.user)
    try:
        contact = get_scoped(
            Contact,
            request.user,
            contact_id,
            related=("owner", "account", "reports_to"),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    posted = request.POST if request.method == "POST" else None
    account = contact.account
    if posted and posted.get("account"):
        try:
            account = get_scoped(Account, request.user, posted.get("account"))
        except (PermissionDenied, ValidationError, Http404):
            account = contact.account
    context = _contact_form_context(request.user, account, contact, posted)
    status = 200
    if request.method == "POST":
        try:
            contact = update_contact(
                actor=request.user,
                contact_id=contact.pk,
                version=request.POST.get("version"),
                data=request.POST,
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            context["errors"] = _errors(exc)
            fail_with(request, "Could not save the contact.", validation_text(exc))
            status = 422
        except VersionConflict:
            context["errors"] = {
                "version": ["This record was updated. Reload and retry."]
            }
            failed(
                request,
                "Could not save the contact. "
                "This record was updated. Reload and retry.",
            )
            status = 409
        except PermissionDenied:
            return render(request, "crm/forbidden.html", status=403)
        else:
            name = f"{contact.first_name} {contact.last_name}".strip()
            succeeded(request, f"Contact {name} saved.")
            return redirect("accounts:detail", contact.account_id)
    return render(request, "accounts/contact_form.html", context, status=status)


@require_POST
def contact_delete(request, contact_id):
    contact = get_scoped(Contact, request.user, contact_id, related=("account",))
    account_id = contact.account_id
    name = f"{contact.first_name} {contact.last_name}".strip()
    try:
        require_action(request.user, "contact", "D", object_id=contact_id)
        require_delete_confirmation(request.POST)
        delete_contact(
            actor=request.user,
            contact_id=contact_id,
            version=request.POST.get("version"),
            delete_reason=request.POST.get("delete_reason", ""),
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except VersionConflict:
        failed(
            request,
            "Could not delete the contact. This record was updated. Reload and retry.",
        )
        return _contact_edit_page(request, contact, status=409)
    except ValidationError as exc:
        fail_with(request, "Could not delete the contact.", validation_text(exc))
        return _contact_edit_page(request, contact, status=422)
    succeeded(request, f"Contact {name} deleted.")
    return redirect("accounts:detail", account_id)


def _contact_edit_page(request, contact, status=200):
    context = _contact_form_context(request.user, contact.account, contact, None)
    return render(request, "accounts/contact_form.html", context, status=status)


@require_http_methods(["GET", "POST"])
def lead_convert(request, lead_id):
    activate_viewer_timezone(request.user)
    lead = get_scoped(Lead, request.user, lead_id)
    errors = None
    choice = None
    status = 200
    candidates = account_candidates(name=lead.company_name, domain=lead.website_domain)
    if request.method == "POST":
        try:
            result = convert_lead(
                actor=request.user,
                lead_id=lead.pk,
                version=request.POST.get("version"),
                data=request.POST,
                request_id=_request_id(request),
            )
        except ConversionChoiceRequired as exc:
            choice = exc.payload
            failed(request, "Could not convert the lead. Confirm the matching account.")
            status = 422
        except VersionConflict:
            errors = {"version": ["This record was updated. Reload and retry."]}
            failed(
                request,
                "Could not convert the lead. "
                "This record was updated. Reload and retry.",
            )
            status = 409
        except PermissionDenied:
            raise
        except ValidationError as exc:
            errors = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else {"detail": exc.messages}
            )
            fail_with(request, "Could not convert the lead.", validation_text(exc))
            status = 422
        else:
            succeeded(request, f"Lead {lead.first_name} {lead.last_name} converted.")
            return redirect("accounts:detail", result["account_id"])
    return render(
        request,
        "leads/convert.html",
        {
            "lead": lead,
            "candidates": candidates,
            "errors": errors,
            "choice": choice,
            "types": Account.Type.choices,
            "posted": request.POST,
        },
        status=status,
    )
