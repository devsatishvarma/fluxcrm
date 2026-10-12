from django.urls import path

from core import identity_views, views

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
]
