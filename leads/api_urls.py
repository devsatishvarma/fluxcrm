from django.urls import path

from leads.api import (
    LeadBulkAssignView,
    LeadDetailView,
    LeadHistoryView,
    LeadListView,
    LeadRestoreView,
    LeadTransitionView,
)

urlpatterns = [
    path("leads/", LeadListView.as_view(), name="api-lead-list"),
    path("leads/bulk-assign/", LeadBulkAssignView.as_view(), name="api-lead-bulk"),
    path("leads/<uuid:lead_id>/", LeadDetailView.as_view(), name="api-lead-detail"),
    path(
        "leads/<uuid:lead_id>/transition/",
        LeadTransitionView.as_view(),
        name="api-lead-transition",
    ),
    path(
        "leads/<uuid:lead_id>/history/",
        LeadHistoryView.as_view(),
        name="api-lead-history",
    ),
    path(
        "leads/<uuid:lead_id>/restore/",
        LeadRestoreView.as_view(),
        name="api-lead-restore",
    ),
]
