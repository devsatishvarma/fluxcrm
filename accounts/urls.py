from django.contrib.auth.decorators import login_required
from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("accounts/", login_required(views.account_list), name="list"),
    path("contacts/", login_required(views.contact_list), name="contacts"),
    path("accounts/new/", login_required(views.account_create), name="create"),
    path(
        "accounts/<uuid:account_id>/",
        login_required(views.account_detail),
        name="detail",
    ),
    path(
        "accounts/<uuid:account_id>/contacts/new/",
        login_required(views.contact_create),
        name="contact_create",
    ),
]
