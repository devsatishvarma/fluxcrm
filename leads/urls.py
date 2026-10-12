from django.contrib.auth.decorators import login_required
from django.urls import path

from accounts.views import lead_convert as convert_view
from leads import views

app_name = "leads"

urlpatterns = [
    path("leads/", login_required(views.lead_list), name="list"),
    path("leads/board/", login_required(views.lead_board), name="board"),
    path("leads/new/", login_required(views.lead_create), name="create"),
    path(
        "leads/bulk-assign/",
        login_required(views.lead_bulk_assign),
        name="bulk_assign",
    ),
    path("leads/<uuid:lead_id>/", login_required(views.lead_detail), name="detail"),
    path("leads/<uuid:lead_id>/edit/", login_required(views.lead_edit), name="edit"),
    path(
        "leads/<uuid:lead_id>/transition/",
        login_required(views.lead_transition),
        name="transition",
    ),
    path(
        "leads/<uuid:lead_id>/delete/",
        login_required(views.lead_delete),
        name="delete",
    ),
    path(
        "leads/<uuid:lead_id>/convert/",
        login_required(convert_view),
        name="convert",
    ),
]
