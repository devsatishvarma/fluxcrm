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
        ("TECHNOLOGY_SAAS", "Technology & SaaS"),
        ("PROFESSIONAL_SERVICES", "Professional Services"),
        ("HEALTHCARE", "Healthcare"),
        ("FINANCIAL_SERVICES", "Financial Services"),
        ("INSURANCE", "Insurance"),
        ("MANUFACTURING", "Manufacturing"),
        ("AUTOMOTIVE", "Automotive"),
        ("RETAIL", "Retail & E-Commerce"),
        ("HOSPITALITY_TRAVEL", "Hospitality & Travel"),
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
        ("REACTIVATION", "Reactivation"),
        ("OTHER", "Other"),
    ),
    "DISQUALIFICATION_REASON": (
        ("NO_BUDGET", "No Budget"),
        ("NO_TECHNICAL_FIT", "No Technical Fit"),
        ("WRONG_DECISION_MAKER", "Wrong Decision-Maker"),
        ("SECURITY_COMPLIANCE", "Security-Compliance Mismatch"),
        ("TIMING", "Timing"),
    ),
    "CURRENT_TOOLS": (
        ("MICROSOFT_365", "Microsoft 365"),
        ("AZURE", "Microsoft Azure"),
        ("AWS", "Amazon Web Services"),
        ("GOOGLE_CLOUD", "Google Cloud"),
        ("ON_PREMISES", "On-premises"),
        ("HYBRID", "Hybrid"),
        ("UNKNOWN", "Unknown"),
        ("OTHER", "Other"),
    ),
    "BUDGET_RANGE": (
        ("UNDER_25K", "Under $25,000"),
        ("25K_100K", "$25,000–$100,000"),
        ("100K_250K", "$100,000–$250,000"),
        ("250K_PLUS", "$250,000 or more"),
        ("UNKNOWN", "Unknown"),
    ),
    "BUYING_TIMELINE": (
        ("IMMEDIATE", "Immediate"),
        ("THIS_QUARTER", "This quarter"),
        ("NEXT_QUARTER", "Next quarter"),
        ("THIS_YEAR", "This year"),
        ("UNKNOWN", "Unknown"),
    ),
    "CLOSED_LOST_REASON": (
        ("PRICE", "Price"),
        ("COMPETITOR", "Competitor"),
        ("NO_TECHNICAL_FIT", "No Technical Fit"),
        ("TIMING", "Timing"),
        ("LOST_TO_INTERNAL_BUILD", "Lost to Internal Build"),
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
        ("DEMO_POC", "Demo"),
        ("SQL", "SQL"),
        ("NURTURING", "Nurturing"),
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
        ("DISCOVERY", "Discovery"),
        ("QUALIFIED", "Qualified"),
        ("TECHNICAL_EVALUATION", "POC/Tech Evaluation"),
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
    "DISCOVERY": "10.00",
    "QUALIFIED": "20.00",
    "TECHNICAL_EVALUATION": "30.00",
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
