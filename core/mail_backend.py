"""Django email backend that sends through Microsoft Graph shared mailbox."""

from django.core.mail.backends.base import BaseEmailBackend

from core.graph_mail import send_graph_mail


class GraphSharedMailboxBackend(BaseEmailBackend):
    """Use for invitations and password-reset when Graph mail is configured."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        sent = 0
        for message in email_messages:
            recipients = list(message.to) + list(message.cc) + list(message.bcc)
            try:
                send_graph_mail(
                    to_addresses=recipients,
                    subject=message.subject or "",
                    body_text=message.body or "",
                )
            except Exception:
                if not self.fail_silently:
                    raise
                continue
            sent += 1
        return sent
