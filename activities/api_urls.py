from django.urls import path

from activities import api

urlpatterns = [
    path("activities/", api.ActivityListView.as_view(), name="api_activities"),
    path("tasks/", api.TaskListView.as_view(), name="api_tasks"),
    path("tasks/<uuid:task_id>/complete/", api.TaskCompleteView.as_view()),
    path("tasks/<uuid:task_id>/snooze/", api.TaskSnoozeView.as_view()),
]
