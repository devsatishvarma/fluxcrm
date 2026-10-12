"""HTML pages for accounts, contacts, and lead conversion."""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.conversion import ConversionChoiceRequired, convert_lead
from accounts.models import Account, Contact
from accounts.services import (
    account_candidates,
    contacts_for_user,
    create_account,
    create_contact,
)
from activities.services import timeline
from core.access import activate_viewer_timezone, get_scoped, scoped
from core.exceptions import VersionConflict
from leads.models import Lead

PAGE_SIZE = 50


def _request_id(request):
    return getattr(request, "request_id", "")


def account_list(request):
    activate_viewer_timezone(request.user)
    queryset = scoped(Account.objects.select_related("owner"), request.user)
    query = str(request.GET.get("q") or "").strip()
    if query:
        queryset = queryset.filter(name__icontains=query)
    paginator = Paginator(queryset.order_by("name"), PAGE_SIZE)
    return render(
        request,
        "accounts/account_list.html",
        {"page_obj": paginator.get_page(request.GET.get("page") or 1), "query": query},
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
        contacts = contacts.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email_normalized__icontains=query)
            | Q(title__icontains=query)
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
    account_rows = Account.objects.filter(
        pk__in=contacts.values("account_id")
    ).order_by("name")
    paginator = Paginator(account_rows, PAGE_SIZE)
    page = paginator.get_page(params.get("page") or 1)
    listed = contacts.filter(account__in=list(page.object_list)).order_by(
        "last_name", "first_name"
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
    errors = None
    status = 200
    if request.method == "POST":
        try:
            account = create_account(
                actor=request.user,
                data=request.POST,
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            errors = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else {"detail": exc.messages}
            )
            status = 422
        else:
            return redirect("accounts:detail", account.pk)
    return render(
        request,
        "accounts/account_form.html",
        {"errors": errors, "types": Account.Type.choices, "posted": request.POST},
        status=status,
    )


def account_detail(request, account_id):
    activate_viewer_timezone(request.user)
    account = get_scoped(Account, request.user, account_id, related=("owner", "parent"))
    contacts = Contact.objects.filter(account=account).select_related(
        "owner", "reports_to", "converted_from_lead"
    )
    children = scoped(Account.objects.filter(parent=account), request.user)
    return render(
        request,
        "accounts/account_detail.html",
        {
            "account": account,
            "contacts": contacts,
            "children": children,
            "activities": timeline(account)[0],
            "types": Account.Type.choices,
        },
    )


@require_http_methods(["GET", "POST"])
def contact_create(request, account_id):
    account = get_scoped(Account, request.user, account_id)
    errors = None
    status = 200
    if request.method == "POST":
        payload = request.POST.copy()
        payload["account"] = str(account.pk)
        try:
            create_contact(
                actor=request.user,
                data=payload,
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            errors = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else {"detail": exc.messages}
            )
            status = 422
        else:
            return redirect("accounts:detail", account.pk)
    reports = scoped(Contact.objects.filter(account=account), request.user)
    return render(
        request,
        "accounts/contact_form.html",
        {
            "account": account,
            "errors": errors,
            "reports": reports,
            "posted": request.POST,
        },
        status=status,
    )


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
            status = 422
        except VersionConflict:
            errors = {"version": ["This record was updated. Reload and retry."]}
            status = 409
        except PermissionDenied:
            raise
        except ValidationError as exc:
            errors = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else {"detail": exc.messages}
            )
            status = 422
        else:
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
