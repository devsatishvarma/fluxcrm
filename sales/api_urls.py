from django.urls import path

from sales.api import DealDetailView, DealHistoryView, DealListView, DealTransitionView

urlpatterns = [
    path("deals/", DealListView.as_view(), name="api-deal-list"),
    path("deals/<uuid:deal_id>/", DealDetailView.as_view(), name="api-deal-detail"),
    path(
        "deals/<uuid:deal_id>/transition/",
        DealTransitionView.as_view(),
        name="api-deal-transition",
    ),
    path(
        "deals/<uuid:deal_id>/stage-history/",
        DealHistoryView.as_view(),
        name="api-deal-history",
    ),
]
