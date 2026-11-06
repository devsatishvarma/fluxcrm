"""HTML pages for leads."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.access import activate_viewer_timezone, get_scoped, scoped
from core.exceptions import VersionConflict
from core.notices import (
    fail_with,
    failed,
    form_text,
    payload_text,
    stage_name,
    succeeded,
    validation_text,
)
from core.policy import assignable_users, can_correct, require_action
from core.taxonomy import choice_pairs
from core.validation import add_form_errors, require_delete_confirmation
from leads.forms import LeadDeleteForm, LeadForm
from leads.models import Lead
from leads.services import (
    bulk_assign_leads,
    create_lead,
    delete_lead,
    filter_leads,
    page_leads,
    update_lead,
)
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
    page = page_leads(queryset, request.GET.get("page") or 1, PAGE_SIZE)
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
            assignable_users(request.user, "lead")
            if assignable_users(request.user, "lead").count() > 1
            else ()
        ),
    }
    template = "leads/_lead_results.html" if request.htmx else "leads/lead_list.html"
    return render(request, template, context, status=status)


@require_http_methods(["GET", "POST"])
def lead_create(request):
    activate_viewer_timezone(request.user)
    if request.method == "POST":
        try:
            require_action(request.user, "lead", "C")
        except PermissionDenied:
            return render(request, "crm/forbidden.html", status=403)
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
            fail_with(request, "Could not add the lead.", validation_text(exc))
            status = 422
        else:
            name = f"{lead.first_name} {lead.last_name}".strip()
            succeeded(request, f"Lead {name} added.")
            return redirect("leads:detail", lead.pk)
    elif request.method == "POST":
        fail_with(request, "Could not add the lead.", form_text(form))
        status = 422
    return render(request, "leads/lead_form.html", {"form": form}, status=status)


def lead_detail(request, lead_id):
    activate_viewer_timezone(request.user)
    try:
        lead = get_scoped(
            Lead,
            request.user,
            lead_id,
            related=("owner", "converted_contact", "converted_account"),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    deals = scoped(
        Deal.objects.filter(Q(lead=lead) | Q(converted_from_lead=lead)).select_related(
            "owner", "account"
        ),
        request.user,
    )
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
            "stage_order": LEAD_BOARD_STAGES,
            "stage_labels": {
                key: label for key, label in choice_pairs("LEAD_STAGE") if key
            },
            "contact_substatus_choices": choice_pairs("CONTACT_SUBSTATUS"),
            "nurture_reason_choices": choice_pairs("NURTURE_REASON"),
            "disqualification_reason_choices": choice_pairs("DISQUALIFICATION_REASON"),
            "company_size_choices": choice_pairs("COMPANY_SIZE"),
            "current_tools_choices": choice_pairs("CURRENT_TOOLS"),
            "budget_range_choices": choice_pairs("BUDGET_RANGE"),
            "buying_timeline_choices": choice_pairs("BUYING_TIMELINE"),
            "correction_stages": (
                tuple(LEAD_BOARD_STAGES) if can_correct(request.user) else ()
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
    if request.method == "POST":
        try:
            require_action(request.user, "lead", "U", object_id=lead_id)
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
            fail_with(request, "Could not save the lead.", validation_text(exc))
            status = 422
        except VersionConflict:
            form.add_error(
                None,
                "This record was updated. Reload and retry.",
            )
            failed(
                request,
                "Could not save the lead. This record was updated. Reload and retry.",
            )
            status = 409
        else:
            name = f"{lead.first_name} {lead.last_name}".strip()
            succeeded(request, f"Lead {name} saved.")
            return redirect("leads:detail", lead.pk)
    elif request.method == "POST":
        fail_with(request, "Could not save the lead.", form_text(form))
        status = 422
    return render(
        request,
        "leads/lead_form.html",
        {"form": form, "lead": lead},
        status=status,
    )


@require_POST
def lead_bulk_assign(request):
    try:
        bulk_assign_leads(
            actor=request.user,
            lead_ids=request.POST.getlist("lead"),
            owner=request.POST.get("owner"),
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except ValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=422)
    succeeded(request, "Leads reassigned.")
    return redirect("leads:list")


@require_POST
def lead_delete(request, lead_id):
    form = LeadDeleteForm(request.POST)
    if not form.is_valid():
        fail_with(request, "Could not delete the lead.", form_text(form))
        return render(request, "leads/lead_form.html", {"form": form}, status=422)
    try:
        require_action(request.user, "lead", "D", object_id=lead_id)
        require_delete_confirmation(request.POST)
        lead = delete_lead(
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
        fail_with(request, "Could not delete the lead.", validation_text(exc))
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
        failed(
            request,
            "Could not delete the lead. This record was updated. Reload and retry.",
        )
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
    name = f"{lead.first_name} {lead.last_name}".strip()
    succeeded(request, f"Lead {name} deleted.")
    return redirect("leads:list")


def lead_board(request):
    from core.workflow import LEAD_BOARD_STAGES

    activate_viewer_timezone(request.user)
    leads = list(filter_leads(request.user, request.GET))
    columns = {stage: [] for stage in LEAD_BOARD_STAGES}
    for lead in leads:
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
    if correction:
        succeeded(request, "Lead correction saved.")
    else:
        succeeded(request, f"Lead moved to {stage_name('LEAD_STAGE', lead.stage)}.")
    if request.headers.get("X-Requested-With") == "fetch":
        from django.http import JsonResponse

        return JsonResponse({"stage": lead.stage, "version": lead.version})
    return redirect("leads:board")


def _transition_error(request, payload, status):
    from django.http import JsonResponse

    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(payload, status=status)
    fail_with(request, "Could not change the stage.", payload_text(payload))
    return render(
        request,
        "crm/transition_error.html",
        {"errors": payload},
        status=status,
    )
