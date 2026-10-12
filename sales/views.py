"""HTML pages for lead-linked deals."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.access import activate_viewer_timezone, get_scoped
from core.exceptions import VersionConflict
from core.validation import add_form_errors
from sales.forms import DealDeleteForm, DealForm
from sales.models import Deal
from sales.services import create_deal, delete_deal, filter_deals, update_deal

PAGE_SIZE = 50


def _request_id(request):
    return getattr(request, "request_id", "")


def deal_list(request):
    activate_viewer_timezone(request.user)
    status = 200
    try:
        queryset = filter_deals(request.user, request.GET)
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
    filters = request.GET.copy()
    filters.pop("page", None)
    context = {
        "page_obj": page,
        "errors": errors,
        "query": request.GET,
        "filter_query": filters.urlencode(),
    }
    template = "sales/_deal_results.html" if request.htmx else "sales/deal_list.html"
    return render(request, template, context, status=status)


@require_http_methods(["GET", "POST"])
def deal_create(request):
    activate_viewer_timezone(request.user)
    initial = {}
    if request.GET.get("lead"):
        initial["lead"] = request.GET.get("lead")
    form = DealForm(request.POST or None, user=request.user, initial=initial)
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
            status = 422
        else:
            return redirect("sales:detail", deal.pk)
    elif request.method == "POST":
        status = 422
    return render(request, "sales/deal_form.html", {"form": form}, status=status)


def deal_detail(request, deal_id):
    activate_viewer_timezone(request.user)
    try:
        deal = get_scoped(Deal, request.user, deal_id, related=("owner", "lead"))
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    return render(
        request,
        "sales/deal_detail.html",
        {
            "deal": deal,
            "delete_form": DealDeleteForm(initial={"version": deal.version}),
        },
    )


@require_http_methods(["GET", "POST"])
def deal_edit(request, deal_id):
    activate_viewer_timezone(request.user)
    try:
        deal = get_scoped(Deal, request.user, deal_id, related=("owner", "lead"))
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    form = DealForm(request.POST or None, user=request.user, instance=deal)
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
            status = 422
        except VersionConflict:
            form.add_error(None, "This record was updated. Reload and retry.")
            status = 409
        else:
            return redirect("sales:detail", deal.pk)
    elif request.method == "POST":
        status = 422
    return render(
        request,
        "sales/deal_form.html",
        {"form": form, "deal": deal},
        status=status,
    )


@require_POST
def deal_delete(request, deal_id):
    form = DealDeleteForm(request.POST)
    if not form.is_valid():
        return redirect("sales:detail", deal_id)
    try:
        delete_deal(
            actor=request.user,
            deal_id=deal_id,
            version=form.cleaned_data["version"],
            delete_reason=form.cleaned_data["delete_reason"],
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    except ValidationError as exc:
        deal = get_scoped(Deal, request.user, deal_id, related=("owner", "lead"))
        add_form_errors(form, exc)
        return render(
            request,
            "sales/deal_detail.html",
            {"deal": deal, "delete_form": form},
            status=422,
        )
    except VersionConflict:
        deal = get_scoped(Deal, request.user, deal_id, related=("owner", "lead"))
        form.add_error(None, "This record was updated. Reload and retry.")
        return render(
            request,
            "sales/deal_detail.html",
            {"deal": deal, "delete_form": form},
            status=409,
        )
    return redirect("sales:list")
