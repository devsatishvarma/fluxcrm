from django.db import migrations

LEAD_STAGES = (
    ("NEW", "New"),
    ("CONTACTED", "Contacted"),
    ("MQL", "MQL"),
    ("DEMO_POC", "Demo/POC Scheduled"),
    ("SQL", "SQL"),
    ("NURTURING", "Nurturing"),
    ("UNQUALIFIED", "Unqualified"),
    ("ARCHIVED", "Archived"),
)
NURTURE_REASONS = (
    ("TIMING", "Timing not right"),
    ("BUDGET", "Budget not available"),
    ("MQL_NOT_SALES_READY", "Marketing-qualified but not sales-ready"),
    ("NO_RESPONSE", "Unable to re-engage"),
    ("FUTURE_EVALUATION", "Evaluating in a future period"),
    ("REACTIVATION", "Reactivation"),
    ("OTHER", "Other"),
)
DISQUALIFICATION_REASONS = (
    ("NO_BUDGET", "No Budget"),
    ("NO_TECHNICAL_FIT", "No Technical Fit"),
    ("WRONG_DECISION_MAKER", "Wrong Decision-Maker"),
    ("SECURITY_COMPLIANCE", "Security-Compliance Mismatch"),
    ("TIMING", "Timing"),
)
CURRENT_TOOLS = (
    ("MICROSOFT_365", "Microsoft 365"),
    ("AZURE", "Microsoft Azure"),
    ("AWS", "Amazon Web Services"),
    ("GOOGLE_CLOUD", "Google Cloud"),
    ("ON_PREMISES", "On-premises"),
    ("HYBRID", "Hybrid"),
    ("UNKNOWN", "Unknown"),
    ("OTHER", "Other"),
)
BUDGET_RANGES = (
    ("UNDER_25K", "Under $25,000"),
    ("25K_100K", "$25,000–$100,000"),
    ("100K_250K", "$100,000–$250,000"),
    ("250K_PLUS", "$250,000 or more"),
    ("UNKNOWN", "Unknown"),
)
BUYING_TIMELINES = (
    ("IMMEDIATE", "Immediate"),
    ("THIS_QUARTER", "This quarter"),
    ("NEXT_QUARTER", "Next quarter"),
    ("THIS_YEAR", "This year"),
    ("UNKNOWN", "Unknown"),
)
STAGE_MAP = {
    "SQL_READY": "SQL",
    "SQL_REACTIVATION": "NURTURING",
}
REASON_MAP = {
    "NO_AUTHORITY": "WRONG_DECISION_MAKER",
    "NO_FIT": "NO_TECHNICAL_FIT",
    "NO_NEED": "NO_TECHNICAL_FIT",
    "BAD_DATA": "NO_TECHNICAL_FIT",
    "DUPLICATE": "NO_TECHNICAL_FIT",
    "OUTSIDE_TERRITORY": "NO_TECHNICAL_FIT",
    "OTHER": "NO_TECHNICAL_FIT",
}


def _sync(picklist, list_key, rows):
    keep = set()
    for order, (key, label) in enumerate(rows, start=1):
        keep.add(key)
        row, _created = picklist.objects.get_or_create(
            list_key=list_key,
            key=key,
            defaults={"label": label, "order": order, "active": True},
        )
        row.label = label
        row.order = order
        row.active = True
        row.save(update_fields=["label", "order", "active"])
    picklist.objects.filter(list_key=list_key).exclude(key__in=keep).update(
        active=False
    )


def _rewrite_json(node):
    changed = False
    if isinstance(node, dict):
        stage = node.get("stage")
        if stage == "SQL_REACTIVATION" and not node.get("nurture_reason"):
            node["nurture_reason"] = "REACTIVATION"
            changed = True
        if stage in STAGE_MAP:
            node["stage"] = STAGE_MAP[stage]
            changed = True
        for field in ("from_stage", "to_stage"):
            if node.get(field) in STAGE_MAP:
                node[field] = STAGE_MAP[node[field]]
                changed = True
        reason = node.get("disqualification_reason")
        if reason in REASON_MAP:
            node["disqualification_reason"] = REASON_MAP[reason]
            changed = True
        for value in node.values():
            if _rewrite_json(value):
                changed = True
    elif isinstance(node, list):
        for item in node:
            if _rewrite_json(item):
                changed = True
    return changed


def apply_lead_stages(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    lead = apps.get_model("leads", "Lead")
    history = apps.get_model("core", "StageHistory")
    _sync(picklist, "LEAD_STAGE", LEAD_STAGES)
    _sync(picklist, "NURTURE_REASON", NURTURE_REASONS)
    _sync(picklist, "DISQUALIFICATION_REASON", DISQUALIFICATION_REASONS)
    _sync(picklist, "CURRENT_TOOLS", CURRENT_TOOLS)
    _sync(picklist, "BUDGET_RANGE", BUDGET_RANGES)
    _sync(picklist, "BUYING_TIMELINE", BUYING_TIMELINES)
    lead.objects.filter(stage="SQL_REACTIVATION", nurture_reason="").update(
        nurture_reason="REACTIVATION"
    )
    lead.objects.filter(stage="SQL_REACTIVATION").update(stage="NURTURING")
    lead.objects.filter(stage="SQL_READY").update(stage="SQL")
    for old, new in REASON_MAP.items():
        lead.objects.filter(disqualification_reason=old).update(
            disqualification_reason=new
        )
    for old, new in STAGE_MAP.items():
        history._base_manager.filter(object_type="lead", from_stage=old).update(
            from_stage=new
        )
        history._base_manager.filter(object_type="lead", to_stage=old).update(
            to_stage=new
        )
    import_row = apps.get_model("imports", "ImportRow")
    for row in import_row.objects.all().iterator():
        if _rewrite_json(row.before_json):
            row.save(update_fields=["before_json"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_industry_labels"),
        ("leads", "0008_lead_stage_fields"),
        ("imports", "0001_csv_batches"),
    ]

    operations = [
        migrations.RunPython(apply_lead_stages, migrations.RunPython.noop),
    ]
