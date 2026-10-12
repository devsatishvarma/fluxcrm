from django.contrib.auth.decorators import login_required
from django.urls import path

from sales import views

app_name = "sales"

urlpatterns = [
    path("deals/", login_required(views.deal_list), name="list"),
    path("deals/board/", login_required(views.deal_board), name="board"),
    path("deals/new/", login_required(views.deal_create), name="create"),
    path("deals/<uuid:deal_id>/", login_required(views.deal_detail), name="detail"),
    path("deals/<uuid:deal_id>/edit/", login_required(views.deal_edit), name="edit"),
    path(
        "deals/<uuid:deal_id>/transition/",
        login_required(views.deal_transition),
        name="transition",
    ),
    path(
        "deals/<uuid:deal_id>/delete/",
        login_required(views.deal_delete),
        name="delete",
    ),
]
