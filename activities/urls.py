from django.urls import path

from activities import views

app_name = "activities"

urlpatterns = [
    path("tasks/", views.task_list, name="tasks"),
    path("activities/new/", views.activity_create, name="activity_create"),
    path("tasks/new/", views.task_create, name="task_create"),
    path("tasks/<uuid:task_id>/complete/", views.task_complete, name="complete"),
    path("tasks/<uuid:task_id>/snooze/", views.task_snooze, name="snooze"),
]
