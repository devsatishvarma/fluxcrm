"""First-run setup, authentication, and administration screens."""

import logging
from pathlib import Path
from smtplib import SMTPException
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.forms import (
    CompanySettingsForm,
    GlideLoginForm,
    GlidePasswordResetForm,
    SetupForm,
    UserCreateForm,
    UserEditForm,
)
from core.mfa import (
    clear_user_mfa,
    confirm_totp_enrollment,
    mfa_status_for_users,
    post_password_login_redirect,
    start_totp_enrollment,
    user_has_mfa,
    verify_mfa_token,
)
from core.notices import fail_with, failed, form_text, succeeded, validation_text
from core.policy import AccessDenied, allows, require_action, visible_user_ids
from core.services import (
    SetupAlreadyCompleted,
    create_standard_user,
    is_throttled,
    issue_on_screen_password_reset_link,
    record_attempt,
    send_user_password_reset,
    set_user_active,
    set_user_password,
    setup_first_administrator,
    update_company_settings,
    update_user,
)
from core.validation import add_form_errors
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
    form = GlideLoginForm(request, data=request.POST or None)
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
            return redirect(post_password_login_redirect(user))
        record_attempt("login", username)
        logger.info("Sign-in failed", extra={"outcome": "failure"})
    return render(request, "core/login.html", {"form": form})


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("core:login")


class ThrottledPasswordResetView(PasswordResetView):
    form_class = GlidePasswordResetForm
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("core:password_reset_done")

    def dispatch(self, request, *args, **kwargs):
        if not settings.PASSWORD_RESET_ENABLED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

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


class GlidePasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"

    def dispatch(self, request, *args, **kwargs):
        if not settings.PASSWORD_RESET_ENABLED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class GlidePasswordResetConfirmView(PasswordResetConfirmView):
    """Accepts email-sent and Super Admin on-screen reset links (D-055 / 10A)."""

    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("core:password_reset_complete")

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        response["Cache-Control"] = "no-store, max-age=0"
        response["Pragma"] = "no-cache"
        return response


class GlidePasswordResetCompleteView(PasswordResetCompleteView):
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
def settings_home(request: HttpRequest) -> HttpResponse:
    return render(request, "core/settings.html")


@login_required
def help_page(request: HttpRequest) -> HttpResponse:
    return render(request, "core/help.html")


@login_required
def company_settings(request: HttpRequest) -> HttpResponse:
    try:
        require_action(request.user, "settings", "A")
    except AccessDenied:
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
        succeeded(request, "Company settings saved.")
        return redirect("core:company_settings")
    if request.method == "POST":
        fail_with(request, "Could not save company settings.", form_text(form))
    return render(request, "core/company_settings.html", {"form": form})


def brand_logo(request: HttpRequest) -> FileResponse:
    """The GlideCRM mark. It is not the company logo stored in settings."""
    path = Path(settings.BASE_DIR) / "core" / "static" / "brand" / "glidecrm-logo.png"
    response = FileResponse(path.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


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
    if not (allows(request.user, "user", "R") or allows(request.user, "user", "A")):
        try:
            require_action(request.user, "user", "R")
        except AccessDenied:
            return HttpResponse(status=403)
    users = User.objects.select_related("role", "manager", "team").order_by(
        "display_name"
    )
    visible = visible_user_ids(request.user)
    if visible is not None:
        users = users.filter(pk__in=visible)
    managers = User.objects.filter(is_active=True).order_by("display_name")
    if visible is not None:
        managers = managers.filter(pk__in=visible)
    user_rows = list(users)
    mfa_enrolled = mfa_status_for_users([account.pk for account in user_rows])
    for account in user_rows:
        account.mfa_enrolled = mfa_enrolled.get(account.pk, False)
    return render(
        request,
        "core/user_list.html",
        {
            "users": user_rows,
            "can_administer": allows(request.user, "user", "A"),
            "can_create_users": request.user.is_super_admin,
            "managers": managers,
        },
    )


@login_required
def user_create(request: HttpRequest) -> HttpResponse:
    if not request.user.is_super_admin:
        return HttpResponse(status=403)
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_standard_user(
                actor=request.user,
                user_data=form.cleaned_data,
                password=form.cleaned_data.get("password"),
                invite=form.cleaned_data["send_invitation"],
                request=request,
                request_id=getattr(request, "request_id", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            fail_with(request, "Could not add the user.", validation_text(exc))
        except (OSError, SMTPException):
            logger.exception(
                "User invitation delivery failed",
                extra={"outcome": "failure"},
            )
            form.add_error(
                None,
                "The invitation could not be delivered. No user was created.",
            )
            failed(
                request,
                "Could not add the user. The invitation could not be delivered. "
                "No user was created.",
            )
        else:
            succeeded(request, f"User {form.cleaned_data['display_name']} added.")
            return redirect("core:user_list")
    elif request.method == "POST":
        fail_with(request, "Could not add the user.", form_text(form))
    return render(request, "core/user_form.html", {"form": form})


@login_required
def user_edit(request: HttpRequest, user_id: int) -> HttpResponse:
    try:
        require_action(request.user, "user", "A")
    except AccessDenied:
        return HttpResponse(status=403)
    account = get_object_or_404(
        User.objects.select_related("role", "manager", "team"),
        pk=user_id,
    )
    if account.role.key == "SUPER_ADMIN" and not request.user.is_super_admin:
        return HttpResponse(status=403)
    form = UserEditForm(request.POST or None, instance=account, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            update_user(
                actor=request.user,
                user=account,
                display_name=form.cleaned_data["display_name"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                role=form.cleaned_data["role"],
                manager=form.cleaned_data["manager"],
                team=form.cleaned_data["team"],
                request_id=getattr(request, "request_id", ""),
            )
            if form.cleaned_data.get("password"):
                set_user_password(
                    actor=request.user,
                    user=account,
                    password=form.cleaned_data["password"],
                    request_id=getattr(request, "request_id", ""),
                )
        except ValidationError as exc:
            add_form_errors(form, exc)
            fail_with(request, "Could not save the user.", validation_text(exc))
        else:
            succeeded(request, f"User {account.display_name} saved.")
            return redirect("core:user_list")
    elif request.method == "POST":
        fail_with(request, "Could not save the user.", form_text(form))
    return render(
        request,
        "core/user_form.html",
        {"form": form, "editing": account},
    )


@login_required
@require_POST
def user_set_active(request: HttpRequest, user_id: int) -> HttpResponse:
    try:
        require_action(request.user, "user", "A")
    except AccessDenied:
        return HttpResponse(status=403)
    user = get_object_or_404(User, pk=user_id)
    active = request.POST.get("active") == "1"
    reassign_to = None
    raw_reassign = request.POST.get("reassign_to")
    if raw_reassign:
        reassign_to = User.objects.filter(pk=raw_reassign, is_active=True).first()
    try:
        set_user_active(
            actor=request.user,
            user=user,
            active=active,
            reassign_to=reassign_to,
            request_id=getattr(request, "request_id", ""),
        )
    except ValidationError as exc:
        failed(request, f"Could not change the user. {exc.messages[0]}")
        return render(
            request,
            "core/user_list.html",
            {
                "users": User.objects.select_related("role", "manager"),
                "error": exc.messages[0],
                "can_administer": True,
            },
            status=422,
        )
    if active:
        succeeded(request, f"User {user.display_name} enabled.")
    else:
        succeeded(request, f"User {user.display_name} disabled.")
    return redirect("core:user_list")


@login_required
@require_POST
def user_send_password_reset(request: HttpRequest, user_id: int) -> HttpResponse:
    if not request.user.is_super_admin:
        return HttpResponse(status=403)
    user = get_object_or_404(User, pk=user_id)
    try:
        send_user_password_reset(
            actor=request.user,
            user=user,
            request=request,
            request_id=getattr(request, "request_id", ""),
        )
    except ValidationError as exc:
        failed(request, f"Could not send the password reset. {exc.messages[0]}")
        return render(
            request,
            "core/user_list.html",
            {
                "users": User.objects.select_related("role", "manager"),
                "error": exc.messages[0],
                "can_administer": True,
            },
            status=422,
        )
    except (OSError, SMTPException):
        logger.exception(
            "Password reset delivery failed",
            extra={"outcome": "failure", "user_id": user.pk},
        )
        failed(
            request,
            "Could not send the password reset. The email could not be delivered.",
        )
        return render(
            request,
            "core/user_list.html",
            {
                "users": User.objects.select_related("role", "manager"),
                "error": "The password reset email could not be delivered.",
            },
            status=503,
        )
    succeeded(request, f"Password reset sent to {user.email}.")
    return redirect("core:user_list")


@login_required
@require_POST
def user_show_password_reset_link(request: HttpRequest, user_id: int) -> HttpResponse:
    if not request.user.is_super_admin:
        return HttpResponse(status=403)
    user = get_object_or_404(
        User.objects.select_related("role"),
        pk=user_id,
    )
    try:
        reset_url = issue_on_screen_password_reset_link(
            actor=request.user,
            user=user,
            request=request,
            request_id=getattr(request, "request_id", ""),
        )
    except ValidationError as exc:
        failed(request, f"Could not create the password reset link. {exc.messages[0]}")
        return render(
            request,
            "core/user_list.html",
            {
                "users": User.objects.select_related("role", "manager", "team"),
                "error": exc.messages[0],
                "can_administer": True,
                "can_create_users": True,
                "managers": User.objects.filter(is_active=True).order_by(
                    "display_name"
                ),
            },
            status=422,
        )
    response = render(
        request,
        "core/user_password_reset_link.html",
        {"account": user, "reset_url": reset_url},
    )
    response["Cache-Control"] = "no-store, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@login_required
def mfa_verify(request: HttpRequest) -> HttpResponse:
    if not user_has_mfa(request.user):
        return redirect("core:mfa_enroll")
    if getattr(request.user, "is_verified", lambda: False)():
        return redirect("core:home")
    error = ""
    if request.method == "POST":
        subject = str(request.user.pk)
        if is_throttled("mfa_verify", subject):
            logger.info("MFA verification throttled", extra={"outcome": "throttled"})
            return render(
                request,
                "core/mfa_verify.html",
                {"error": "Too many attempts. Wait and try again.", "throttled": True},
                status=429,
            )
        try:
            verify_mfa_token(
                user=request.user,
                token=request.POST.get("token", ""),
                request=request,
                request_id=getattr(request, "request_id", ""),
            )
        except ValidationError as exc:
            error = exc.messages[0]
            record_attempt("mfa_verify", subject)
            logger.info("MFA verification failed", extra={"outcome": "failure"})
        else:
            return redirect("core:home")
    return render(request, "core/mfa_verify.html", {"error": error})


@login_required
def mfa_enroll(request: HttpRequest) -> HttpResponse:
    if user_has_mfa(request.user):
        return redirect("core:mfa_verify")
    error = ""
    if request.method == "POST":
        try:
            backup_codes = confirm_totp_enrollment(
                user=request.user,
                token=request.POST.get("token", ""),
                request=request,
                request_id=getattr(request, "request_id", ""),
            )
        except ValidationError as exc:
            error = exc.messages[0]
        else:
            request.session["mfa_backup_codes"] = backup_codes
            return redirect("core:mfa_backup_codes")
    enrollment = start_totp_enrollment(
        user=request.user,
        request_id=getattr(request, "request_id", ""),
    )
    return render(
        request,
        "core/mfa_enroll.html",
        {
            "error": error,
            "qr_data_uri": enrollment["qr_data_uri"],
            "secret": enrollment["secret"],
        },
    )


@login_required
def mfa_backup_codes(request: HttpRequest) -> HttpResponse:
    codes = request.session.pop("mfa_backup_codes", None)
    if not codes:
        return redirect("core:home")
    return render(request, "core/mfa_backup_codes.html", {"codes": codes})


@login_required
@require_POST
def user_clear_mfa(request: HttpRequest, user_id: int) -> HttpResponse:
    if not request.user.is_super_admin:
        return HttpResponse(status=403)
    user = get_object_or_404(User, pk=user_id)
    try:
        clear_user_mfa(
            actor=request.user,
            user=user,
            request_id=getattr(request, "request_id", ""),
        )
    except ValidationError as exc:
        failed(request, f"Could not clear MFA. {exc.messages[0]}")
        return redirect("core:user_list")
    succeeded(
        request,
        f"Authenticator cleared for {user.display_name}. They must enroll again.",
    )
    return redirect("core:user_list")
