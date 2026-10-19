"""
URL configuration for glidecrm project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import include, path

from core.access_api import AuditEventListView, ExportView, ImportAuthorizeView

urlpatterns = [
    path("", include("core.urls")),
    path("", include("leads.urls")),
    path("", include("sales.urls")),
    path("", include("activities.urls")),
    path("", include("accounts.urls")),
    path("", include("reporting.urls")),
    path("", include("imports.urls")),
    path("api/v1/", include("leads.api_urls")),
    path("api/v1/", include("sales.api_urls")),
    path("api/v1/", include("activities.api_urls")),
    path("api/v1/", include("accounts.api_urls")),
    path("api/v1/audit-events/", AuditEventListView.as_view(), name="api-audit"),
    path("api/v1/exports/", ExportView.as_view(), name="api-export"),
    path(
        "api/v1/imports/authorize/",
        ImportAuthorizeView.as_view(),
        name="api-import-authorize",
    ),
]
