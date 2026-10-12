"""Read-only audit search and preparatory import/export checks."""

from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import CappedPagination
from core.policy import allows
from core.services import authorize_import, request_export, visible_audit_events


def audit_payload(event, *, snapshots):
    payload = {
        "id": event.pk,
        "action": event.action,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "occurred_at": event.occurred_at.isoformat(),
        "actor_id": event.actor_id,
    }
    if snapshots:
        payload["before"] = event.before_json
        payload["after"] = event.after_json
    return payload


class AuditEventListView(APIView):
    def get(self, request):
        if not allows(request.user, "audit", "R"):
            from core.policy import require_action

            require_action(request.user, "audit", "R")
        events = visible_audit_events(request.user)
        if request.query_params.get("object_type"):
            events = events.filter(object_type=request.query_params.get("object_type"))
        if request.query_params.get("object_id"):
            events = events.filter(object_id=request.query_params.get("object_id"))
        paginator = CappedPagination()
        page = paginator.paginate_queryset(events, request, view=self)
        snapshots = allows(request.user, "settings", "A")
        return paginator.get_paginated_response(
            [audit_payload(event, snapshots=snapshots) for event in page]
        )

    def post(self, request):
        return Response(status=405)

    def put(self, request):
        return Response(status=405)

    def patch(self, request):
        return Response(status=405)

    def delete(self, request):
        return Response(status=405)


class ExportView(APIView):
    def post(self, request):
        count = request_export(
            actor=request.user,
            object_key=request.data.get("object", ""),
            query=request.data.get("q", ""),
            request_id=getattr(request, "request_id", ""),
        )
        return Response({"row_count": count})


class ImportAuthorizeView(APIView):
    def post(self, request):
        authorize_import(
            actor=request.user,
            object_key=request.data.get("object", ""),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(status=204)
