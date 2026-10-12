from django.urls import path

from sales.api import DealDetailView, DealListView

urlpatterns = [
    path("deals/", DealListView.as_view(), name="api-deal-list"),
    path("deals/<uuid:deal_id>/", DealDetailView.as_view(), name="api-deal-detail"),
]
