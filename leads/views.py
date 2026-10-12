"""HTML pages for leads."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.access import activate_viewer_timezone, get_scoped, scoped
from core.exceptions import VersionConflict
from core.validation import add_form_errors
from leads.forms import LeadDeleteForm, LeadForm
from leads.models import Lead
from leads.services import create_lead, delete_lead, filter_leads, update_lead
from sales.models import Deal

PAGE_SIZE = 50


def _request_id(request):
    return getattr(request, "request_id", "")


def lead_list(request):
    activate_viewer_timezone(request.user)
    status = 200
    try:
        queryset = filter_leads(request.user, request.GET)
        errors = None
    except ValidationError as exc:
        queryset = Lead.objects.none()
        errors = (
            exc.message_dict
            if hasattr(exc, "message_dict")
            else {"detail": exc.messages}
        )
        status = 422
    paginator = Paginator(queryset, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page") or 1)
    filters = request.GET.copy()
    filters.pop("page", None)
    context = {
        "page_obj": page,
        "errors": errors,
        "query": request.GET,
        "filter_query": filters.urlencode(),
    }
    template = "leads/_lead_results.html" if request.htmx else "leads/lead_list.html"
    return render(request, template, context, status=status)


@require_http_methods(["GET", "POST"])
def lead_create(request):
    activate_viewer_timezone(request.user)
    form = LeadForm(request.POST or None, user=request.user)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            lead = create_lead(
                actor=request.user,
                data=form.service_data(),
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            add_form_errors(form, exc)
            status = 422
        else:
            return redirect("leads:detail", lead.pk)
    elif request.method == "POST":
        status = 422
    return render(request, "leads/lead_form.html", {"form": form}, status=status)


def lead_detail(request, lead_id):
    activate_viewer_timezone(request.user)
    try:
        lead = get_scoped(Lead, request.user, lead_id)
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    deals = scoped(Deal.objects.filter(lead=lead).select_related("owner"), request.user)
    return render(
        request,
        "leads/lead_detail.html",
        {
            "lead": lead,
            "deals": deals,
            "delete_form": LeadDeleteForm(initial={"version": lead.version}),
        },
    )


@require_http_methods(["GET", "POST"])
def lead_edit(request, lead_id):
    activate_viewer_timezone(request.user)
    try:
        lead = get_scoped(Lead, request.user, lead_id)
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    form = LeadForm(request.POST or None, user=request.user, instance=lead)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            lead = update_lead(
                actor=request.user,
                lead_id=lead.pk,
                version=form.cleaned_data["version"],
                data=form.service_data(),
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            add_form_errors(form, exc)
            status = 422
        except VersionConflict:
            form.add_error(
                None,
                "This record was updated. Reload and retry.",
            )
            status = 409
        else:
            return redirect("leads:detail", lead.pk)
    elif request.method == "POST":
        status = 422
    return render(
        request,
        "leads/lead_form.html",
        {"form": form, "lead": lead},
        status=status,
    )


@require_POST
def lead_delete(request, lead_id):
    form = LeadDeleteForm(request.POST)
    if not form.is_valid():
        return render(request, "leads/lead_form.html", {"form": form}, status=422)
    try:
        delete_lead(
            actor=request.user,
            lead_id=lead_id,
            version=form.cleaned_data["version"],
            delete_reason=form.cleaned_data["delete_reason"],
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except Http404:
        raise
    except ValidationError as exc:
        try:
            lead = get_scoped(Lead, request.user, lead_id)
        except (PermissionDenied, Http404):
            raise
        form = LeadDeleteForm(request.POST)
        add_form_errors(form, exc)
        return render(
            request,
            "leads/lead_detail.html",
            {
                "lead": lead,
                "deals": scoped(Deal.objects.filter(lead=lead), request.user),
                "delete_form": form,
            },
            status=422,
        )
    except VersionConflict:
        lead = get_scoped(Lead, request.user, lead_id)
        form.add_error(None, "This record was updated. Reload and retry.")
        return render(
            request,
            "leads/lead_detail.html",
            {
                "lead": lead,
                "deals": scoped(Deal.objects.filter(lead=lead), request.user),
                "delete_form": form,
            },
            status=409,
        )
    return redirect("leads:list")
