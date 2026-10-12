"""Lead API. Uses the same services as the HTML pages."""

from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import get_scoped
from core.api import CappedPagination, parse_page_size
from leads.models import Lead
from leads.services import (
    bulk_assign_leads,
    create_lead,
    delete_lead,
    filter_leads,
    lead_history,
    lead_payload,
    restore_lead,
    transition_lead,
    update_lead,
)


class LeadListView(APIView):
    def get(self, request):
        parse_page_size(request.query_params.get("page_size"))
        paginator = CappedPagination()
        page = paginator.paginate_queryset(
            filter_leads(request.user, request.query_params),
            request,
            view=self,
        )
        return paginator.get_paginated_response([lead_payload(lead) for lead in page])

    def post(self, request):
        lead = create_lead(
            actor=request.user,
            data=request.data,
            request_id=getattr(request, "request_id", ""),
        )
        return Response(lead_payload(lead), status=201)


class LeadBulkAssignView(APIView):
    def post(self, request):
        leads = bulk_assign_leads(
            actor=request.user,
            lead_ids=request.data.get("leads") or [],
            owner=request.data.get("owner"),
            request_id=getattr(request, "request_id", ""),
        )
        return Response([lead_payload(lead) for lead in leads])


class LeadDetailView(APIView):
    def get(self, request, lead_id):
        return Response(lead_payload(get_scoped(Lead, request.user, lead_id)))

    def patch(self, request, lead_id):
        lead = update_lead(
            actor=request.user,
            lead_id=lead_id,
            version=request.data.get("version"),
            data=request.data,
            request_id=getattr(request, "request_id", ""),
        )
        return Response(lead_payload(lead))

    def delete(self, request, lead_id):
        delete_lead(
            actor=request.user,
            lead_id=lead_id,
            version=request.data.get("version"),
            delete_reason=request.data.get("delete_reason", ""),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(status=204)


class LeadRestoreView(APIView):
    def post(self, request, lead_id):
        lead = restore_lead(
            actor=request.user,
            lead_id=lead_id,
            version=request.data.get("version"),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(lead_payload(lead))


class LeadTransitionView(APIView):
    def post(self, request, lead_id):
        correction = request.data.get("correction")
        lead = transition_lead(
            actor=request.user,
            lead_id=lead_id,
            version=request.data.get("version"),
            to_stage=request.data.get("to_stage"),
            reason=request.data.get("reason", ""),
            data=request.data,
            correction=correction is True or str(correction).lower() in {"1", "true"},
            request_id=getattr(request, "request_id", ""),
        )
        return Response(lead_payload(lead))


class LeadHistoryView(APIView):
    def get(self, request, lead_id):
        lead = get_scoped(Lead, request.user, lead_id)
        return Response(
            [
                {
                    "from_stage": row.from_stage,
                    "to_stage": row.to_stage,
                    "changed_at": row.changed_at.isoformat(),
                    "changed_by": row.changed_by_id,
                    "duration_seconds": row.duration_seconds,
                    "probability_snapshot": (
                        None
                        if row.probability_snapshot is None
                        else str(row.probability_snapshot)
                    ),
                    "probability_reason": row.probability_reason,
                    "reason": row.reason,
                    "correction": row.correction,
                }
                for row in lead_history(lead)
            ]
        )
