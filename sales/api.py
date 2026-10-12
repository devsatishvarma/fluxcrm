"""Deal API. Uses the same services as the HTML pages."""

from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import get_scoped
from core.api import CappedPagination, parse_page_size
from sales.models import Deal
from sales.services import (
    create_deal,
    deal_history,
    deal_payload,
    delete_deal,
    filter_deals,
    transition_deal,
    update_deal,
)


class DealListView(APIView):
    def get(self, request):
        parse_page_size(request.query_params.get("page_size"))
        paginator = CappedPagination()
        page = paginator.paginate_queryset(
            filter_deals(request.user, request.query_params),
            request,
            view=self,
        )
        return paginator.get_paginated_response([deal_payload(deal) for deal in page])

    def post(self, request):
        deal = create_deal(
            actor=request.user,
            data=request.data,
            request_id=getattr(request, "request_id", ""),
        )
        return Response(deal_payload(deal), status=201)


class DealDetailView(APIView):
    def get(self, request, deal_id):
        deal = get_scoped(Deal, request.user, deal_id, related=("owner", "lead"))
        return Response(deal_payload(deal))

    def patch(self, request, deal_id):
        deal = update_deal(
            actor=request.user,
            deal_id=deal_id,
            version=request.data.get("version"),
            data=request.data,
            request_id=getattr(request, "request_id", ""),
        )
        return Response(deal_payload(deal))

    def delete(self, request, deal_id):
        delete_deal(
            actor=request.user,
            deal_id=deal_id,
            version=request.data.get("version"),
            delete_reason=request.data.get("delete_reason", ""),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(status=204)


class DealTransitionView(APIView):
    def post(self, request, deal_id):
        correction = request.data.get("correction")
        deal = transition_deal(
            actor=request.user,
            deal_id=deal_id,
            version=request.data.get("version"),
            to_stage=request.data.get("to_stage"),
            reason=request.data.get("reason", ""),
            data=request.data,
            correction=correction is True or str(correction).lower() in {"1", "true"},
            request_id=getattr(request, "request_id", ""),
        )
        return Response(deal_payload(deal))


class DealHistoryView(APIView):
    def get(self, request, deal_id):
        deal = get_scoped(Deal, request.user, deal_id, related=("owner", "lead"))
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
                for row in deal_history(deal)
            ]
        )
