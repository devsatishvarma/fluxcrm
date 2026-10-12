"""First-run setup, authentication, and administration screens."""

import logging
from zoneinfo import ZoneInfo

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import CompanySettingsForm, FluxLoginForm, SetupForm, UserCreateForm
from core.services import (
    SetupAlreadyCompleted,
    create_standard_user,
    is_throttled,
    record_attempt,
    set_user_active,
    setup_first_administrator,
    update_company_settings,
)
from identity.models import CompanySettings, User

logger = logging.getLogger(__name__)


def setup(request: HttpRequest) -> HttpResponse:
    if User.objects.exists():
        return redirect("core:login")
    form = SetupForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            setup_first_administrator(
                profile=form.company_profile(),
                admin_user={
                    "username": form.cleaned_data["admin_username"],
                    "email": form.cleaned_data["admin_email"],
                    "display_name": form.cleaned_data["admin_display_name"],
                },
                password=form.cleaned_data["password"],
                request_id=getattr(request, "request_id", ""),
            )
        except SetupAlreadyCompleted:
            return redirect("core:login")
        except ValidationError as exc:
            form.add_error("password", exc)
        else:
            logger.info("Initial administrator created", extra={"outcome": "success"})
            return redirect("core:login")
    return render(request, "core/setup.html", {"form": form})


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("core:home")
    form = FluxLoginForm(request, data=request.POST or None)
    if request.method == "POST":
        username = request.POST.get("username", "")
        if is_throttled("login", username):
            logger.info("Sign-in throttled", extra={"outcome": "throttled"})
            return render(
                request,
                "core/login.html",
                {"form": form, "throttled": True},
                status=429,
            )
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            user.last_seen_at = timezone.now()
            user.save(update_fields=("last_seen_at",))
            logger.info(
                "Sign-in succeeded",
                extra={"outcome": "success", "user_id": user.pk},
            )
            return redirect("core:home")
        record_attempt("login", username)
        logger.info("Sign-in failed", extra={"outcome": "failure"})
    return render(request, "core/login.html", {"form": form})


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("core:login")


class ThrottledPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("core:password_reset_done")

    def post(self, request, *args, **kwargs):
        email = request.POST.get("email", "")
        if is_throttled("password_reset", email):
            logger.info("Password reset throttled", extra={"outcome": "throttled"})
            return render(
                request,
                self.template_name,
                {"form": self.get_form(), "throttled": True},
                status=429,
            )
        record_attempt("password_reset", email)
        logger.info("Password reset requested", extra={"outcome": "requested"})
        return super().post(request, *args, **kwargs)


class FluxPasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


class FluxPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("core:password_reset_complete")


class FluxPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"


@login_required
def home(request: HttpRequest) -> HttpResponse:
    company = CompanySettings.objects.first()
    zone_name = request.user.timezone or (
        company.default_timezone if company else "America/Los_Angeles"
    )
    timezone.activate(ZoneInfo(zone_name))
    local_now = timezone.localtime()
    return render(
        request,
        "core/home.html",
        {"company": company, "local_now": local_now, "timezone_name": zone_name},
    )


@login_required
def company_settings(request: HttpRequest) -> HttpResponse:
    if not request.user.is_company_admin:
        return HttpResponse(status=403)
    company = get_object_or_404(CompanySettings, singleton=True)
    form = CompanySettingsForm(
        request.POST or None,
        request.FILES or None,
        instance=company,
    )
    if request.method == "POST" and form.is_valid():
        update_company_settings(
            actor=request.user,
            company=company,
            changes=form.profile_changes(),
            request_id=getattr(request, "request_id", ""),
        )
        return redirect("core:company_settings")
    return render(request, "core/company_settings.html", {"form": form})


@login_required
def company_logo(request: HttpRequest) -> FileResponse:
    company = get_object_or_404(CompanySettings, singleton=True)
    if not company.logo:
        return HttpResponse(status=404)
    response = FileResponse(
        company.logo.open("rb"), content_type="application/octet-stream"
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    return response


@login_required
def user_list(request: HttpRequest) -> HttpResponse:
    if not request.user.is_company_admin:
        return HttpResponse(status=403)
    return render(
        request,
        "core/user_list.html",
        {
            "users": User.objects.select_related("role", "manager").order_by(
                "display_name"
            )
        },
    )


@login_required
def user_create(request: HttpRequest) -> HttpResponse:
    if not request.user.is_company_admin:
        return HttpResponse(status=403)
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_standard_user(
                actor=request.user,
                user_data=form.cleaned_data,
                password=form.cleaned_data["password"],
                request_id=getattr(request, "request_id", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("core:user_list")
    return render(request, "core/user_form.html", {"form": form})


@login_required
@require_POST
def user_set_active(request: HttpRequest, user_id: int) -> HttpResponse:
    if not request.user.is_company_admin:
        return HttpResponse(status=403)
    user = get_object_or_404(User, pk=user_id)
    active = request.POST.get("active") == "1"
    try:
        set_user_active(
            actor=request.user,
            user=user,
            active=active,
            request_id=getattr(request, "request_id", ""),
        )
    except ValidationError as exc:
        return render(
            request,
            "core/user_list.html",
            {
                "users": User.objects.select_related("role", "manager"),
                "error": exc.messages[0],
            },
            status=422,
        )
    return redirect("core:user_list")
