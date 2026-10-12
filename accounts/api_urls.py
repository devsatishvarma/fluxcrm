from django.urls import path

from accounts.api import (
    AccountDetailView,
    AccountListView,
    ContactListView,
    LeadConvertView,
)

urlpatterns = [
    path("accounts/", AccountListView.as_view(), name="api-account-list"),
    path(
        "accounts/<uuid:account_id>/",
        AccountDetailView.as_view(),
        name="api-account-detail",
    ),
    path("contacts/", ContactListView.as_view(), name="api-contact-list"),
    path(
        "leads/<uuid:lead_id>/convert/",
        LeadConvertView.as_view(),
        name="api-lead-convert",
    ),
]
