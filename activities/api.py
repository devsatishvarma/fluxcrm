"""Activity and task API."""

from rest_framework.response import Response
from rest_framework.views import APIView

from activities.models import Activity, Task
from activities.services import (
    TASK_BUCKET_KEYS,
    change_task_status,
    complete_task,
    create_activity,
    create_task,
    delete_activity,
    delete_task,
    filter_task_bucket,
    snooze_task,
    update_activity,
)
from core.access import scoped
from core.api import CappedPagination


def activity_payload(activity):
    return {
        "id": str(activity.pk),
        "external_id": activity.external_id,
        "activity_type": activity.activity_type,
        "subject": activity.subject,
        "with_whom": activity.party_name(),
        "with_contact_id": (
            None if activity.with_contact_id is None else str(activity.with_contact_id)
        ),
        "with_lead_id": (
            None if activity.with_lead_id is None else str(activity.with_lead_id)
        ),
        "occurred_at": activity.occurred_at.isoformat(),
        "owner_id": activity.owner_id,
        "version": activity.version,
    }


def task_payload(task):
    return {
        "id": str(task.pk),
        "external_id": task.external_id,
        "title": task.title,
        "due_at": task.due_at.isoformat(),
        "snooze_until": None
        if task.snooze_until is None
        else task.snooze_until.isoformat(),
        "status": task.status,
        "priority": task.priority,
        "owner_id": task.owner_id,
        "version": task.version,
    }


def _links(data):
    links = data.get("links")
    if isinstance(links, list):
        return links
    if data.get("kind") and data.get("object_id"):
        return [{"kind": data.get("kind"), "id": data.get("object_id")}]
    return []


class ActivityListView(APIView):
    def get(self, request):
        queryset = scoped(Activity.objects.select_related("owner"), request.user)
        kind = request.query_params.get("kind")
        object_id = request.query_params.get("object_id")
        if kind and object_id:
            queryset = queryset.filter(
                links__content_type__model=kind,
                links__object_id=object_id,
            ).distinct()
        page = CappedPagination().paginate_queryset(queryset, request, view=self)
        return Response({"results": [activity_payload(item) for item in page]})

    def post(self, request):
        activity = create_activity(
            actor=request.user,
            data=request.data,
            links=_links(request.data),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(activity_payload(activity), status=201)


class TaskListView(APIView):
    def get(self, request):
        queryset = scoped(Task.objects.select_related("owner"), request.user)
        bucket = request.query_params.get("bucket")
        if bucket in TASK_BUCKET_KEYS:
            queryset = filter_task_bucket(queryset, bucket, request.user)
        page = CappedPagination().paginate_queryset(queryset, request, view=self)
        return Response({"results": [task_payload(item) for item in page]})

    def post(self, request):
        task = create_task(
            actor=request.user,
            data=request.data,
            links=_links(request.data),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(task_payload(task), status=201)


class TaskCompleteView(APIView):
    def post(self, request, task_id):
        task = complete_task(
            actor=request.user,
            task_id=task_id,
            version=request.data.get("version"),
            completion_notes=request.data.get(
                "completion_notes", request.data.get("description", "")
            ),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(task_payload(task))


class TaskStatusView(APIView):
    def post(self, request, task_id):
        task = change_task_status(
            actor=request.user,
            task_id=task_id,
            version=request.data.get("version"),
            status=request.data.get("status"),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(task_payload(task))


class TaskDeleteView(APIView):
    def post(self, request, task_id):
        delete_task(
            actor=request.user,
            task_id=task_id,
            version=request.data.get("version"),
            delete_reason=request.data.get("delete_reason"),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(status=204)


class ActivityDetailView(APIView):
    def patch(self, request, activity_id):
        activity = update_activity(
            actor=request.user,
            activity_id=activity_id,
            version=request.data.get("version"),
            data=request.data,
            request_id=getattr(request, "request_id", ""),
        )
        return Response(activity_payload(activity))

    def delete(self, request, activity_id):
        delete_activity(
            actor=request.user,
            activity_id=activity_id,
            version=request.data.get("version"),
            delete_reason=request.data.get("delete_reason"),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(status=204)


class TaskSnoozeView(APIView):
    def post(self, request, task_id):
        task = snooze_task(
            actor=request.user,
            task_id=task_id,
            version=request.data.get("version"),
            until=request.data.get("snooze_until"),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(task_payload(task))
