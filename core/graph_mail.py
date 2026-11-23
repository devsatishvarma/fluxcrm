"""Microsoft Graph outbound mail from a shared mailbox (Phase 10C)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import msal
import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError

logger = logging.getLogger(__name__)

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/users/{mailbox}/sendMail"


@dataclass(frozen=True)
class GraphMailConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    shared_mailbox: str
    public_base_url: str


def graph_mail_configured() -> bool:
    return bool(
        getattr(settings, "AZURE_TENANT_ID", "")
        and getattr(settings, "AZURE_CLIENT_ID", "")
        and getattr(settings, "AZURE_CLIENT_SECRET", "")
        and getattr(settings, "GRAPH_SHARED_MAILBOX", "")
    )


def load_graph_mail_config() -> GraphMailConfig:
    if not graph_mail_configured():
        raise ImproperlyConfigured(
            "Microsoft Graph mail is not configured. Set AZURE_TENANT_ID, "
            "AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and GRAPH_SHARED_MAILBOX."
        )
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    if not base:
        raise ImproperlyConfigured(
            "PUBLIC_BASE_URL is required for CRM deep links in outbound mail."
        )
    return GraphMailConfig(
        tenant_id=settings.AZURE_TENANT_ID,
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET,
        shared_mailbox=settings.GRAPH_SHARED_MAILBOX,
        public_base_url=base,
    )


def absolute_crm_url(path: str) -> str:
    config = load_graph_mail_config()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{config.public_base_url}{path}"


def _access_token(config: GraphMailConfig) -> str:
    app = msal.ConfidentialClientApplication(
        config.client_id,
        authority=f"https://login.microsoftonline.com/{config.tenant_id}",
        client_credential=config.client_secret,
    )
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        error = result.get("error_description") or result.get("error") or "token_failed"
        logger.error(
            "Graph token acquisition failed",
            extra={"outcome": "failure", "error": str(error)[:200]},
        )
        raise ValidationError("Could not authenticate to Microsoft Graph for mail.")
    return result["access_token"]


def send_graph_mail(
    *,
    to_addresses: list[str],
    subject: str,
    body_text: str,
    request_id: str = "",
) -> None:
    """Send one message from the shared mailbox. Raises ValidationError on failure."""
    recipients = sorted({addr.strip().lower() for addr in to_addresses if addr.strip()})
    if not recipients:
        raise ValidationError("At least one recipient email is required.")
    config = load_graph_mail_config()
    token = _access_token(config)
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "toRecipients": [
                {"emailAddress": {"address": address}} for address in recipients
            ],
        },
        "saveToSentItems": True,
    }
    url = GRAPH_SEND_URL.format(mailbox=config.shared_mailbox)
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code not in {202, 200}:
        logger.error(
            "Graph sendMail failed",
            extra={
                "outcome": "failure",
                "http_status": response.status_code,
                "request_id": request_id or "-",
            },
        )
        raise ValidationError("The email could not be delivered through Microsoft 365.")
    logger.info(
        "Graph mail sent",
        extra={
            "outcome": "success",
            "recipient_count": len(recipients),
            "request_id": request_id or "-",
        },
    )


def send_crm_mail(
    *,
    to_addresses: list[str],
    subject: str,
    body_text: str,
    request_id: str = "",
) -> None:
    """Send via Graph when configured; otherwise raise a clear configuration error."""
    if not graph_mail_configured():
        raise ValidationError(
            "Outbound CRM email is off until the Microsoft shared mailbox "
            "is configured."
        )
    send_graph_mail(
        to_addresses=to_addresses,
        subject=subject,
        body_text=body_text,
        request_id=request_id,
    )
