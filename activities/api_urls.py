from django.urls import path

from activities import api

urlpatterns = [
    path("activities/", api.ActivityListView.as_view(), name="api_activities"),
    path(
        "activities/<uuid:activity_id>/",
        api.ActivityDetailView.as_view(),
        name="api_activity_detail",
    ),
    path("tasks/", api.TaskListView.as_view(), name="api_tasks"),
    path("tasks/<uuid:task_id>/complete/", api.TaskCompleteView.as_view()),
    path("tasks/<uuid:task_id>/status/", api.TaskStatusView.as_view()),
    path("tasks/<uuid:task_id>/delete/", api.TaskDeleteView.as_view()),
    path("tasks/<uuid:task_id>/snooze/", api.TaskSnoozeView.as_view()),
]
