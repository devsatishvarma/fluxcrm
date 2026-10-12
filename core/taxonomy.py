"""Frozen version-1 picklists. Keys stay stable; labels may be edited later."""

TAXONOMY = {
    "LEAD_SOURCE": (
        ("WEB", "Website"),
        ("REFERRAL", "Referral"),
        ("PARTNER", "Partner"),
        ("CONFERENCE_EVENT", "Conference/Event"),
        ("OUTBOUND", "Outbound Prospecting"),
        ("LIST_PURCHASE", "Purchased List"),
        ("ORGANIC_SEARCH", "Organic Search"),
        ("PAID_SEARCH", "Paid Search"),
        ("SOCIAL", "Social Media"),
        ("EMAIL_CAMPAIGN", "Email Campaign"),
        ("OTHER", "Other"),
    ),
    "INDUSTRY": (
        ("INFORMATION_TECHNOLOGY", "Information Technology"),
        ("PROFESSIONAL_SERVICES", "Professional Services"),
        ("HEALTHCARE", "Healthcare"),
        ("FINANCIAL_SERVICES", "Financial Services"),
        ("MANUFACTURING", "Manufacturing"),
        ("RETAIL", "Retail"),
        ("EDUCATION", "Education"),
        ("GOVERNMENT", "Government"),
        ("NONPROFIT", "Nonprofit"),
        ("OTHER", "Other"),
    ),
    "COMPANY_SIZE": (
        ("1_10", "1–10 employees"),
        ("11_50", "11–50 employees"),
        ("51_200", "51–200 employees"),
        ("201_500", "201–500 employees"),
        ("501_1000", "501–1,000 employees"),
        ("1001_5000", "1,001–5,000 employees"),
        ("5001_PLUS", "5,001+ employees"),
        ("UNKNOWN", "Unknown"),
    ),
    "NURTURE_REASON": (
        ("TIMING", "Timing not right"),
        ("BUDGET", "Budget not available"),
        ("MQL_NOT_SALES_READY", "Marketing-qualified but not sales-ready"),
        ("NO_RESPONSE", "Unable to re-engage"),
        ("FUTURE_EVALUATION", "Evaluating in a future period"),
        ("OTHER", "Other"),
    ),
    "DISQUALIFICATION_REASON": (
        ("BAD_DATA", "Invalid or unusable data"),
        ("DUPLICATE", "Duplicate record"),
        ("NO_FIT", "Outside ideal customer profile"),
        ("NO_NEED", "No relevant need"),
        ("NO_AUTHORITY", "No access to authority"),
        ("NO_BUDGET", "No viable budget"),
        ("OUTSIDE_TERRITORY", "Outside served territory"),
        ("OTHER", "Other"),
    ),
    "CLOSED_LOST_REASON": (
        ("PRICE", "Price"),
        ("COMPETITOR", "Competitor selected"),
        ("NO_DECISION", "No decision"),
        ("BUDGET", "Budget unavailable"),
        ("TIMING", "Timing"),
        ("REQUIREMENTS_GAP", "Requirements gap"),
        ("RELATIONSHIP", "Relationship/incumbent"),
        ("INTERNAL_CANCELLED", "Internally cancelled"),
        ("OTHER", "Other"),
    ),
    "CLOSED_HOLD_REASON": (
        ("BUDGET", "Budget deferred"),
        ("TIMING", "Timing deferred"),
        ("CUSTOMER_REQUEST", "Customer requested hold"),
        ("PROCUREMENT_LEGAL", "Procurement/legal delay"),
        ("RESOURCE_CONSTRAINT", "Customer resource constraint"),
        ("INTERNAL_CAPACITY", "Infoshare capacity constraint"),
        ("OTHER", "Other"),
    ),
    "LEAD_STAGE": (
        ("NEW", "New"),
        ("CONTACTED", "Contacted"),
        ("MQL", "MQL"),
        ("SQL_READY", "SQL Ready"),
        ("NURTURING", "Nurturing"),
        ("SQL_REACTIVATION", "SQL Reactivation"),
        ("UNQUALIFIED", "Unqualified"),
        ("ARCHIVED", "Archived"),
    ),
    "CONTACT_SUBSTATUS": (
        ("ATTEMPTED", "Attempted to Contact"),
        ("IN_CONTACT", "In Contact"),
        ("NO_CONTACT_DETAILS", "No contact details"),
    ),
    "DEAL_STAGE": (
        ("NEW", "New"),
        ("CONTACTED", "Contacted"),
        ("QUALIFIED", "Qualified"),
        ("DISCOVERY", "Discovery"),
        ("PROPOSAL", "Proposal"),
        ("NEGOTIATION", "Negotiation"),
        ("CLOSING", "Closing"),
        ("CLOSED_WON", "Closed Won"),
        ("CLOSED_LOST", "Closed Lost"),
        ("CLOSED_HOLD", "Closed Hold"),
    ),
    "DEAL_TYPE": (
        ("CONSULTING_SERVICES", "Consulting Services"),
        ("OEM_RESALE", "OEM Resale"),
        ("SOFTWARE_SERVICES", "Software Services"),
    ),
    "LEAD_RATING": (
        ("HOT", "Hot"),
        ("WARM", "Warm"),
        ("COLD", "Cold"),
    ),
    "DEAL_CONFIDENCE": (
        ("HIGH", "High"),
        ("MEDIUM", "Medium"),
        ("LOW", "Low"),
    ),
    "BANT_STATUS": (
        ("UNKNOWN", "Unknown"),
        ("NOT_MET", "Not met"),
        ("PARTIAL", "Partial"),
        ("CONFIRMED", "Confirmed"),
    ),
}

DEAL_STAGE_PROBABILITY = {
    "NEW": "5.00",
    "CONTACTED": "10.00",
    "QUALIFIED": "20.00",
    "DISCOVERY": "30.00",
    "PROPOSAL": "50.00",
    "NEGOTIATION": "70.00",
    "CLOSING": "90.00",
    "CLOSED_WON": "100.00",
    "CLOSED_LOST": "0.00",
    "CLOSED_HOLD": "0.00",
}


def ensure_picklists():
    """Insert any missing version-1 values without reactivating retired ones."""
    from core.models import PicklistValue

    for list_key, rows in TAXONOMY.items():
        for order, (key, label) in enumerate(rows, start=1):
            PicklistValue.objects.get_or_create(
                list_key=list_key,
                key=key,
                defaults={"label": label, "order": order, "active": True},
            )


def active_keys(list_key):
    from core.models import PicklistValue

    return set(
        PicklistValue.objects.filter(list_key=list_key, active=True).values_list(
            "key", flat=True
        )
    )


def known_keys(list_key):
    from core.models import PicklistValue

    return set(
        PicklistValue.objects.filter(list_key=list_key).values_list("key", flat=True)
    )


def choice_pairs(list_key):
    from core.models import PicklistValue

    pairs = [
        (row.key, row.label)
        for row in PicklistValue.objects.filter(
            list_key=list_key, active=True
        ).order_by("order", "key")
    ]
    return [("", "---------"), *pairs]
