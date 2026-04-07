"""Microsoft Graph API adapter for email ingestion.

Uses MSAL for OAuth2 client_credentials flow to authenticate
with Microsoft Graph. Fetches emails from the shared mailbox
and sends emails via the /sendMail endpoint.

Auth credentials come from env vars:
  - GRAPH_API_TENANT_ID
  - GRAPH_API_CLIENT_ID
  - GRAPH_API_CLIENT_SECRET
  - GRAPH_API_MAILBOX

Corresponds to Steps E1-E2 (email fetch) and Steps 12A/12B
(email send) in the VQMS Solution Flow Document.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
import msal

from config.settings import get_settings
from src.models.email import EmailAttachment, EmailMessage

logger = logging.getLogger(__name__)

# Microsoft Graph API base URL
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Lazy-initialized MSAL confidential client and token cache
_msal_app = None
_access_token: str | None = None
_token_expires_at: datetime | None = None


def _get_msal_app():
    """Get or create the MSAL ConfidentialClientApplication.

    Uses the client_credentials flow for daemon/service auth.
    No user interaction required.
    """
    global _msal_app  # noqa: PLW0603
    if _msal_app is None:
        settings = get_settings()
        authority = f"https://login.microsoftonline.com/{settings.graph_api_tenant_id}"
        _msal_app = msal.ConfidentialClientApplication(
            client_id=settings.graph_api_client_id,
            client_credential=settings.graph_api_client_secret,
            authority=authority,
        )
    return _msal_app


def _get_access_token() -> str:
    """Acquire an access token for Microsoft Graph.

    Uses cached token if not expired, otherwise acquires a new one.
    The client_credentials flow returns tokens valid for ~60 minutes.
    """
    global _access_token, _token_expires_at  # noqa: PLW0603

    # Return cached token if still valid (with 5-min buffer)
    if _access_token and _token_expires_at:
        from datetime import timedelta

        if datetime.now(UTC) < _token_expires_at - timedelta(minutes=5):
            return _access_token

    app = _get_msal_app()
    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_for_client(scopes=scopes)

    if "access_token" not in result:
        error_desc = result.get("error_description", "Unknown error")
        logger.error(
            "MSAL token acquisition failed",
            extra={"error": result.get("error"), "description": error_desc},
        )
        raise PermissionError(f"Failed to acquire Graph API token: {error_desc}")

    _access_token = result["access_token"]

    # Token typically expires in 3600 seconds
    from datetime import timedelta

    expires_in = result.get("expires_in", 3600)
    _token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

    logger.info("Acquired new Graph API access token")
    return _access_token


def _auth_headers() -> dict[str, str]:
    """Build authorization headers for Graph API requests."""
    token = _get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def validate_webhook_subscription(validation_token: str) -> str:
    """Handle Graph API subscription validation request.

    When Microsoft Graph sets up a webhook subscription, it sends
    a validation request with a token. We must echo the token back
    as plain text to confirm the subscription.

    Args:
        validation_token: The token Microsoft Graph sends for validation.

    Returns:
        The same validation_token string (echoed back).
    """
    logger.info("Validating Graph webhook subscription")
    return validation_token


async def fetch_email_by_resource(
    resource: str,
    *,
    correlation_id: str | None = None,
) -> EmailMessage:
    """Fetch an email from Exchange Online by its Graph resource path.

    Calls GET /users/{mailbox}/messages/{id} to retrieve the email
    message, including sender, subject, body, and attachments.

    Args:
        resource: Graph API resource path (e.g., "messages/AAMk...").
        correlation_id: Tracing ID for this request.

    Returns:
        EmailMessage with parsed email data.

    Raises:
        httpx.HTTPStatusError: If Graph API returns an error.
        PermissionError: If MSAL token acquisition fails.
    """
    settings = get_settings()
    headers = _auth_headers()

    # Build the full Graph API URL
    # Resource from webhook is like "Users/{user-id}/Messages/{msg-id}"
    # We normalize it to use the mailbox setting
    if resource.lower().startswith("users/"):
        url = f"{GRAPH_BASE_URL}/{resource}"
    else:
        url = f"{GRAPH_BASE_URL}/users/{settings.graph_api_mailbox}/{resource}"

    logger.info(
        "Fetching email from Graph API",
        extra={"url": url, "correlation_id": correlation_id},
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    # Parse the Graph API response into our EmailMessage model
    sender = data.get("from", {}).get("emailAddress", {})

    # Extract To and CC recipients from Graph API response
    to_addresses = _extract_recipient_emails(data.get("toRecipients", []))
    cc_addresses = _extract_recipient_emails(data.get("ccRecipients", []))

    # Fetch attachments with content (for S3 upload)
    attachments = []
    if data.get("hasAttachments", False):
        attachments = await _fetch_attachments_with_content(
            url, headers=headers, correlation_id=correlation_id
        )

    # Detect auto-reply from Graph API fields
    is_auto_reply = _detect_auto_reply(data)

    # Body preview from Graph API (first ~255 chars)
    body_preview = data.get("bodyPreview", "")

    return EmailMessage(
        message_id=data.get("internetMessageId", data.get("id", "")),
        conversation_id=data.get("conversationId"),
        in_reply_to=_find_header(data, "In-Reply-To"),
        references=_parse_references(data),
        sender_email=sender.get("address", ""),
        sender_name=sender.get("name"),
        recipients=to_addresses + cc_addresses,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        subject=data.get("subject", ""),
        body_text=data.get("body", {}).get("content", "")
        if data.get("body", {}).get("contentType") == "text"
        else _strip_html(data.get("body", {}).get("content", "")),
        body_html=data.get("body", {}).get("content")
        if data.get("body", {}).get("contentType") == "html"
        else None,
        body_preview=body_preview[:200] if body_preview else None,
        received_at=_parse_datetime(data.get("receivedDateTime")),
        attachments=attachments,
        is_auto_reply=is_auto_reply,
    )


async def fetch_latest_email(
    *,
    correlation_id: str | None = None,
) -> EmailMessage | None:
    """Fetch the most recent email from the shared mailbox.

    Calls GET /users/{mailbox}/messages?$top=1&$orderby=receivedDateTime desc
    to get the latest email. Useful for testing the pipeline after
    manually sending an email to the mailbox.

    Args:
        correlation_id: Tracing ID for this request.

    Returns:
        EmailMessage for the latest email, or None if mailbox is empty.

    Raises:
        httpx.HTTPStatusError: If Graph API returns an error.
        PermissionError: If MSAL token acquisition fails.
    """
    settings = get_settings()
    headers = _auth_headers()

    url = (
        f"{GRAPH_BASE_URL}/users/{settings.graph_api_mailbox}/messages"
        "?$top=1&$orderby=receivedDateTime desc"
    )

    logger.info(
        "Fetching latest email from mailbox",
        extra={
            "mailbox": settings.graph_api_mailbox,
            "correlation_id": correlation_id,
        },
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    messages = data.get("value", [])
    if not messages:
        logger.info("Mailbox is empty -- no messages found")
        return None

    msg = messages[0]

    # Parse sender
    sender = msg.get("from", {}).get("emailAddress", {})

    # Extract To and CC recipients
    to_addresses = _extract_recipient_emails(msg.get("toRecipients", []))
    cc_addresses = _extract_recipient_emails(msg.get("ccRecipients", []))

    # Fetch attachments with content if present
    attachments = []
    if msg.get("hasAttachments", False):
        msg_url = f"{GRAPH_BASE_URL}/users/{settings.graph_api_mailbox}/messages/{msg['id']}"
        attachments = await _fetch_attachments_with_content(
            msg_url, headers=headers, correlation_id=correlation_id
        )

    # Detect auto-reply
    is_auto_reply = _detect_auto_reply(msg)

    # Body preview
    body_preview = msg.get("bodyPreview", "")

    return EmailMessage(
        message_id=msg.get("internetMessageId", msg.get("id", "")),
        conversation_id=msg.get("conversationId"),
        in_reply_to=_find_header(msg, "In-Reply-To"),
        references=_parse_references(msg),
        sender_email=sender.get("address", ""),
        sender_name=sender.get("name"),
        recipients=to_addresses + cc_addresses,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        subject=msg.get("subject", ""),
        body_text=msg.get("body", {}).get("content", "")
        if msg.get("body", {}).get("contentType") == "text"
        else _strip_html(msg.get("body", {}).get("content", "")),
        body_html=msg.get("body", {}).get("content")
        if msg.get("body", {}).get("contentType") == "html"
        else None,
        body_preview=body_preview[:200] if body_preview else None,
        received_at=_parse_datetime(msg.get("receivedDateTime")),
        attachments=attachments,
        is_auto_reply=is_auto_reply,
    )


async def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    *,
    correlation_id: str | None = None,
) -> bool:
    """Send an email via Microsoft Graph API /sendMail.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        body_html: Email body in HTML format.
        correlation_id: Tracing ID for this request.

    Returns:
        True if the email was sent successfully.

    Raises:
        httpx.HTTPStatusError: If Graph API returns an error.
    """
    settings = get_settings()
    headers = _auth_headers()

    url = f"{GRAPH_BASE_URL}/users/{settings.graph_api_mailbox}/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [
                {"emailAddress": {"address": to_email}},
            ],
        },
    }

    logger.info(
        "Sending email via Graph API",
        extra={
            "to": to_email,
            "subject": subject,
            "correlation_id": correlation_id,
        },
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url, headers=headers, json=payload, timeout=30.0
        )
        response.raise_for_status()

    logger.info(
        "Email sent successfully",
        extra={"to": to_email, "correlation_id": correlation_id},
    )
    return True


# --- Helper Functions ---


async def _fetch_attachments_with_content(
    message_url: str,
    *,
    headers: dict[str, str],
    correlation_id: str | None = None,
) -> list[EmailAttachment]:
    """Fetch attachments including their content bytes from Graph API.

    Graph API returns attachment content as base64-encoded in the
    'contentBytes' field when requesting /attachments. We decode
    it and store it in EmailAttachment.content_bytes so the intake
    service can upload it to S3.
    """
    import base64

    url = f"{message_url}/attachments"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()

        attachments = []
        for att in data.get("value", []):
            # Graph API returns contentBytes as base64 for file attachments
            content_b64 = att.get("contentBytes")
            content_bytes = None
            if content_b64:
                try:
                    content_bytes = base64.b64decode(content_b64)
                except Exception:
                    logger.warning(
                        "Failed to decode attachment content",
                        extra={
                            "attachment_name": att.get("name"),
                            "correlation_id": correlation_id,
                        },
                    )

            attachments.append(
                EmailAttachment(
                    filename=att.get("name", "unknown"),
                    content_type=att.get("contentType", "application/octet-stream"),
                    size_bytes=att.get("size", 0),
                    s3_key=None,
                    content_bytes=content_bytes,
                )
            )

        logger.info(
            "Fetched attachments with content",
            extra={
                "count": len(attachments),
                "with_content": sum(1 for a in attachments if a.content_bytes),
                "correlation_id": correlation_id,
            },
        )
        return attachments
    except Exception:
        logger.warning(
            "Failed to fetch attachments",
            extra={"correlation_id": correlation_id},
            exc_info=True,
        )
        return []


def _extract_recipient_emails(recipients: list[dict]) -> list[str]:
    """Extract email addresses from Graph API recipient list.

    Graph API returns recipients as:
    [{"emailAddress": {"name": "...", "address": "user@example.com"}}]
    """
    return [
        r.get("emailAddress", {}).get("address", "")
        for r in recipients
        if r.get("emailAddress", {}).get("address")
    ]


def _detect_auto_reply(data: dict) -> bool:
    """Detect if an email is an auto-reply (OOF, read receipt, etc.).

    Graph API provides several signals:
      - isReadReceiptRequested / isDeliveryReceiptRequested
      - inferenceClassification == "focused" vs "other"
      - Auto-Reply header in internetMessageHeaders
      - Subject starting with "Automatic reply:" or "Out of Office:"
    """
    # Check common auto-reply headers
    auto_reply_header = _find_header(data, "X-Auto-Response-Suppress")
    if auto_reply_header:
        return True

    auto_submitted = _find_header(data, "Auto-Submitted")
    if auto_submitted and auto_submitted.lower() != "no":
        return True

    # Check subject patterns
    subject = data.get("subject", "").lower()
    auto_reply_prefixes = [
        "automatic reply:",
        "out of office:",
        "auto-reply:",
        "autoreply:",
    ]
    if any(subject.startswith(prefix) for prefix in auto_reply_prefixes):
        return True

    return False


def _find_header(data: dict, header_name: str) -> str | None:
    """Find a specific internet message header in Graph API response."""
    headers = data.get("internetMessageHeaders", [])
    for header in headers:
        if header.get("name", "").lower() == header_name.lower():
            return header.get("value")
    return None


def _parse_references(data: dict) -> list[str]:
    """Parse the References header into a list of message IDs."""
    refs = _find_header(data, "References")
    if not refs:
        return []
    # References header contains space-separated message IDs
    return [r.strip() for r in refs.split() if r.strip()]


def _parse_datetime(iso_string: str | None) -> datetime | None:
    """Parse an ISO datetime string from Graph API."""
    if not iso_string:
        return None
    try:
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _strip_html(html: str) -> str:
    """Simple HTML tag stripping for plain text extraction.

    This is a basic implementation. In Phase 8, we may use
    a proper HTML-to-text library like html2text or beautifulsoup.
    """
    import re

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def reset_auth() -> None:
    """Reset MSAL app and cached token. Used in tests."""
    global _msal_app, _access_token, _token_expires_at  # noqa: PLW0603
    _msal_app = None
    _access_token = None
    _token_expires_at = None
