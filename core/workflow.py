"""Protected lead and deal stage graphs.

Activity and task side effects stay in Phase 4. Primary-contact checks stay in
Phase 5. Until then, the transition service enforces the data those gates need
and explains any missing field.
"""

from core.taxonomy import DEAL_STAGE_PROBABILITY, active_keys

LEAD_GRAPH = {
    "NEW": {"CONTACTED", "NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "CONTACTED": {"MQL", "NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "MQL": {"SQL_READY", "NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "SQL_READY": {
        "NURTURING",
        "UNQUALIFIED",
        "SQL_REACTIVATION",
        "ARCHIVED",
    },
    "NURTURING": {
        "MQL",
        "SQL_READY",
        "SQL_REACTIVATION",
        "UNQUALIFIED",
        "ARCHIVED",
    },
    "SQL_REACTIVATION": {
        "SQL_READY",
        "NURTURING",
        "UNQUALIFIED",
        "ARCHIVED",
    },
    "ARCHIVED": {"NEW"},
    "UNQUALIFIED": {"NEW"},
}

DEAL_GRAPH = {
    "NEW": {"CONTACTED", "CLOSED_LOST", "CLOSED_HOLD"},
    "CONTACTED": {"QUALIFIED", "CLOSED_LOST", "CLOSED_HOLD"},
    "QUALIFIED": {"DISCOVERY", "CLOSED_LOST", "CLOSED_HOLD"},
    "DISCOVERY": {"PROPOSAL", "CLOSED_LOST", "CLOSED_HOLD"},
    "PROPOSAL": {"NEGOTIATION", "CLOSED_LOST", "CLOSED_HOLD"},
    "NEGOTIATION": {"CLOSING", "CLOSED_LOST", "CLOSED_HOLD"},
    "CLOSING": {"CLOSED_WON", "CLOSED_LOST", "CLOSED_HOLD"},
    "CLOSED_HOLD": {"NEW"},
    "CLOSED_WON": set(),
    "CLOSED_LOST": set(),
}

CLOSED_DEAL_STAGES = {"CLOSED_WON", "CLOSED_LOST", "CLOSED_HOLD"}
OPEN_DEAL_STAGES = [
    stage for stage in DEAL_STAGE_PROBABILITY if stage not in CLOSED_DEAL_STAGES
]
LEAD_BOARD_STAGES = [
    "NEW",
    "CONTACTED",
    "MQL",
    "SQL_READY",
    "NURTURING",
    "SQL_REACTIVATION",
    "UNQUALIFIED",
    "ARCHIVED",
]


def allowed_targets(graph, stage):
    return tuple(sorted(graph.get(stage, ())))


def stage_is_active(list_key, stage):
    return stage in active_keys(list_key)


def lead_gate_gaps(lead, to_stage, reason):
    """Return human-readable gaps that block this lead transition."""
    gaps = []
    if to_stage == "CONTACTED":
        substatus = lead.contact_substatus
        has_channel = bool(lead.email or lead.work_phone or lead.mobile_phone)
        if substatus == "NO_CONTACT_DETAILS":
            if not (lead.notes or reason):
                gaps.append("notes: add a no-contact-details note")
        elif substatus not in {"ATTEMPTED", "IN_CONTACT"}:
            gaps.append("contact_substatus: choose Attempted to Contact or In Contact")
        elif not has_channel:
            gaps.append("email: add an email or phone, or mark no contact details")
    if to_stage == "MQL" and not (lead.source and lead.company_name and reason):
        gaps.append("reason: add the qualification note")
    if to_stage == "SQL_READY" and (not reason or lead.next_follow_up_at is None):
        gaps.append("reason: document need, fit, and the next follow-up")
    if to_stage == "NURTURING" and (
        not lead.nurture_reason or lead.next_follow_up_at is None
    ):
        gaps.append("nurture_reason: choose a nurture reason and a next follow-up")
    if to_stage == "UNQUALIFIED" and not lead.disqualification_reason:
        gaps.append("disqualification_reason: choose a disqualification reason")
    if to_stage == "ARCHIVED" and not reason:
        gaps.append("reason: add the no-interest reason")
    if to_stage == "SQL_REACTIVATION" and (
        not reason or lead.next_follow_up_at is None
    ):
        gaps.append("reason: add the re-engagement reason and the next follow-up")
    if to_stage == "NEW" and lead.stage in {"ARCHIVED", "UNQUALIFIED"} and not reason:
        gaps.append("reason: add the reopen reason")
    return gaps


def deal_gate_gaps(deal, to_stage, reason):
    """Return human-readable gaps that block this deal transition."""
    gaps = []
    bant = (
        deal.bant_budget_status,
        deal.bant_authority_status,
        deal.bant_need_status,
        deal.bant_timeline_status,
    )
    if to_stage == "CONTACTED" and not reason:
        gaps.append("reason: describe the contact attempt")
    if to_stage == "QUALIFIED":
        if deal.amount is None:
            gaps.append("amount: enter an amount")
        if deal.expected_close_date is None:
            gaps.append("expected_close_date: enter an expected close date")
        if deal.bant_need_status == "UNKNOWN":
            gaps.append("bant_need_status: Need cannot stay Unknown")
        if deal.bant_authority_status not in {"PARTIAL", "CONFIRMED"}:
            gaps.append("bant_authority_status: Authority must be Partial or Confirmed")
    if to_stage == "DISCOVERY":
        if not reason:
            gaps.append("reason: describe the discovery review")
        if any(status == "UNKNOWN" for status in bant):
            gaps.append("bant: review budget, authority, need, and timeline")
    if to_stage == "PROPOSAL":
        if deal.amount is None:
            gaps.append("amount: enter the proposal amount")
        if deal.expected_close_date is None:
            gaps.append("expected_close_date: enter an expected close date")
        if not reason:
            gaps.append("reason: record that the proposal was sent")
    if to_stage in {"NEGOTIATION", "CLOSING"} and not reason:
        gaps.append("reason: record the decision step")
    if to_stage == "CLOSING" and deal.expected_close_date is None:
        gaps.append("expected_close_date: confirm the target close date")
    if to_stage == "CLOSED_WON":
        if deal.amount is None:
            gaps.append("amount: a won deal needs a final amount")
        if deal.expected_close_date is None:
            gaps.append("expected_close_date: a won deal needs a close date")
    if to_stage == "CLOSED_LOST" and not deal.close_reason:
        gaps.append("close_reason: choose a loss reason")
    if to_stage == "CLOSED_HOLD" and not deal.close_reason:
        gaps.append("close_reason: choose a hold reason")
    if to_stage == "NEW" and deal.stage == "CLOSED_HOLD" and not reason:
        gaps.append("reason: add the reopen reason")
    return gaps
