"""Import pages for lead, account, and contact CSV files."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.notices import fail_with, succeeded, validation_text, warned
from core.policy import allows
from imports.columns import COLUMNS, ENTITIES, template_csv
from imports.models import ImportBatch
from imports.services import (
    can_import,
    commit_import,
    export_csv,
    preview_import,
    rollback_import,
)

LABELS = {"lead": "Leads", "account": "Accounts", "contact": "Contacts"}


def _request_id(request):
    return getattr(request, "request_id", "")


def _guard(request):
    if not can_import(request.user):
        raise PermissionDenied


@login_required
def home(request):
    _guard(request)
    guides = []
    for entity in ENTITIES:
        guides.append(
            {
                "entity": entity,
                "label": LABELS[entity],
                "columns": COLUMNS[entity],
                "can_export": allows(request.user, entity, "X"),
            }
        )
    return render(request, "imports/home.html", {"guides": guides})


@login_required
def template_file(request, entity):
    _guard(request)
    if entity not in ENTITIES:
        raise Http404
    response = HttpResponse(
        template_csv(entity), content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{entity}s-template.csv"'
    return response


@login_required
@require_POST
def preview(request):
    _guard(request)
    upload = request.FILES.get("file")
    if upload is None:
        fail_with(request, "Could not preview the import.", "Choose a CSV file.")
        return render(
            request,
            "imports/home.html",
            {"guides": _guides(request), "errors": {"file": ["Choose a CSV file."]}},
            status=422,
        )
    try:
        batch = preview_import(
            actor=request.user,
            entity=request.POST.get("entity", ""),
            upload_name=upload.name,
            content_type=upload.content_type or "",
            content=upload.read(),
            policy=request.POST.get("policy", "skip"),
            idempotency_key=request.POST.get("idempotency_key", ""),
            request_id=_request_id(request),
        )
    except ValidationError as exc:
        fail_with(request, "Could not preview the import.", validation_text(exc))
        return render(
            request,
            "imports/home.html",
            {"guides": _guides(request), "errors": exc.message_dict},
            status=422,
        )
    problems = batch.summary.get("error_count", 0)
    if problems:
        noun = "row needs" if problems == 1 else "rows need"
        warned(request, f"Preview finished. {problems} {noun} attention.")
    else:
        succeeded(request, "Preview finished. The file is ready to import.")
    return redirect("imports:detail", batch.pk)


def _guides(request):
    return [
        {
            "entity": entity,
            "label": LABELS[entity],
            "columns": COLUMNS[entity],
            "can_export": allows(request.user, entity, "X"),
        }
        for entity in ENTITIES
    ]


@login_required
def detail(request, batch_id):
    _guard(request)
    batch = _batch(request, batch_id)
    return render(
        request,
        "imports/detail.html",
        {"batch": batch, "label": LABELS.get(batch.entity, batch.entity)},
    )


@login_required
@require_POST
def commit(request, batch_id):
    _guard(request)
    _batch(request, batch_id)
    try:
        batch = commit_import(
            actor=request.user,
            batch_id=batch_id,
            request_id=_request_id(request),
        )
    except ValidationError as exc:
        batch = _batch(request, batch_id)
        fail_with(request, "Could not finish the import.", validation_text(exc))
        return render(
            request,
            "imports/detail.html",
            {
                "batch": batch,
                "label": LABELS.get(batch.entity, batch.entity),
                "errors": exc.message_dict,
            },
            status=422,
        )
    if batch.status == "incomplete":
        warned(
            request,
            "Import stopped. Rows already saved stay in place. Try again for the rest.",
        )
    else:
        succeeded(request, "Import finished.")
    return redirect("imports:detail", batch.pk)


@login_required
@require_POST
def rollback(request, batch_id):
    _guard(request)
    try:
        batch = rollback_import(
            actor=request.user,
            batch_id=batch_id,
            request_id=_request_id(request),
        )
    except ValidationError as exc:
        batch = _batch(request, batch_id)
        fail_with(request, "Could not roll back the import.", validation_text(exc))
        return render(
            request,
            "imports/detail.html",
            {
                "batch": batch,
                "label": LABELS.get(batch.entity, batch.entity),
                "errors": exc.message_dict,
            },
            status=422,
        )
    succeeded(request, "Import rolled back.")
    return redirect("imports:detail", batch.pk)


@login_required
def export_file(request, entity):
    if entity not in ENTITIES:
        raise Http404
    try:
        body = export_csv(actor=request.user, entity=entity)
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{entity}s.csv"'
    return response


def _batch(request, batch_id):
    try:
        batch = ImportBatch.objects.get(pk=batch_id)
    except ImportBatch.DoesNotExist as exc:
        raise Http404 from exc
    if batch.actor_id != request.user.pk and not allows(request.user, "import", "A"):
        raise Http404
    return batch
