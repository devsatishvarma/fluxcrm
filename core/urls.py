from django.urls import path

from core import access_views, identity_views, views

app_name = "core"

urlpatterns = [
    path("", identity_views.home, name="home"),
    path("health/", views.health, name="health"),
    path("ready/", views.readiness, name="readiness"),
    path("setup/", identity_views.setup, name="setup"),
    path("login/", identity_views.login_view, name="login"),
    path("logout/", identity_views.logout_view, name="logout"),
    path(
        "password-reset/",
        identity_views.ThrottledPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        identity_views.FluxPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        identity_views.FluxPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        identity_views.FluxPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("settings/", identity_views.settings_home, name="settings"),
    path("help/", identity_views.help_page, name="help"),
    path("company/", identity_views.company_settings, name="company_settings"),
    path("company/logo/", identity_views.company_logo, name="company_logo"),
    path("users/", identity_views.user_list, name="user_list"),
    path("users/new/", identity_views.user_create, name="user_create"),
    path(
        "users/<int:user_id>/active/",
        identity_views.user_set_active,
        name="user_set_active",
    ),
    path(
        "users/<int:user_id>/password-reset/",
        identity_views.user_send_password_reset,
        name="user_send_password_reset",
    ),
    path(
        "users/<int:user_id>/manager/",
        access_views.user_manager,
        name="user_manager",
    ),
    path(
        "users/administrators/",
        access_views.administrator_review,
        name="administrator_review",
    ),
    path("teams/", access_views.team_list, name="teams"),
    path("teams/new/", access_views.team_edit, name="team_create"),
    path("teams/<int:team_id>/", access_views.team_edit, name="team_edit"),
    path("roles/", access_views.role_list, name="roles"),
    path("roles/<int:role_id>/", access_views.role_edit, name="role_edit"),
    path("audit/", access_views.audit_list, name="audit"),
    path("exports/", access_views.export_request, name="export"),
    path("imports/authorize/", access_views.import_authorize, name="import_authorize"),
]
