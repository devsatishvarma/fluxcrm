"""HTML pages for leads."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.access import activate_viewer_timezone, get_scoped, scoped
from core.exceptions import VersionConflict
from core.taxonomy import choice_pairs
from core.validation import add_form_errors
from identity.models import User
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
    from activities.services import attach_freshness

    attach_freshness(list(page.object_list), "lead")
    filters = request.GET.copy()
    filters.pop("page", None)
    context = {
        "page_obj": page,
        "errors": errors,
        "query": request.GET,
        "filter_query": filters.urlencode(),
        "source_choices": choice_pairs("LEAD_SOURCE"),
        "stage_choices": choice_pairs("LEAD_STAGE"),
        "rating_choices": choice_pairs("LEAD_RATING"),
        "owner_choices": (
            User.objects.filter(is_active=True).order_by("display_name")
            if request.user.is_company_admin
            else ()
        ),
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
    from core.workflow import LEAD_BOARD_STAGES, LEAD_GRAPH, allowed_targets
    from leads.services import lead_history

    stages = allowed_targets(LEAD_GRAPH, lead.stage)
    from activities.services import timeline

    activities, tasks = timeline(lead)
    return render(
        request,
        "leads/lead_detail.html",
        {
            "lead": lead,
            "deals": deals,
            "activities": activities,
            "tasks": tasks,
            "history": lead_history(lead).select_related("changed_by"),
            "allowed_stages": stages,
            "contact_substatus_choices": choice_pairs("CONTACT_SUBSTATUS"),
            "nurture_reason_choices": choice_pairs("NURTURE_REASON"),
            "disqualification_reason_choices": choice_pairs("DISQUALIFICATION_REASON"),
            "correction_stages": (
                tuple(LEAD_BOARD_STAGES) if request.user.is_company_admin else ()
            ),
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


def lead_board(request):
    from core.workflow import LEAD_BOARD_STAGES, LEAD_GRAPH, allowed_targets

    activate_viewer_timezone(request.user)
    leads = list(filter_leads(request.user, request.GET))
    columns = {stage: [] for stage in LEAD_BOARD_STAGES}
    for lead in leads:
        lead.allowed_stage_targets = allowed_targets(LEAD_GRAPH, lead.stage)
        columns.setdefault(lead.stage, []).append(lead)
    return render(
        request,
        "leads/lead_board.html",
        {"columns": columns.items(), "error": None},
    )


@require_POST
def lead_transition(request, lead_id):
    from leads.services import transition_lead

    correction = request.POST.get("correction") == "1"
    try:
        lead = transition_lead(
            actor=request.user,
            lead_id=lead_id,
            version=request.POST.get("version"),
            to_stage=request.POST.get("to_stage"),
            reason=request.POST.get("reason", ""),
            data=request.POST,
            correction=correction,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _transition_error(
            request, {"detail": ["You cannot make that change."]}, 403
        )
    except VersionConflict:
        return _transition_error(
            request, {"detail": ["This record was updated. Reload and retry."]}, 409
        )
    except ValidationError as exc:
        if hasattr(exc, "message_dict"):
            payload = exc.message_dict
        else:
            payload = {"detail": exc.messages}
        return _transition_error(request, payload, 422)
    if request.headers.get("X-Requested-With") == "fetch":
        from django.http import JsonResponse

        return JsonResponse({"stage": lead.stage, "version": lead.version})
    return redirect("leads:board")


def _transition_error(request, payload, status):
    from django.http import JsonResponse

    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(payload, status=status)
    return render(
        request,
        "crm/transition_error.html",
        {"errors": payload},
        status=status,
    )
