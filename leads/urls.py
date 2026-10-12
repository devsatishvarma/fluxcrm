from django.contrib.auth.decorators import login_required
from django.urls import path

from leads import views

app_name = "leads"

urlpatterns = [
    path("leads/", login_required(views.lead_list), name="list"),
    path("leads/new/", login_required(views.lead_create), name="create"),
    path("leads/<uuid:lead_id>/", login_required(views.lead_detail), name="detail"),
    path("leads/<uuid:lead_id>/edit/", login_required(views.lead_edit), name="edit"),
    path(
        "leads/<uuid:lead_id>/delete/",
        login_required(views.lead_delete),
        name="delete",
    ),
]
