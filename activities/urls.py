from django.urls import path

from activities import views

app_name = "activities"

urlpatterns = [
    path("tasks/", views.task_list, name="tasks"),
    path("activities/new/", views.activity_create, name="activity_create"),
    path("tasks/new/", views.task_create, name="task_create"),
    path("tasks/<uuid:task_id>/edit/", views.task_update, name="task_update"),
    path("tasks/<uuid:task_id>/complete/", views.task_complete, name="complete"),
    path("tasks/<uuid:task_id>/cancel/", views.task_cancel, name="cancel"),
    path("tasks/<uuid:task_id>/hold/", views.task_hold, name="hold"),
    path("tasks/<uuid:task_id>/resume/", views.task_resume, name="resume"),
    path("tasks/<uuid:task_id>/delete/", views.task_delete, name="delete"),
    path("tasks/<uuid:task_id>/snooze/", views.task_snooze, name="snooze"),
    path(
        "activities/<uuid:activity_id>/edit/",
        views.activity_update,
        name="activity_update",
    ),
    path(
        "activities/<uuid:activity_id>/delete/",
        views.activity_delete,
        name="activity_delete",
    ),
]
