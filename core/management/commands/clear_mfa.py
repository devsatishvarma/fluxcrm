"""Break-glass: clear TOTP/backup devices when a Super Admin is locked out."""

from django.core.management.base import BaseCommand, CommandError

from core.mfa import clear_user_mfa
from identity.models import User


class Command(BaseCommand):
    help = (
        "Remove authenticator and backup codes for a user so they can enroll "
        "again at the next sign-in. Use when no Super Admin can open Clear MFA."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "username",
            help="Login username of the account to clear (for example satish).",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required confirmation flag.",
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            raise CommandError("Refusing to clear MFA without --yes.")
        username = options["username"]
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"No user named {username!r}.")
        actor = (
            User.objects.filter(role__key="SUPER_ADMIN", is_active=True)
            .exclude(pk=user.pk)
            .first()
        )
        if actor is None:
            actor = user if user.is_super_admin else None
        if actor is None or not actor.is_super_admin:
            raise CommandError(
                "A Super Admin account is required to authorize this clear."
            )
        from django.core.exceptions import ValidationError

        try:
            clear_user_mfa(actor=actor, user=user, request_id="mgmt-clear-mfa")
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Cleared MFA for {user.username}. They must enroll at next sign-in."
            )
        )
