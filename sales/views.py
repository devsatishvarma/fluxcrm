"""HTML pages for deals on a lead or an account."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.access import activate_viewer_timezone, get_scoped
from core.exceptions import VersionConflict
from core.notices import (
    fail_with,
    failed,
    form_text,
    stage_name,
    succeeded,
    validation_text,
)
from core.policy import assignable_users, can_correct, require_action
from core.taxonomy import choice_pairs
from core.validation import add_form_errors, require_delete_confirmation
from sales.forms import DealDeleteForm, DealForm
from sales.models import Deal
from sales.services import (
    DEAL_RELATED,
    create_deal,
    delete_deal,
    filter_deals,
    update_deal,
)

PAGE_SIZE = 50


def _request_id(request):
    return getattr(request, "request_id", "")


def deal_list(request):
    from core.workflow import CLOSED_DEAL_STAGES

    activate_viewer_timezone(request.user)
    status = 200
    try:
        queryset = filter_deals(request.user, request.GET).exclude(
            stage__in=CLOSED_DEAL_STAGES
        )
        errors = None
    except ValidationError as exc:
        queryset = Deal.objects.none()
        errors = (
            exc.message_dict
            if hasattr(exc, "message_dict")
            else {"detail": exc.messages}
        )
        status = 422
    paginator = Paginator(queryset, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page") or 1)
    from activities.services import attach_freshness

    attach_freshness(list(page.object_list), "deal")
    filters = request.GET.copy()
    filters.pop("page", None)
    from sales.services import open_pipeline_total, owner_amount_totals

    context = {
        "page_obj": page,
        "errors": errors,
        "query": request.GET,
        "filter_query": filters.urlencode(),
        "open_total": open_pipeline_total(request.user),
        "owner_totals": owner_amount_totals(queryset),
        "stage_choices": [
            (key, label)
            for key, label in choice_pairs("DEAL_STAGE")
            if key not in CLOSED_DEAL_STAGES
        ],
        "type_choices": choice_pairs("DEAL_TYPE"),
        "confidence_choices": choice_pairs("DEAL_CONFIDENCE"),
        "owner_choices": (
            assignable_users(request.user, "deal")
            if assignable_users(request.user, "deal").count() > 1
            else ()
        ),
    }
    if not request.htmx:
        from reporting.services import deal_report_groups

        context["report_groups"] = deal_report_groups(request.user)
    template = "sales/_deal_results.html" if request.htmx else "sales/deal_list.html"
    return render(request, template, context, status=status)


def _account_for_new_deal(request):
    if request.method == "POST" and (
        request.POST.get("lead") or request.POST.get("linked_to")
    ):
        return None
    account_id = ""
    if request.method == "POST":
        account_id = request.POST.get("account") or ""
    if not account_id:
        account_id = request.GET.get("account") or ""
    if not account_id:
        return None
    from accounts.models import Account

    return get_scoped(Account, request.user, account_id)


@require_http_methods(["GET", "POST"])
def deal_create(request):
    activate_viewer_timezone(request.user)
    try:
        account = _account_for_new_deal(request)
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    initial = {}
    if account is None and request.GET.get("lead"):
        initial["lead"] = request.GET.get("lead")
        initial["linked_to"] = "lead"
    form = DealForm(
        request.POST or None,
        user=request.user,
        initial=initial,
        account=account,
    )
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            deal = create_deal(
                actor=request.user,
                data=form.service_data(),
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            add_form_errors(form, exc)
            fail_with(request, "Could not add the deal.", validation_text(exc))
            status = 422
        else:
            succeeded(request, f"Deal {deal.title} added.")
            return redirect("sales:detail", deal.pk)
    elif request.method == "POST":
        fail_with(request, "Could not add the deal.", form_text(form))
        status = 422
    return render(
        request,
        "sales/deal_form.html",
        {"form": form, "account": account},
        status=status,
    )


def deal_detail(request, deal_id):
    activate_viewer_timezone(request.user)
    try:
        deal = get_scoped(Deal, request.user, deal_id, related=DEAL_RELATED)
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    from core.taxonomy import DEAL_STAGE_PROBABILITY
    from core.workflow import DEAL_GRAPH, allowed_targets
    from sales.services import deal_history

    stages = allowed_targets(DEAL_GRAPH, deal.stage)
    bant_choices = choice_pairs("BANT_STATUS")
    from activities.services import timeline

    activities, tasks = timeline(deal)
    return render(
        request,
        "sales/deal_detail.html",
        {
            "deal": deal,
            "activities": activities,
            "tasks": tasks,
            "history": deal_history(deal).select_related("changed_by"),
            "allowed_stages": stages,
            "stage_order": tuple(DEAL_STAGE_PROBABILITY),
            "stage_labels": {
                key: label for key, label in choice_pairs("DEAL_STAGE") if key
            },
            "can_override": can_correct(request.user),
            "bant_choices": bant_choices,
            "bant_labels": {key: label for key, label in bant_choices if key},
            "lost_reason_choices": choice_pairs("CLOSED_LOST_REASON"),
            "hold_reason_choices": choice_pairs("CLOSED_HOLD_REASON"),
            "correction_stages": (
                tuple(DEAL_STAGE_PROBABILITY) if can_correct(request.user) else ()
            ),
            "delete_form": DealDeleteForm(initial={"version": deal.version}),
        },
    )


@require_http_methods(["GET", "POST"])
def deal_edit(request, deal_id):
    activate_viewer_timezone(request.user)
    try:
        deal = get_scoped(Deal, request.user, deal_id, related=DEAL_RELATED)
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    source_account = deal.account if deal.lead_id is None else None
    form = DealForm(
        request.POST or None,
        user=request.user,
        instance=deal,
        account=source_account,
    )
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            deal = update_deal(
                actor=request.user,
                deal_id=deal.pk,
                version=form.cleaned_data["version"],
                data=form.service_data(),
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            add_form_errors(form, exc)
            fail_with(request, "Could not save the deal.", validation_text(exc))
            status = 422
        except PermissionDenied:
            message = (
                "Only an administrator or sales director can change "
                "the win probability."
            )
            form.add_error("probability", message)
            fail_with(request, "Could not save the deal.", message)
            status = 403
        except VersionConflict:
            form.add_error(None, "This record was updated. Reload and retry.")
            failed(
                request,
                "Could not save the deal. This record was updated. Reload and retry.",
            )
            status = 409
        else:
            succeeded(request, f"Deal {deal.title} saved.")
            return redirect("sales:detail", deal.pk)
    elif request.method == "POST":
        fail_with(request, "Could not save the deal.", form_text(form))
        status = 422
    return render(
        request,
        "sales/deal_form.html",
        {"form": form, "deal": deal, "account": source_account},
        status=status,
    )


@require_POST
def deal_delete(request, deal_id):
    form = DealDeleteForm(request.POST)
    if not form.is_valid():
        deal = get_scoped(Deal, request.user, deal_id, related=DEAL_RELATED)
        fail_with(request, "Could not delete the deal.", form_text(form))
        return render(
            request,
            "sales/deal_detail.html",
            {"deal": deal, "delete_form": form},
            status=422,
        )
    try:
        require_action(request.user, "deal", "D", object_id=deal_id)
        require_delete_confirmation(request.POST)
        deal = delete_deal(
            actor=request.user,
            deal_id=deal_id,
            version=form.cleaned_data["version"],
            delete_reason=form.cleaned_data["delete_reason"],
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except ValidationError as exc:
        deal = get_scoped(Deal, request.user, deal_id, related=DEAL_RELATED)
        add_form_errors(form, exc)
        fail_with(request, "Could not delete the deal.", validation_text(exc))
        return render(
            request,
            "sales/deal_detail.html",
            {"deal": deal, "delete_form": form},
            status=422,
        )
    except VersionConflict:
        deal = get_scoped(Deal, request.user, deal_id, related=DEAL_RELATED)
        form.add_error(None, "This record was updated. Reload and retry.")
        failed(
            request,
            "Could not delete the deal. This record was updated. Reload and retry.",
        )
        return render(
            request,
            "sales/deal_detail.html",
            {"deal": deal, "delete_form": form},
            status=409,
        )
    succeeded(request, f"Deal {deal.title} deleted.")
    return redirect("sales:list")


def deal_board(request):
    from core.workflow import OPEN_DEAL_STAGES

    activate_viewer_timezone(request.user)
    deals = list(filter_deals(request.user, {}).filter(stage__in=OPEN_DEAL_STAGES))
    columns = {stage: [] for stage in OPEN_DEAL_STAGES}
    for deal in deals:
        columns[deal.stage].append(deal)
    from sales.services import open_pipeline_total

    return render(
        request,
        "sales/deal_board.html",
        {
            "columns": columns.items(),
            "open_total": open_pipeline_total(request.user),
        },
    )


@require_POST
def deal_transition(request, deal_id):
    from sales.services import transition_deal

    correction = request.POST.get("correction") == "1"
    try:
        deal = transition_deal(
            actor=request.user,
            deal_id=deal_id,
            version=request.POST.get("version"),
            to_stage=request.POST.get("to_stage"),
            reason=request.POST.get("reason", ""),
            data=request.POST,
            correction=correction,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        from leads.views import _transition_error

        return _transition_error(
            request, {"detail": ["You cannot make that change."]}, 403
        )
    except VersionConflict:
        from leads.views import _transition_error

        return _transition_error(
            request, {"detail": ["This record was updated. Reload and retry."]}, 409
        )
    except ValidationError as exc:
        from leads.views import _transition_error

        if hasattr(exc, "message_dict"):
            payload = exc.message_dict
        else:
            payload = {"detail": exc.messages}
        return _transition_error(request, payload, 422)
    if correction:
        succeeded(request, "Deal correction saved.")
    else:
        succeeded(request, f"Deal moved to {stage_name('DEAL_STAGE', deal.stage)}.")
    if request.headers.get("X-Requested-With") == "fetch":
        from django.http import JsonResponse

        return JsonResponse({"stage": deal.stage, "version": deal.version})
    return redirect("sales:board")
