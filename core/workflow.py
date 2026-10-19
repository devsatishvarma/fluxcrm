"""Protected lead and deal stage graphs.

A lead stage change does not move a deal, and a deal stage change does not
move a lead. Closing a deal as won or lost converts that lead separately.
"""

from core.taxonomy import DEAL_STAGE_PROBABILITY, active_keys

LEAD_GRAPH = {
    "NEW": {"CONTACTED", "NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "CONTACTED": {"MQL", "NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "MQL": {"DEMO_POC", "SQL", "NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "DEMO_POC": {"SQL", "NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "SQL": {"NURTURING", "UNQUALIFIED", "ARCHIVED"},
    "NURTURING": {"MQL", "DEMO_POC", "SQL", "UNQUALIFIED", "ARCHIVED"},
    "ARCHIVED": {"NEW"},
    "UNQUALIFIED": {"NEW"},
}

DEAL_GRAPH = {
    "NEW": {"DISCOVERY", "CLOSED_LOST", "CLOSED_HOLD"},
    "DISCOVERY": {"QUALIFIED", "CLOSED_LOST", "CLOSED_HOLD"},
    "QUALIFIED": {"TECHNICAL_EVALUATION", "CLOSED_LOST", "CLOSED_HOLD"},
    "TECHNICAL_EVALUATION": {"PROPOSAL", "CLOSED_LOST", "CLOSED_HOLD"},
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
    "DEMO_POC",
    "SQL",
    "NURTURING",
    "UNQUALIFIED",
    "ARCHIVED",
]


def allowed_targets(graph, stage):
    """Allowed moves, with the next stage in the cycle first."""
    targets = graph.get(stage, ())
    order = (
        tuple(DEAL_STAGE_PROBABILITY)
        if graph is DEAL_GRAPH
        else tuple(LEAD_BOARD_STAGES)
    )
    position = {key: index for index, key in enumerate(order)}
    current = position.get(stage, -1)
    later = [key for key in order if key in targets and position[key] > current]
    earlier = [key for key in order if key in targets and key not in later]
    unknown = sorted(key for key in targets if key not in position)
    return tuple(later + earlier + unknown)


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
    if to_stage == "DEMO_POC" and (
        lead.demo_scheduled_on is None or not lead.technical_contact_name
    ):
        gaps.append("demo_scheduled_on: enter the demo date and technical contact")
    if to_stage == "SQL" and (not reason or lead.next_follow_up_at is None):
        gaps.append("reason: add a note and the next follow-up")
    if to_stage == "NURTURING" and (
        not lead.nurture_reason or lead.next_follow_up_at is None
    ):
        gaps.append("nurture_reason: choose a nurture reason and a next follow-up")
    if to_stage == "UNQUALIFIED" and not lead.disqualification_reason:
        gaps.append("disqualification_reason: choose a disqualification reason")
    if to_stage == "ARCHIVED" and not reason:
        gaps.append("reason: add why the lead went silent")
    if to_stage == "NEW" and lead.stage in {"ARCHIVED", "UNQUALIFIED"} and not reason:
        gaps.append("reason: add the reopen reason")
    return gaps


def deal_gate_gaps(deal, to_stage, reason):
    """Return human-readable gaps that block this deal transition."""
    gaps = []
    if to_stage == "DISCOVERY" and not reason:
        gaps.append("reason: add what you learned about their requirements")
    if to_stage == "QUALIFIED":
        if deal.amount is None:
            gaps.append("amount: enter an amount")
        if deal.expected_close_date is None:
            gaps.append("expected_close_date: enter an expected close date")
    if to_stage == "TECHNICAL_EVALUATION":
        if deal.evaluation_started_on is None or not deal.technical_stakeholder_name:
            gaps.append(
                "evaluation_started_on: enter the POC or trial start date "
                "and the technical stakeholder"
            )
        if not reason:
            gaps.append("reason: add the success criteria")
    if to_stage == "PROPOSAL":
        if deal.amount is None:
            gaps.append("amount: enter the proposal amount")
        if deal.expected_close_date is None:
            gaps.append("expected_close_date: enter an expected close date")
        if not reason:
            gaps.append("reason: record that the proposal was sent")
    if to_stage == "NEGOTIATION":
        if not reason:
            gaps.append("reason: add the terms or redlines")
        if deal.expected_close_date is None:
            gaps.append("expected_close_date: enter an expected close date")
    if to_stage == "CLOSING" and not reason:
        gaps.append("reason: add the sign-off note")
    if to_stage == "CLOSING" and deal.expected_close_date is None:
        gaps.append("expected_close_date: confirm the target close date")
    if to_stage == "CLOSED_WON":
        if deal.amount is None:
            gaps.append("amount: a won deal needs a final amount")
        if deal.actual_close_date is None:
            gaps.append("actual_close_date: enter the date the deal closed")
    if to_stage == "CLOSED_LOST" and not deal.close_reason:
        gaps.append("close_reason: choose a loss reason")
    if to_stage == "CLOSED_HOLD" and not deal.close_reason:
        gaps.append("close_reason: choose a hold reason")
    if to_stage == "NEW" and deal.stage == "CLOSED_HOLD" and not reason:
        gaps.append("reason: add the reopen reason")
    return gaps
