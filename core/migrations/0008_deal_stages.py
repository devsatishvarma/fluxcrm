from django.db import migrations

DEAL_STAGES = (
    ("NEW", "New"),
    ("DISCOVERY", "Discovery"),
    ("QUALIFIED", "Qualified"),
    ("TECHNICAL_EVALUATION", "Technical Evaluation"),
    ("PROPOSAL", "Proposal"),
    ("NEGOTIATION", "Negotiation"),
    ("CLOSING", "Closing"),
    ("CLOSED_WON", "Closed Won"),
    ("CLOSED_LOST", "Closed Lost"),
    ("CLOSED_HOLD", "Closed Hold"),
)
LOST_REASONS = (
    ("PRICE", "Price"),
    ("COMPETITOR", "Competitor"),
    ("NO_TECHNICAL_FIT", "No Technical Fit"),
    ("TIMING", "Timing"),
    ("LOST_TO_INTERNAL_BUILD", "Lost to Internal Build"),
)
# Keys that only existed on Closed Lost.
LOST_REASON_MAP = {
    "REQUIREMENTS_GAP": "NO_TECHNICAL_FIT",
    "INTERNAL_CANCELLED": "LOST_TO_INTERNAL_BUILD",
    "NO_DECISION": "TIMING",
    "RELATIONSHIP": "COMPETITOR",
}
# Shared with Closed Hold, so only Closed Lost rows are rewritten.
LOST_ONLY_REASON_MAP = {
    "BUDGET": "PRICE",
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


def _map_stage(value):
    if value == "DISCOVERY":
        return "TECHNICAL_EVALUATION"
    if value == "CONTACTED":
        return "DISCOVERY"
    return value


def _rewrite_json(node):
    changed = False
    if isinstance(node, dict):
        if "deal_type" in node:
            stage = node.get("stage")
            mapped = _map_stage(stage)
            if mapped != stage:
                node["stage"] = mapped
                changed = True
            reason = node.get("close_reason")
            if reason in LOST_REASON_MAP:
                node["close_reason"] = LOST_REASON_MAP[reason]
                changed = True
            elif node.get("stage") == "CLOSED_LOST" and reason in LOST_ONLY_REASON_MAP:
                node["close_reason"] = LOST_ONLY_REASON_MAP[reason]
                changed = True
        for value in node.values():
            if _rewrite_json(value):
                changed = True
    elif isinstance(node, list):
        for item in node:
            if _rewrite_json(item):
                changed = True
    return changed


def apply_deal_stages(apps, schema_editor):
    picklist = apps.get_model("core", "PicklistValue")
    deal = apps.get_model("sales", "Deal")
    history = apps.get_model("core", "StageHistory")
    _sync(picklist, "DEAL_STAGE", DEAL_STAGES)
    _sync(picklist, "CLOSED_LOST_REASON", LOST_REASONS)
    deal.objects.filter(stage="DISCOVERY").update(stage="TECHNICAL_EVALUATION")
    deal.objects.filter(stage="CONTACTED").update(stage="DISCOVERY")
    for old, new in LOST_REASON_MAP.items():
        deal.objects.filter(close_reason=old).update(close_reason=new)
    for old, new in LOST_ONLY_REASON_MAP.items():
        deal.objects.filter(stage="CLOSED_LOST", close_reason=old).update(
            close_reason=new
        )
    for old, new in (
        ("DISCOVERY", "TECHNICAL_EVALUATION"),
        ("CONTACTED", "DISCOVERY"),
    ):
        history._base_manager.filter(object_type="deal", from_stage=old).update(
            from_stage=new
        )
        history._base_manager.filter(object_type="deal", to_stage=old).update(
            to_stage=new
        )
    import_row = apps.get_model("imports", "ImportRow")
    for row in import_row.objects.all().iterator():
        if _rewrite_json(row.before_json):
            row.save(update_fields=["before_json"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_lead_stages"),
        ("sales", "0008_deal_evaluation_fields"),
        ("imports", "0001_csv_batches"),
    ]

    operations = [
        migrations.RunPython(apply_deal_stages, migrations.RunPython.noop),
    ]
