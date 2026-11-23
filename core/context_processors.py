"""Template values shared by every page."""

from django.conf import settings


def company(request):
    """The configured company, used for the name shown in the shell."""
    from identity.models import CompanySettings

    from core.graph_mail import graph_mail_configured

    return {
        "company": CompanySettings.objects.first(),
        "password_reset_enabled": settings.PASSWORD_RESET_ENABLED,
        "graph_mail_enabled": graph_mail_configured(),
        "app_version": settings.APP_VERSION,
    }
