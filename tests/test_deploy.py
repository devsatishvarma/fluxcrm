from django.core.management import call_command
from django.test import override_settings

RELEASE_SECRET = "glidecrm-release-profile-secret-key-with-mixed-characters-9f3c"


@override_settings(
    DEBUG=False,
    SECRET_KEY=RELEASE_SECRET,
    ALLOWED_HOSTS=["crm.example.test"],
    CSRF_TRUSTED_ORIGINS=["https://crm.example.test"],
    SECURE_SSL_REDIRECT=True,
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    SECURE_HSTS_SECONDS=31536000,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
    SECURE_HSTS_PRELOAD=True,
    SECURE_REFERRER_POLICY="same-origin",
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
def test_release_profile_passes_deploy_checks():
    call_command("check", deploy=True)
