"""Scoped report totals. Dates use the viewer's time zone and fiscal calendar."""

import csv
import io
import logging
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import Account, Contact
from activities.models import Activity, ActivityLink, Task
from activities.services import stale_days
from audit.models import AuditEvent
from core.access import activate_viewer_timezone, scoped
from core.display import format_money
from core.models import StageHistory
from core.policy import allows, deny, grant_for
from core.taxonomy import TAXONOMY
from core.workflow import OPEN_DEAL_STAGES
from identity.models import CompanySettings, User
from leads.models import Lead
from sales.models import Deal

logger = logging.getLogger(__name__)

QUERY_BUDGET = 30
AGE_BUCKETS = ("0–7 days", "8–30 days", "31–90 days", "91+ days")
REPORT_GROUPS = (
    (
        "Leads",
        (
            ("leads-by-stage", "Leads by stage"),
            ("leads-by-source", "Leads by source"),
            ("lead-aging", "Lead aging"),
            ("conversion", "Conversion"),
        ),
    ),
    (
        "Deals",
        (
            ("deals-by-stage", "Deals by stage"),
            ("deals-by-confidence", "Deals by confidence"),
            ("deals-by-age", "Deals by age"),
            ("deals-by-quarter", "Deals by quarter"),
            ("deals-by-owner", "Deals by sales owner"),
            ("deal-pipeline", "Deal pipeline"),
            ("forecast", "Forecast by quarter"),
            ("won-lost", "Won, lost, and hold"),
        ),
    ),
    (
        "Accounts",
        (
            ("account-pipeline", "Account pipeline"),
            ("contacts", "Contacts"),
        ),
    ),
    (
        "Activity",
        (("activities", "Activity per rep"),),
    ),
)
REPORTS = tuple(item for _title, items in REPORT_GROUPS for item in items)
REPORT_KEYS = {key for key, _label in REPORTS}
RECORD_COLUMNS = {
    "leads-by-stage": (
        "Leads",
        [
            ("Company", "company"),
            ("Lead name", "title"),
            ("Lead stage", "detail"),
        ],
    ),
    "leads-by-source": (
        "Leads",
        [
            ("Company", "company"),
            ("Lead name", "title"),
            ("Lead source", "detail"),
        ],
    ),
    "lead-aging": (
        "Leads",
        [
            ("Company", "company"),
            ("Lead name", "title"),
            ("Age and stage", "detail"),
        ],
    ),
    "conversion": (
        "Leads",
        [
            ("Company", "company"),
            ("Lead name", "title"),
            ("Result", "detail"),
        ],
    ),
    "deals-by-stage": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Deal stage", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "deals-by-confidence": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Deal confidence", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "deals-by-age": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Deal age", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "deals-by-quarter": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Expected close quarter", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "deals-by-owner": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Sales owner", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "deal-pipeline": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Deal stage", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "account-pipeline": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Deal stage", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "forecast": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Quarter and stage", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "won-lost": (
        "Deals",
        [
            ("Company", "company"),
            ("Deal title", "title"),
            ("Outcome and close date", "detail"),
            ("Amount", "amount"),
        ],
    ),
    "activities": (
        "Activities",
        [
            ("Company", "company"),
            ("Subject", "title"),
            ("Owner and type", "detail"),
        ],
    ),
    "contacts": (
        "Contacts",
        [
            ("Account", "company"),
            ("Contact name", "title"),
            ("Title", "detail"),
        ],
    ),
}


DEAL_PAGE_GROUPS = (
    ("Pipeline", ("deals-by-stage", "deals-by-confidence")),
    ("Timing", ("deals-by-age", "deals-by-quarter")),
    ("Ownership", ("deals-by-owner",)),
)
SQL_STAGES = {"SQL"}


def can_view_reports(user):
    return allows(user, "report", "R") or allows(user, "report", "A")


def can_export_reports(user):
    return allows(user, "report", "X") or allows(user, "report", "A")


def report_preset(user):
    scope = grant_for(user, "report").scope
    if scope == "ALL":
        return "Executive"
    if scope == "MANAGER_TREE":
        return "Manager"
    return "Rep"


def _zone(user):
    from zoneinfo import ZoneInfoNotFoundError

    activate_viewer_timezone(user)
    try:
        return ZoneInfo(getattr(user, "timezone", "") or "America/Los_Angeles")
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/Los_Angeles")


def fiscal_start_month():
    company = CompanySettings.objects.first()
    if company is None:
        return 1
    return company.fiscal_year_start_month or 1


def _shift_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def fiscal_year_containing(day, start_month):
    """Return the fiscal year start date and the last day of that year."""
    if day.month >= start_month:
        fiscal_year = day.year
    else:
        fiscal_year = day.year - 1
    start = date(fiscal_year, start_month, 1)
    return start, _shift_months(start, 12) - timedelta(days=1)


def quarter_containing(day, start_month):
    """Return the fiscal quarter start date and the next quarter's start."""
    if day.month >= start_month:
        fiscal_year = day.year
    else:
        fiscal_year = day.year - 1
    origin = date(fiscal_year, start_month, 1)
    elapsed = (day.year - origin.year) * 12 + day.month - origin.month
    start = _shift_months(origin, (elapsed // 3) * 3)
    return start, _shift_months(start, 3)


def quarter_label(day, start_month):
    start, _end = quarter_containing(day, start_month)
    if start.month >= start_month:
        year = start.year
    else:
        year = start.year - 1
    quarter = ((start.month - start_month) % 12) // 3 + 1
    return f"FY{year} Q{quarter}"


def local_today(user):
    return timezone.now().astimezone(_zone(user)).date()


def parse_bounds(user, params):
    """Inclusive local dates from the request. Blank means no date limit."""
    del user
    start = parse_date(str(params.get("start") or "")) if params else None
    end = parse_date(str(params.get("end") or "")) if params else None
    if start and end and end < start:
        start, end = end, start
    return start, end


def current_quarter(user):
    start, following = quarter_containing(local_today(user), fiscal_start_month())
    return start, following - timedelta(days=1)


def _aware_range(user, start, end):
    zone = _zone(user)
    start_dt = None if start is None else datetime.combine(start, time.min, tzinfo=zone)
    end_dt = None
    if end is not None:
        end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
    return start_dt, end_dt


def _apply_created(queryset, user, start, end):
    start_dt, end_dt = _aware_range(user, start, end)
    if start_dt is not None:
        queryset = queryset.filter(created_at__gte=start_dt)
    if end_dt is not None:
        queryset = queryset.filter(created_at__lt=end_dt)
    return queryset


def _money(value):
    return Decimal("0.00") if value is None else Decimal(value)


def _percent(part, whole):
    if not whole:
        return None
    return (Decimal(part) / Decimal(whole) * Decimal("100")).quantize(Decimal("1"))


def _share(part, whole):
    value = _percent(part, whole)
    if value is None:
        return "—"
    return f"{value}%"


def _label_map(list_key):
    return {key: label for key, label in TAXONOMY[list_key]}


def _key_order(list_key):
    return {key: index for index, (key, _label) in enumerate(TAXONOMY[list_key])}


def _deal_company(deal):
    if deal.account_id:
        return deal.account.name
    if deal.lead_id:
        return deal.lead.company_name
    if deal.converted_from_lead_id:
        return deal.converted_from_lead.company_name
    return "Unknown"


def _named_amounts(pairs):
    totals = {}
    order = []
    for name, amount in pairs:
        if name not in totals:
            order.append(name)
            totals[name] = Decimal("0.00")
        totals[name] += _money(amount)
    return ", ".join(f"{name} ({format_money(totals[name])})" for name in order)


def _named_counts(names):
    counts = {}
    order = []
    for name in names:
        if name not in counts:
            order.append(name)
            counts[name] = 0
        counts[name] += 1
    return ", ".join(
        name if counts[name] == 1 else f"{name} ({counts[name]})" for name in order
    )


def _deal_record(deal, detail):
    return {
        "company": _deal_company(deal),
        "title": deal.title,
        "detail": detail,
        "amount": _money(deal.amount),
    }


def _lead_record(lead, detail):
    return {
        "company": lead.company_name,
        "title": f"{lead.first_name} {lead.last_name}".strip(),
        "detail": detail,
        "amount": None,
    }


def _visible_deals(user):
    return scoped(Deal.objects.all(), user).select_related(
        "account", "lead", "converted_from_lead", "owner"
    )


def _median(values):
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return None
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def active_leads(user):
    return scoped(Lead.objects.all(), user).filter(converted_at__isnull=True)


def open_deals(user):
    return scoped(Deal.objects.all(), user).filter(stage__in=OPEN_DEAL_STAGES)


def _close_moment(deal, history, zone):
    moment = history.get(deal.pk) or deal.stage_entered_at
    if timezone.is_naive(moment):
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(zone)


def won_deals_with_close_dates(user):
    """Won deals dated by the close date on the deal, not the stage change."""
    deals = scoped(
        Deal.objects.filter(outcome="WON", actual_close_date__isnull=False),
        user,
    ).only(
        "id",
        "amount",
        "actual_close_date",
        "owner_id",
        "close_reason",
        "deal_type",
        "lead_id",
        "converted_from_lead_id",
    )
    return [(deal, deal.actual_close_date) for deal in deals]


def dashboard(user, params=None):
    """Summary for the viewer's report scope: Rep, Manager, or Executive."""
    start, end = current_quarter(user)
    leads = active_leads(user)
    deals = open_deals(user)
    totals = deals.aggregate(total=Sum("amount"), deals=Count("pk"))
    pipeline = _money(totals["total"])
    now = timezone.now()
    overdue = (
        scoped(Task.objects.filter(status=Task.Status.OPEN), user)
        .annotate(effective_due=Coalesce("snooze_until", "due_at"))
        .filter(effective_due__lt=now)
        .count()
    )
    cutoff = now - timedelta(days=stale_days("lead"))
    lead_type = ContentType.objects.get_for_model(Lead)
    latest = (
        Activity.objects.filter(
            links__content_type=lead_type,
            links__object_id=OuterRef("pk"),
        )
        .order_by("-occurred_at")
        .values("occurred_at")[:1]
    )
    stale = (
        leads.annotate(last_activity=Subquery(latest))
        .filter(Q(last_activity__lt=cutoff) | Q(last_activity__isnull=True))
        .count()
    )
    closed = won_deals_with_close_dates(user)
    wins = sum(
        (
            _money(deal.amount)
            for deal, closed_on in closed
            if start <= closed_on <= end
        ),
        Decimal("0.00"),
    )
    previous_start = _shift_months(start, -3)
    previous_end = start - timedelta(days=1)
    prior_wins = sum(
        (
            _money(deal.amount)
            for deal, closed_on in closed
            if previous_start <= closed_on <= previous_end
        ),
        Decimal("0.00"),
    )
    year_start, year_end = fiscal_year_containing(
        local_today(user), fiscal_start_month()
    )
    prior_year_start = _shift_months(year_start, -12)
    prior_year_end = year_start - timedelta(days=1)
    year_wins = sum(
        (
            _money(deal.amount)
            for deal, closed_on in closed
            if year_start <= closed_on <= year_end
        ),
        Decimal("0.00"),
    )
    prior_year_wins = sum(
        (
            _money(deal.amount)
            for deal, closed_on in closed
            if prior_year_start <= closed_on <= prior_year_end
        ),
        Decimal("0.00"),
    )
    return {
        "preset": report_preset(user),
        "start": start,
        "end": end,
        "year_start": year_start,
        "year_end": year_end,
        "open_leads": leads.count(),
        "open_deals": totals["deals"],
        "open_pipeline": pipeline,
        "overdue_tasks": overdue,
        "stale_leads": stale,
        "period_wins": wins,
        "prior_wins": prior_wins,
        "prior_change": _percent(wins - prior_wins, prior_wins),
        "year_wins": year_wins,
        "prior_year_wins": prior_year_wins,
        "year_change": _percent(year_wins - prior_year_wins, prior_year_wins),
        "reports": REPORTS,
        "report_groups": [
            {"title": title, "reports": reports} for title, reports in REPORT_GROUPS
        ],
    }


def build_report(user, key, params=None):
    if key not in REPORT_KEYS:
        raise KeyError(key)
    params = params or {}
    start, end = parse_bounds(user, params)
    builder = {
        "leads-by-stage": _leads_by_stage,
        "leads-by-source": _leads_by_source,
        "lead-aging": _lead_aging,
        "deal-pipeline": _deal_pipeline,
        "deals-by-stage": _deals_by_stage,
        "deals-by-confidence": _deals_by_confidence,
        "deals-by-age": _deals_by_age,
        "deals-by-quarter": _deals_by_quarter,
        "deals-by-owner": _deals_by_owner,
        "account-pipeline": _account_pipeline,
        "forecast": _forecast,
        "won-lost": _won_lost,
        "conversion": _conversion,
        "activities": _activities,
        "contacts": _contacts,
    }[key]
    report = builder(user, start, end)
    heading, record_columns = RECORD_COLUMNS[key]
    report["key"] = key
    report["start"] = start
    report["end"] = end
    report["preset"] = report_preset(user)
    report["record_heading"] = heading
    report["record_columns"] = record_columns
    return report


def _lead_rows(user, start, end):
    return _apply_created(active_leads(user), user, start, end).only(
        "company_name", "first_name", "last_name", "stage", "source", "created_at"
    )


def _leads_by_stage(user, start, end):
    labels = _label_map("LEAD_STAGE")
    order = _key_order("LEAD_STAGE")
    buckets = {}
    records = []
    for lead in _lead_rows(user, start, end):
        bucket = buckets.setdefault(lead.stage, {"count": 0, "names": []})
        bucket["count"] += 1
        bucket["names"].append(lead.company_name)
        records.append(_lead_record(lead, labels.get(lead.stage, lead.stage)))
    total = sum(bucket["count"] for bucket in buckets.values())
    rows = [
        {
            "label": labels.get(stage, stage),
            "companies": _named_counts(values["names"]),
            "count": values["count"],
            "share": _share(values["count"], total),
        }
        for stage, values in sorted(
            buckets.items(), key=lambda item: order.get(item[0], 99)
        )
    ]
    return {
        "title": "Leads by stage",
        "columns": [
            ("Lead stage", "label"),
            ("Companies", "companies"),
            ("Leads", "count"),
            ("Share", "share"),
        ],
        "money_fields": [],
        "chart_field": "count",
        "rows": rows,
        "records": records,
        "total": total,
    }


def _leads_by_source(user, start, end):
    labels = _label_map("LEAD_SOURCE")
    buckets = {}
    records = []
    for lead in _lead_rows(user, start, end):
        bucket = buckets.setdefault(lead.source or "", {"count": 0, "names": []})
        bucket["count"] += 1
        bucket["names"].append(lead.company_name)
        source_label = labels.get(lead.source, lead.source or "Unknown")
        records.append(_lead_record(lead, source_label))
    total = sum(bucket["count"] for bucket in buckets.values())
    rows = [
        {
            "label": labels.get(source, source or "Unknown"),
            "companies": _named_counts(values["names"]),
            "count": values["count"],
            "share": _share(values["count"], total),
        }
        for source, values in sorted(buckets.items(), key=lambda item: item[0])
    ]
    return {
        "title": "Leads by source",
        "columns": [
            ("Lead source", "label"),
            ("Companies", "companies"),
            ("Leads", "count"),
            ("Share", "share"),
        ],
        "money_fields": [],
        "chart_field": "count",
        "rows": rows,
        "records": records,
        "total": total,
    }


def _age_bucket(age):
    if age <= 7:
        return "0–7 days"
    if age <= 30:
        return "8–30 days"
    if age <= 90:
        return "31–90 days"
    return "91+ days"


def _lead_aging(user, start, end):
    leads = list(_lead_rows(user, start, end))
    today = local_today(user)
    labels = _label_map("LEAD_STAGE")
    ages = []
    names = {label: [] for label in AGE_BUCKETS}
    records = []
    for lead in leads:
        age = (today - lead.created_at.astimezone(_zone(user)).date()).days
        age = max(age, 0)
        ages.append(age)
        bucket = _age_bucket(age)
        names[bucket].append(lead.company_name)
        records.append(
            _lead_record(lead, f"{bucket} · {labels.get(lead.stage, lead.stage)}")
        )
    return {
        "title": "Lead aging",
        "columns": [
            ("Lead age", "label"),
            ("Companies", "companies"),
            ("Leads", "count"),
        ],
        "money_fields": [],
        "chart_field": "count",
        "rows": [
            {
                "label": label,
                "companies": _named_counts(names[label]),
                "count": len(names[label]),
            }
            for label in AGE_BUCKETS
            if names[label]
        ],
        "records": records,
        "median_days": _median(ages),
        "total": len(leads),
    }


def deal_report_groups(user):
    """Deal reports for the Deals page, grouped by what the reader is asking."""
    groups = []
    for title, keys in DEAL_PAGE_GROUPS:
        groups.append(
            {"title": title, "reports": [build_report(user, key) for key in keys]}
        )
    return groups


def _report_deals(user, start, end):
    return _apply_created(_visible_deals(user), user, start, end)


def _weighted(amount, probability):
    return amount * _money(probability) / Decimal("100")


def _deals_by_stage(user, start, end):
    labels = _label_map("DEAL_STAGE")
    order = _key_order("DEAL_STAGE")
    buckets = {}
    records = []
    for deal in _report_deals(user, start, end):
        bucket = buckets.setdefault(
            deal.stage,
            {
                "count": 0,
                "amount": Decimal("0.00"),
                "weighted": Decimal("0.00"),
                "companies": [],
            },
        )
        amount = _money(deal.amount)
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["weighted"] += _weighted(amount, deal.probability)
        bucket["companies"].append((_deal_company(deal), amount))
        records.append(_deal_record(deal, labels.get(deal.stage, deal.stage)))
    rows = [
        {
            "label": labels.get(stage, stage),
            "companies": _named_amounts(values["companies"]),
            "count": values["count"],
            "amount": values["amount"],
            "weighted": values["weighted"],
        }
        for stage, values in sorted(
            buckets.items(), key=lambda item: order.get(item[0], 99)
        )
    ]
    return {
        "title": "Deals by stage",
        "note": "Every deal you can see, including closed deals.",
        "columns": [
            ("Deal stage", "label"),
            ("Companies", "companies"),
            ("Deals", "count"),
            ("Amount", "amount"),
            ("Weighted", "weighted"),
        ],
        "money_fields": ["amount", "weighted"],
        "chart_field": "amount",
        "rows": rows,
        "records": records,
        "total": sum((row["count"] for row in rows), 0),
    }


def _deals_by_confidence(user, start, end):
    labels = _label_map("DEAL_CONFIDENCE")
    order = ("HIGH", "MEDIUM", "LOW")
    buckets = {
        key: {
            "count": 0,
            "amount": Decimal("0.00"),
            "weighted": Decimal("0.00"),
            "companies": [],
        }
        for key in order
    }
    records = []
    for deal in _report_deals(user, start, end):
        key = deal.confidence if deal.confidence in buckets else "LOW"
        bucket = buckets[key]
        amount = _money(deal.amount)
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["weighted"] += _weighted(amount, deal.probability)
        bucket["companies"].append((_deal_company(deal), amount))
        records.append(_deal_record(deal, labels.get(key, key)))
    return {
        "title": "Deals by confidence",
        "note": (
            "High is a win probability of 80% or more. Medium is 40% up to 80%. "
            "Low is under 40%. Confidence follows the probability; it is not edited."
        ),
        "columns": [
            ("Deal confidence", "label"),
            ("Companies", "companies"),
            ("Deals", "count"),
            ("Amount", "amount"),
            ("Weighted", "weighted"),
        ],
        "money_fields": ["amount", "weighted"],
        "chart_field": "amount",
        "rows": [
            {
                "label": labels.get(key, key),
                "companies": _named_amounts(buckets[key]["companies"]),
                "count": buckets[key]["count"],
                "amount": buckets[key]["amount"],
                "weighted": buckets[key]["weighted"],
            }
            for key in order
        ],
        "records": records,
        "total": sum(buckets[key]["count"] for key in order),
    }


def _deals_by_age(user, start, end):
    today = local_today(user)
    zone = _zone(user)
    names = {label: [] for label in AGE_BUCKETS}
    amounts = {label: Decimal("0.00") for label in AGE_BUCKETS}
    ages = []
    records = []
    for deal in _report_deals(user, start, end):
        age = (today - deal.created_at.astimezone(zone).date()).days
        age = max(age, 0)
        ages.append(age)
        bucket = _age_bucket(age)
        amount = _money(deal.amount)
        names[bucket].append(_deal_company(deal))
        amounts[bucket] += amount
        records.append(_deal_record(deal, f"{bucket} · {age} days"))
    return {
        "title": "Deals by age",
        "note": "Age is the number of days since the deal was added.",
        "columns": [
            ("Deal age", "label"),
            ("Companies", "companies"),
            ("Deals", "count"),
            ("Amount", "amount"),
        ],
        "money_fields": ["amount"],
        "chart_field": "count",
        "rows": [
            {
                "label": label,
                "companies": _named_counts(names[label]),
                "count": len(names[label]),
                "amount": amounts[label],
            }
            for label in AGE_BUCKETS
            if names[label]
        ],
        "records": records,
        "median_days": _median(ages),
        "total": len(ages),
    }


def _deals_by_quarter(user, start, end):
    start_month = fiscal_start_month()
    buckets = {}
    records = []
    for deal in _report_deals(user, start, end):
        closed_on = deal.expected_close_date
        if closed_on is None:
            label = "Unscheduled"
            sort_on = date.max
        else:
            label = quarter_label(closed_on, start_month)
            sort_on = quarter_containing(closed_on, start_month)[0]
        bucket = buckets.setdefault(
            label,
            {
                "sort": sort_on,
                "count": 0,
                "amount": Decimal("0.00"),
                "companies": [],
            },
        )
        amount = _money(deal.amount)
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["companies"].append((_deal_company(deal), amount))
        records.append(_deal_record(deal, label))
    rows = [
        {
            "label": label,
            "companies": _named_amounts(values["companies"]),
            "count": values["count"],
            "amount": values["amount"],
        }
        for label, values in sorted(
            buckets.items(), key=lambda item: (item[1]["sort"], item[0])
        )
    ]
    return {
        "title": "Deals by quarter",
        "note": (
            "Each row is the fiscal quarter of the expected close date. "
            "Deals with no expected close date are Unscheduled."
        ),
        "columns": [
            ("Expected close quarter", "label"),
            ("Companies", "companies"),
            ("Deals", "count"),
            ("Amount", "amount"),
        ],
        "money_fields": ["amount"],
        "chart_field": "amount",
        "rows": rows,
        "records": records,
        "total": sum((row["count"] for row in rows), 0),
    }


def _deals_by_owner(user, start, end):
    buckets = {}
    records = []
    for deal in _report_deals(user, start, end):
        name = deal.owner.display_name or "—"
        bucket = buckets.setdefault(
            name,
            {"count": 0, "amount": Decimal("0.00"), "companies": []},
        )
        amount = _money(deal.amount)
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["companies"].append((_deal_company(deal), amount))
        records.append(_deal_record(deal, name))
    rows = [
        {
            "label": name,
            "companies": _named_amounts(values["companies"]),
            "count": values["count"],
            "amount": values["amount"],
        }
        for name, values in sorted(
            buckets.items(), key=lambda item: (-item[1]["amount"], item[0].lower())
        )
    ]
    return {
        "title": "Deals by sales owner",
        "note": "Each row is the person who owns those deals.",
        "columns": [
            ("Sales owner", "label"),
            ("Companies", "companies"),
            ("Deals", "count"),
            ("Amount", "amount"),
        ],
        "money_fields": ["amount"],
        "chart_field": "amount",
        "rows": rows,
        "records": records,
        "total": sum((row["count"] for row in rows), 0),
    }


def _deal_pipeline(user, start, end):
    labels = _label_map("DEAL_STAGE")
    order = _key_order("DEAL_STAGE")
    buckets = {}
    records = []
    deals = _apply_created(_visible_deals(user), user, start, end).filter(
        stage__in=OPEN_DEAL_STAGES
    )
    for deal in deals:
        bucket = buckets.setdefault(
            deal.stage,
            {
                "count": 0,
                "amount": Decimal("0.00"),
                "weighted": Decimal("0.00"),
                "companies": [],
            },
        )
        amount = _money(deal.amount)
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["weighted"] += amount * _money(deal.probability) / Decimal("100")
        bucket["companies"].append((_deal_company(deal), amount))
        records.append(_deal_record(deal, labels.get(deal.stage, deal.stage)))
    rows = []
    ordered = sorted(buckets.items(), key=lambda item: order.get(item[0], 99))
    for stage, values in ordered:
        rows.append(
            {
                "label": labels.get(stage, stage),
                "companies": _named_amounts(values["companies"]),
                "count": values["count"],
                "amount": values["amount"],
                "weighted": values["weighted"],
            }
        )
    return {
        "title": "Deal pipeline",
        "columns": [
            ("Deal stage", "label"),
            ("Companies", "companies"),
            ("Deals", "count"),
            ("Amount", "amount"),
            ("Weighted", "weighted"),
        ],
        "money_fields": ["amount", "weighted"],
        "chart_field": "amount",
        "rows": rows,
        "records": records,
        "total": sum((row["amount"] for row in rows), Decimal("0.00")),
    }


def account_rollups(user):
    """Own open amount and a parent rollup that counts each deal once."""
    accounts = list(scoped(Account.objects.all(), user).only("id", "name", "parent_id"))
    grouped = (
        open_deals(user)
        .filter(account__isnull=False)
        .values("account_id")
        .annotate(total=Sum(Coalesce("amount", Decimal("0.00"))))
    )
    own = {row["account_id"]: _money(row["total"]) for row in grouped}
    children = defaultdict(list)
    for account in accounts:
        if account.parent_id:
            children[account.parent_id].append(account.pk)

    def rollup(account_id, seen):
        if account_id in seen:
            return Decimal("0.00")
        seen.add(account_id)
        total = own.get(account_id, Decimal("0.00"))
        for child_id in children.get(account_id, ()):
            total += rollup(child_id, seen)
        return total

    rows = []
    for account in sorted(accounts, key=lambda item: item.name.lower()):
        rows.append(
            {
                "label": account.name,
                "own": own.get(account.pk, Decimal("0.00")),
                "rollup": rollup(account.pk, set()),
            }
        )
    return rows, sum(own.values(), Decimal("0.00"))


def _account_pipeline(user, start, end):
    del start, end
    labels = _label_map("DEAL_STAGE")
    rows, company_total = account_rollups(user)
    records = [
        _deal_record(deal, labels.get(deal.stage, deal.stage))
        for deal in open_deals(user)
        .filter(account__isnull=False)
        .select_related("account", "lead", "converted_from_lead")
    ]
    return {
        "title": "Account pipeline",
        "note": (
            "Each account row is that account. With descendants adds child "
            "accounts once. The company total is the sum of own amounts. "
            "Deals still on a lead, with no account yet, stay on Deal pipeline."
        ),
        "columns": [
            ("Account", "label"),
            ("Own open amount", "own"),
            ("With descendants", "rollup"),
        ],
        "money_fields": ["own", "rollup"],
        "chart_field": "own",
        "rows": rows,
        "records": records,
        "total": company_total,
    }


def _forecast(user, start, end):
    start_month = fiscal_start_month()
    quarter_start, quarter_end = current_quarter(user)
    labels = _label_map("DEAL_STAGE")
    buckets = {}
    records = []
    for deal in _visible_deals(user).filter(stage__in=OPEN_DEAL_STAGES):
        closed_on = deal.expected_close_date
        if start or end:
            if closed_on is None or (start and closed_on < start):
                continue
            if end and closed_on > end:
                continue
        if closed_on is None:
            label = "Unscheduled"
            sort_on = date.max
        else:
            label = quarter_label(closed_on, start_month)
            sort_on = quarter_containing(closed_on, start_month)[0]
        bucket = buckets.setdefault(
            label,
            {
                "sort": sort_on,
                "commit": Decimal("0.00"),
                "weighted": Decimal("0.00"),
                "best": Decimal("0.00"),
                "companies": [],
            },
        )
        amount = _money(deal.amount)
        weighted = amount * _money(deal.probability) / Decimal("100")
        bucket["best"] += amount
        bucket["weighted"] += weighted
        if deal.stage == "CLOSING":
            bucket["commit"] += amount
        bucket["companies"].append((_deal_company(deal), amount))
        stage_label = labels.get(deal.stage, deal.stage)
        records.append(_deal_record(deal, f"{label} · {stage_label}"))
    rows = []
    ordered = sorted(buckets.items(), key=lambda item: (item[1]["sort"], item[0]))
    for label, values in ordered:
        rows.append(
            {
                "label": label,
                "companies": _named_amounts(values["companies"]),
                "commit": values["commit"],
                "weighted": values["weighted"],
                "best": values["best"],
            }
        )
    current = quarter_label(quarter_start, start_month)
    return {
        "title": "Forecast by quarter",
        "note": (
            "Companies are grouped by the quarter the deal is expected to close. "
            f"The current fiscal quarter is {current}, "
            f"{quarter_start.strftime('%m-%d-%Y')} through "
            f"{quarter_end.strftime('%m-%d-%Y')}. "
            "Leave the dates blank to include every open deal. "
            "Deals with no expected close date appear as Unscheduled. "
            "Commit is the Closing stage."
        ),
        "columns": [
            ("Expected close quarter", "label"),
            ("Companies", "companies"),
            ("Commit", "commit"),
            ("Weighted", "weighted"),
            ("Best case", "best"),
        ],
        "money_fields": ["commit", "weighted", "best"],
        "chart_series": [
            {"label": "Commit", "field": "commit"},
            {"label": "Weighted", "field": "weighted"},
            {"label": "Best case", "field": "best"},
        ],
        "rows": rows,
        "records": records,
        "total": sum((row["best"] for row in rows), Decimal("0.00")),
    }


def _won_lost(user, start, end):
    outcome_labels = {"WON": "Won", "LOST": "Lost", "HOLD": "Hold"}
    deals = _visible_deals(user).filter(outcome__in=outcome_labels)
    zone = _zone(user)
    deal_list = list(deals)
    history = {}
    if deal_list:
        for row in StageHistory.objects.filter(
            object_type="deal",
            object_id__in=[deal.pk for deal in deal_list],
            to_stage__in=["CLOSED_WON", "CLOSED_LOST", "CLOSED_HOLD"],
        ).order_by("changed_at"):
            history[row.object_id] = row.changed_at
    totals = {
        key: {"count": 0, "amount": Decimal("0.00"), "companies": []}
        for key in outcome_labels
    }
    records = []
    for deal in deal_list:
        if deal.outcome == "WON":
            closed_on = deal.actual_close_date
        else:
            closed_on = _close_moment(deal, history, zone).date()
        if closed_on is None:
            if start or end:
                continue
        elif start and closed_on < start:
            continue
        elif end and closed_on > end:
            continue
        closed_label = (
            "No close date" if closed_on is None else closed_on.strftime("%m-%d-%Y")
        )
        bucket = totals[deal.outcome]
        amount = _money(deal.amount)
        bucket["count"] += 1
        bucket["amount"] += amount
        bucket["companies"].append((_deal_company(deal), amount))
        records.append(
            _deal_record(
                deal,
                f"{outcome_labels[deal.outcome]} · {closed_label}",
            )
        )
    return {
        "title": "Won, lost, and hold",
        "columns": [
            ("Deal outcome", "label"),
            ("Companies", "companies"),
            ("Deals", "count"),
            ("Amount", "amount"),
        ],
        "money_fields": ["amount"],
        "chart_field": "amount",
        "rows": [
            {
                "label": outcome_labels[key],
                "companies": _named_amounts(values["companies"]),
                "count": values["count"],
                "amount": values["amount"],
            }
            for key, values in totals.items()
        ],
        "records": records,
        "total": totals["WON"]["amount"],
    }


def _conversion(user, start, end):
    labels = _label_map("LEAD_STAGE")
    cohort = list(
        _apply_created(scoped(Lead.objects.all(), user), user, start, end).only(
            "id", "stage", "company_name", "first_name", "last_name"
        )
    )
    eligible = len(cohort)
    ids = [lead.pk for lead in cohort]
    reached = set(
        StageHistory.objects.filter(
            object_type="lead",
            object_id__in=ids,
            to_stage="SQL",
        ).values_list("object_id", flat=True)
    )
    reached.update(lead.pk for lead in cohort if lead.stage in SQL_STAGES)
    won_leads = set(
        scoped(Deal.objects.filter(outcome="WON"), user)
        .filter(Q(lead_id__in=reached) | Q(converted_from_lead_id__in=reached))
        .values_list("lead_id", "converted_from_lead_id")
    )
    won_ids = {lead_id for pair in won_leads for lead_id in pair if lead_id in reached}
    sql_count = len(reached)
    won_count = len(won_ids)
    won_amount = _money(
        scoped(Deal.objects.filter(outcome="WON"), user)
        .filter(Q(lead_id__in=won_ids) | Q(converted_from_lead_id__in=won_ids))
        .aggregate(total=Sum("amount"))["total"]
    )
    average = None if not won_count else won_amount / won_count
    records = []
    for lead in cohort:
        if lead.pk in won_ids:
            detail = "Won"
        elif lead.pk in reached:
            detail = "Reached SQL"
        else:
            detail = labels.get(lead.stage, lead.stage)
        records.append(_lead_record(lead, detail))
    return {
        "title": "Conversion",
        "columns": [("Measure", "label"), ("Value", "count")],
        "money_fields": [],
        "chart_field": "count",
        "rows": [
            {"label": "Leads created", "count": eligible},
            {"label": "Reached SQL", "count": sql_count},
            {
                "label": "Lead to SQL %",
                "count": _share(sql_count, eligible),
                "chart": False,
            },
            {"label": "SQL won", "count": won_count},
            {
                "label": "SQL to won %",
                "count": _share(won_count, sql_count),
                "chart": False,
            },
            {
                "label": "Average won amount",
                "count": "—" if average is None else format_money(average),
                "chart": False,
            },
        ],
        "records": records,
        "total": eligible,
        "sql_count": sql_count,
        "won_count": won_count,
        "average_won": average,
    }


def _activity_companies(activity_ids):
    links = list(ActivityLink.objects.filter(activity_id__in=activity_ids))
    grouped = defaultdict(list)
    for link in links:
        grouped[link.content_type_id].append(link.object_id)
    names = {}
    for content_type_id, object_ids in grouped.items():
        content_type = ContentType.objects.get_for_id(content_type_id)
        model = content_type.model_class()
        found = {}
        if model is Lead:
            found = {
                lead.pk: lead.company_name
                for lead in Lead.objects.filter(pk__in=object_ids).only("company_name")
            }
        elif model is Account:
            found = {
                account.pk: account.name
                for account in Account.objects.filter(pk__in=object_ids).only("name")
            }
        elif model is Contact:
            found = {
                contact.pk: contact.account.name
                for contact in Contact.objects.filter(pk__in=object_ids).select_related(
                    "account"
                )
            }
        elif model is Deal:
            found = {
                deal.pk: _deal_company(deal)
                for deal in Deal.objects.filter(pk__in=object_ids).select_related(
                    "account", "lead", "converted_from_lead"
                )
            }
        for object_id, name in found.items():
            names[(content_type_id, object_id)] = name
    by_activity = defaultdict(list)
    for link in links:
        name = names.get((link.content_type_id, link.object_id))
        if name and name not in by_activity[link.activity_id]:
            by_activity[link.activity_id].append(name)
    return by_activity


def _activities(user, start, end):
    queryset = scoped(Activity.objects.filter(source="MANUAL"), user)
    start_dt, end_dt = _aware_range(user, start, end)
    if start_dt is not None:
        queryset = queryset.filter(occurred_at__gte=start_dt)
    if end_dt is not None:
        queryset = queryset.filter(occurred_at__lt=end_dt)
    activities = list(queryset.order_by("-occurred_at", "pk"))
    companies = _activity_companies([activity.pk for activity in activities])
    type_labels = dict(Activity.Type.choices)
    owner_ids = {activity.owner_id for activity in activities}
    names = {
        person.pk: person.display_name
        for person in User.objects.filter(pk__in=owner_ids)
    }
    buckets = {}
    records = []
    for activity in activities:
        type_label = type_labels.get(activity.activity_type, activity.activity_type)
        company_names = companies.get(activity.pk, [])
        key = (activity.owner_id, activity.activity_type)
        bucket = buckets.setdefault(key, {"count": 0, "names": []})
        bucket["count"] += 1
        bucket["names"].extend(company_names)
        records.append(
            {
                "company": ", ".join(company_names) or "—",
                "title": activity.subject,
                "detail": f"{names.get(activity.owner_id, 'Unknown')} · {type_label}",
                "amount": None,
            }
        )
    rows = [
        {
            "label": names.get(owner_id, "Unknown"),
            "activity_type": type_labels.get(activity_type, activity_type),
            "companies": _named_counts(values["names"]),
            "count": values["count"],
        }
        for (owner_id, activity_type), values in buckets.items()
    ]
    rows.sort(key=lambda row: (row["label"], row["activity_type"]))
    return {
        "title": "Activity per rep",
        "columns": [
            ("Owner", "label"),
            ("Activity type", "activity_type"),
            ("Companies", "companies"),
            ("Activities", "count"),
        ],
        "money_fields": [],
        "chart_field": "count",
        "rows": rows,
        "records": records,
        "total": len(activities),
    }


def _contacts(user, start, end):
    queryset = scoped(
        Contact.objects.select_related("account", "owner"),
        user,
    )
    contacts = list(
        _apply_created(queryset, user, start, end).order_by(
            "account__name", "last_name", "first_name"
        )
    )
    buckets = {}
    records = []
    for contact in contacts:
        account_name = contact.account.name if contact.account_id else "No account"
        bucket = buckets.setdefault(account_name, {"count": 0, "primary": ""})
        bucket["count"] += 1
        person = f"{contact.first_name} {contact.last_name}".strip()
        if contact.is_primary:
            bucket["primary"] = person
        detail = contact.title or contact.email or "—"
        records.append(
            {
                "company": account_name,
                "title": person,
                "detail": detail,
                "amount": None,
            }
        )
    rows = [
        {
            "label": name,
            "primary": values["primary"] or "—",
            "count": values["count"],
        }
        for name, values in sorted(buckets.items())
    ]
    return {
        "title": "Contacts",
        "note": (
            "Each row is an account. The list below names the people "
            "at those accounts."
        ),
        "columns": [
            ("Account", "label"),
            ("Primary contact", "primary"),
            ("Contacts", "count"),
        ],
        "money_fields": [],
        "chart_field": "count",
        "rows": rows,
        "records": records,
        "total": len(contacts),
    }


def _csv_cell(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def report_csv(report):
    """UTF-8 CSV of the report table, then the records behind it."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    columns = report.get("columns") or []
    money = set(report.get("money_fields") or [])
    writer.writerow([label for label, _key in columns])
    for row in report.get("rows") or []:
        cells = []
        for _label, key in columns:
            value = row.get(key, "")
            if key in money and value not in ("", None):
                value = format_money(value)
            cells.append(_csv_cell(value))
        writer.writerow(cells)
    records = report.get("records") or []
    record_columns = report.get("record_columns") or []
    if records and record_columns:
        writer.writerow([])
        writer.writerow([label for label, _key in record_columns])
        for item in records:
            cells = []
            for _label, key in record_columns:
                value = item.get(key)
                if key == "amount":
                    value = "" if value is None else format_money(value)
                cells.append(_csv_cell(value))
            writer.writerow(cells)
    return buffer.getvalue()


def detail_page(user, key, params, page, page_size):
    report = build_report(user, key, params)
    paginator = Paginator(report.get("records") or [], page_size)
    return paginator.get_page(page)


def export_report(*, actor, report_key, filters, fields, request_id=""):
    if not can_export_reports(actor):
        deny(actor, "report", "X", object_id=report_key, reason="missing_grant")
    report = build_report(actor, report_key, filters)
    clean_filters = {
        "start": None if report["start"] is None else report["start"].isoformat(),
        "end": None if report["end"] is None else report["end"].isoformat(),
    }
    clean_fields = [key for _label, key in report["columns"]]
    del fields
    AuditEvent.objects.create(
        actor=actor,
        action="report.exported",
        object_type="report",
        object_id=report_key,
        before_json=None,
        after_json={
            "report_key": report_key,
            "filters": clean_filters,
            "fields": clean_fields,
            "row_count": len(report["rows"]),
        },
        request_id=request_id,
        source="web",
    )
    logger.info(
        "report.exported %s rows=%s",
        report_key,
        len(report["rows"]),
    )
    return report
