"""Activity and task API."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from activities.models import Activity, Task
from activities.services import complete_task, create_activity, create_task, snooze_task
from core.access import scoped
from core.api import CappedPagination

BUCKETS = ("overdue", "due", "upcoming")


def activity_payload(activity):
    return {
        "id": str(activity.pk),
        "external_id": activity.external_id,
        "activity_type": activity.activity_type,
        "subject": activity.subject,
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
        if bucket in BUCKETS:
            zone = ZoneInfo(request.user.timezone or "America/Los_Angeles")
            local_now = timezone.now().astimezone(zone)
            start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            queryset = queryset.filter(status=Task.Status.OPEN).annotate(
                effective_due=Coalesce("snooze_until", "due_at")
            )
            if bucket == "overdue":
                queryset = queryset.filter(effective_due__lt=local_now)
            elif bucket == "upcoming":
                queryset = queryset.filter(effective_due__gte=end)
            else:
                queryset = queryset.filter(
                    effective_due__gte=start, effective_due__lt=end
                )
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
            request_id=getattr(request, "request_id", ""),
        )
        return Response(task_payload(task))


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
