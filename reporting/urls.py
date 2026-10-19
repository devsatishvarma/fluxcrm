from django.urls import path

from reporting import views

app_name = "reporting"

urlpatterns = [
    path("reports/", views.dashboard, name="dashboard"),
    path("reports/<slug:report_key>/", views.report_detail, name="detail"),
    path("reports/<slug:report_key>/export/", views.report_export, name="export"),
]
