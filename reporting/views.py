"""Report pages. Totals use the same record scope as the lists."""

import logging
import time

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.api import parse_page_size
from reporting.services import (
    QUERY_BUDGET,
    REPORT_KEYS,
    REPORTS,
    build_report,
    can_export_reports,
    can_view_reports,
    detail_page,
    export_report,
    report_csv,
)
from reporting.services import (
    dashboard as dashboard_summary,
)

logger = logging.getLogger(__name__)


def _params(request):
    return {"start": request.GET.get("start", ""), "end": request.GET.get("end", "")}


def _chart(report):
    rows = [row for row in report["rows"] if row.get("chart", True)]
    series = report.get("chart_series")
    if series:
        return {
            "labels": [row.get("label", "") for row in rows],
            "datasets": [
                {
                    "label": item["label"],
                    "data": [float(row.get(item["field"]) or 0) for row in rows],
                }
                for item in series
            ],
        }
    value_key = report.get("chart_field", "count")
    numeric_rows = [row for row in rows if not isinstance(row.get(value_key), str)]
    return {
        "labels": [row.get("label", "") for row in numeric_rows],
        "datasets": [
            {
                "label": report.get("title", ""),
                "data": [float(row.get(value_key) or 0) for row in numeric_rows],
            }
        ],
    }


@login_required
def dashboard(request):
    if not can_view_reports(request.user):
        raise PermissionDenied
    started = time.perf_counter()
    summary = dashboard_summary(request.user)
    elapsed = int((time.perf_counter() - started) * 1000)
    logger.info("report.rendered dashboard %sms budget=%s", elapsed, QUERY_BUDGET)
    return render(
        request,
        "reporting/dashboard.html",
        {"summary": summary, "query_budget": QUERY_BUDGET, "elapsed_ms": elapsed},
    )


@login_required
def report_detail(request, report_key):
    if not can_view_reports(request.user):
        raise PermissionDenied
    if report_key not in REPORT_KEYS:
        raise Http404
    params = _params(request)
    try:
        page_size = parse_page_size(request.GET.get("page_size"))
    except ValidationError as exc:
        return render(
            request,
            "reporting/report.html",
            {
                "errors": exc.message_dict,
                "reports": REPORTS,
                "report_key": report_key,
                "report": {
                    "title": "Report",
                    "preset": "",
                    "rows": [],
                    "columns": [],
                    "money_fields": [],
                    "start": None,
                    "end": None,
                },
                "params": params,
                "chart": [],
                "page_obj": None,
                "can_export": False,
            },
            status=422,
        )
    started = time.perf_counter()
    report = build_report(request.user, report_key, params)
    page = detail_page(
        request.user,
        report_key,
        params,
        request.GET.get("page") or 1,
        page_size,
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    logger.info(
        "report.rendered %s %sms budget=%s",
        report_key,
        elapsed,
        QUERY_BUDGET,
    )
    chart = _chart(report)
    return render(
        request,
        "reporting/report.html",
        {
            "report": report,
            "reports": REPORTS,
            "report_key": report_key,
            "page_obj": page,
            "chart": chart,
            "can_export": can_export_reports(request.user),
            "elapsed_ms": elapsed,
            "query_budget": QUERY_BUDGET,
            "params": params,
        },
    )


@login_required
@require_POST
def report_export(request, report_key):
    if report_key not in REPORT_KEYS:
        raise Http404
    filters = {
        "start": request.POST.get("start", ""),
        "end": request.POST.get("end", ""),
    }
    try:
        report = export_report(
            actor=request.user,
            report_key=report_key,
            filters=filters,
            fields=request.POST.getlist("fields"),
            request_id=getattr(request, "request_id", ""),
        )
    except PermissionDenied:
        return render(request, "crm/forbidden.html", status=403)
    response = HttpResponse(report_csv(report), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{report_key}.csv"'
    return response
