from django.urls import path

from leads.api import LeadDetailView, LeadListView, LeadRestoreView

urlpatterns = [
    path("leads/", LeadListView.as_view(), name="api-lead-list"),
    path("leads/<uuid:lead_id>/", LeadDetailView.as_view(), name="api-lead-detail"),
    path(
        "leads/<uuid:lead_id>/restore/",
        LeadRestoreView.as_view(),
        name="api-lead-restore",
    ),
]
