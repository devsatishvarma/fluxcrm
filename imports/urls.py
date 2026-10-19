from django.urls import path

from imports import views

app_name = "imports"

urlpatterns = [
    path("imports/", views.home, name="home"),
    path("imports/templates/<slug:entity>.csv", views.template_file, name="template"),
    path("imports/preview/", views.preview, name="preview"),
    path("imports/<uuid:batch_id>/", views.detail, name="detail"),
    path("imports/<uuid:batch_id>/commit/", views.commit, name="commit"),
    path("imports/<uuid:batch_id>/rollback/", views.rollback, name="rollback"),
    path("imports/export/<slug:entity>.csv", views.export_file, name="export"),
]
