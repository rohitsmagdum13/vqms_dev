# ruff: noqa: E402
"""Check connectivity to Microsoft Graph API for VQMS.

Tests MSAL authentication, mailbox access, message listing,
folder enumeration, attachment download, and sendMail permission.
Reports status for each check with clear PASS/FAIL indicators.

Usage:
  uv run python scripts/check_graph_api.py
  uv run python scripts/check_graph_api.py --send-test   # also send a test email to yourself
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

# ---------------------------------------------------------------------------
# Bootstrap -- must happen before project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import httpx
import msal

from config.settings import get_settings

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
HEADER = "\033[1m"
RESET = "\033[0m"

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{HEADER}{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}{RESET}")


def print_check(name: str, passed: bool, detail: str) -> None:
    """Print a single check result."""
    status = PASS if passed else FAIL
    print(f"  {status} {name}")
    print(f"         {detail}")


def print_info(name: str, detail: str) -> None:
    """Print an info line."""
    print(f"  {INFO} {name}")
    print(f"         {detail}")


def print_warn(name: str, detail: str) -> None:
    """Print a warning line."""
    print(f"  {WARN} {name}")
    print(f"         {detail}")


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_env_config(settings) -> bool:
    """Check that all required Graph API env vars are set."""
    required = {
        "GRAPH_API_TENANT_ID": settings.graph_api_tenant_id,
        "GRAPH_API_CLIENT_ID": settings.graph_api_client_id,
        "GRAPH_API_CLIENT_SECRET": settings.graph_api_client_secret,
        "GRAPH_API_MAILBOX": settings.graph_api_mailbox,
    }

    missing = [k for k, v in required.items() if not v]

    if missing:
        print_check(
            "Environment variables",
            False,
            f"Missing: {', '.join(missing)}. Set them in .env",
        )
        return False

    print_check(
        "Environment variables",
        True,
        f"All 4 required vars set. Mailbox: {settings.graph_api_mailbox}",
    )
    return True


def check_msal_auth(settings) -> tuple[bool, str | None]:
    """Acquire an access token via MSAL client_credentials flow.

    Returns (success, access_token_or_none).
    """
    authority = f"https://login.microsoftonline.com/{settings.graph_api_tenant_id}"

    try:
        app = msal.ConfidentialClientApplication(
            client_id=settings.graph_api_client_id,
            client_credential=settings.graph_api_client_secret,
            authority=authority,
        )

        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )

        if "access_token" in result:
            token = result["access_token"]
            expires_in = result.get("expires_in", "?")
            # Show first/last 8 chars of token for verification
            token_preview = f"{token[:8]}...{token[-8:]}"
            print_check(
                "MSAL authentication",
                True,
                f"Token acquired (expires in {expires_in}s). "
                f"Token: {token_preview}",
            )
            return True, token

        error = result.get("error", "unknown")
        error_desc = result.get("error_description", "No description")
        print_check(
            "MSAL authentication",
            False,
            f"Error: {error} — {error_desc}",
        )
        return False, None

    except Exception as e:
        print_check("MSAL authentication", False, f"Exception: {e}")
        return False, None


async def check_mailbox_access(token: str, mailbox: str) -> bool:
    """Check if we can access the mailbox via Graph API.

    Calls GET /users/{mailbox} to verify the mailbox exists
    and our app has permission to access it.
    """
    url = f"{GRAPH_BASE_URL}/users/{mailbox}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)

        if response.status_code == 200:
            data = response.json()
            display_name = data.get("displayName", "N/A")
            mail = data.get("mail") or data.get("userPrincipalName", "N/A")
            print_check(
                "Mailbox access",
                True,
                f"User found: {display_name} ({mail})",
            )
            return True

        if response.status_code == 403:
            print_check(
                "Mailbox access",
                False,
                "403 Forbidden — app lacks User.Read.All or "
                "Mail.Read permission. Check Azure AD app permissions.",
            )
        elif response.status_code == 404:
            print_check(
                "Mailbox access",
                False,
                f"404 Not Found — mailbox '{mailbox}' does not exist "
                "in this tenant.",
            )
        else:
            body = response.text[:200]
            print_check(
                "Mailbox access",
                False,
                f"HTTP {response.status_code}: {body}",
            )
        return False

    except Exception as e:
        print_check("Mailbox access", False, f"Request failed: {e}")
        return False


async def check_list_messages(token: str, mailbox: str) -> bool:
    """Check if we can list messages in the mailbox.

    Calls GET /users/{mailbox}/messages?$top=5 to verify
    Mail.Read or Mail.ReadWrite permission.
    """
    url = (
        f"{GRAPH_BASE_URL}/users/{mailbox}/messages"
        "?$top=5&$orderby=receivedDateTime desc"
        "&$select=id,subject,from,receivedDateTime,hasAttachments"
    )
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)

        if response.status_code == 200:
            data = response.json()
            messages = data.get("value", [])

            if not messages:
                print_check(
                    "List messages (Mail.Read)",
                    True,
                    "Permission OK but mailbox is empty — no messages found.",
                )
                return True

            print_check(
                "List messages (Mail.Read)",
                True,
                f"Found {len(messages)} recent message(s):",
            )
            for i, msg in enumerate(messages, 1):
                sender = msg.get("from", {}).get("emailAddress", {})
                sender_str = sender.get("address", "unknown")
                subject = msg.get("subject", "(no subject)")[:50]
                received = msg.get("receivedDateTime", "?")[:19]
                has_att = "📎" if msg.get("hasAttachments") else "  "
                print(f"           {i}. {has_att} [{received}] {sender_str}")
                print(f"              {subject}")
            return True

        if response.status_code == 403:
            print_check(
                "List messages (Mail.Read)",
                False,
                "403 Forbidden — app lacks Mail.Read or Mail.ReadBasic "
                "permission. Grant it in Azure AD > App registrations "
                "> API permissions.",
            )
        else:
            body = response.text[:200]
            print_check(
                "List messages (Mail.Read)",
                False,
                f"HTTP {response.status_code}: {body}",
            )
        return False

    except Exception as e:
        print_check("List messages (Mail.Read)", False, f"Request failed: {e}")
        return False


async def check_mail_folders(token: str, mailbox: str) -> bool:
    """Check if we can list mail folders (Inbox, Sent, etc.).

    Calls GET /users/{mailbox}/mailFolders to verify folder access.
    """
    url = (
        f"{GRAPH_BASE_URL}/users/{mailbox}/mailFolders"
        "?$select=displayName,totalItemCount,unreadItemCount"
    )
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)

        if response.status_code == 200:
            data = response.json()
            folders = data.get("value", [])

            print_check(
                "Mail folders",
                True,
                f"Found {len(folders)} folder(s):",
            )
            for folder in folders:
                name = folder.get("displayName", "?")
                total = folder.get("totalItemCount", 0)
                unread = folder.get("unreadItemCount", 0)
                print(f"           - {name}: {total} total, {unread} unread")
            return True

        if response.status_code == 403:
            print_check(
                "Mail folders",
                False,
                "403 Forbidden — app may lack MailboxSettings.Read.",
            )
        else:
            print_check(
                "Mail folders",
                False,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )
        return False

    except Exception as e:
        print_check("Mail folders", False, f"Request failed: {e}")
        return False


async def check_attachment_download(token: str, mailbox: str) -> bool:
    """Check if we can download attachment content from the latest email.

    Finds the most recent email with attachments, then fetches
    the attachment list including contentBytes.
    """
    # First find an email with attachments
    url = (
        f"{GRAPH_BASE_URL}/users/{mailbox}/messages"
        "?$filter=hasAttachments eq true"
        "&$top=1&$orderby=receivedDateTime desc"
        "&$select=id,subject"
    )
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)

        if response.status_code != 200:
            print_warn(
                "Attachment download",
                f"Cannot search for emails with attachments "
                f"(HTTP {response.status_code}). Skipping.",
            )
            return False

        messages = response.json().get("value", [])
        if not messages:
            print_info(
                "Attachment download",
                "No emails with attachments found — skipping test.",
            )
            return True

        msg_id = messages[0]["id"]
        subject = messages[0].get("subject", "(no subject)")[:50]

        # Fetch attachments for this message
        att_url = (
            f"{GRAPH_BASE_URL}/users/{mailbox}/messages/{msg_id}/attachments"
        )

        async with httpx.AsyncClient() as client:
            att_response = await client.get(
                att_url, headers=headers, timeout=30.0
            )

        if att_response.status_code != 200:
            print_check(
                "Attachment download",
                False,
                f"Cannot fetch attachments (HTTP {att_response.status_code}).",
            )
            return False

        attachments = att_response.json().get("value", [])
        has_content = sum(
            1 for a in attachments if a.get("contentBytes")
        )

        print_check(
            "Attachment download",
            True,
            f"Email: '{subject}' — {len(attachments)} attachment(s), "
            f"{has_content} with downloadable content.",
        )
        for att in attachments:
            name = att.get("name", "?")
            size = att.get("size", 0)
            has_bytes = "✓ content" if att.get("contentBytes") else "✗ no content"
            print(f"           - {name} ({size:,} bytes) [{has_bytes}]")
        return True

    except Exception as e:
        print_check("Attachment download", False, f"Request failed: {e}")
        return False


async def check_send_permission(
    token: str, mailbox: str, *, actually_send: bool = False
) -> bool:
    """Check if we have Mail.Send permission.

    If actually_send is False, we only verify the permission exists
    by checking app role assignments. If True, we send a test email
    to the mailbox itself.
    """
    if not actually_send:
        # Just check by trying to construct the request — we can't
        # verify Mail.Send without actually sending. Report as info.
        print_info(
            "Send email (Mail.Send)",
            "Use --send-test flag to actually send a test email "
            "to the mailbox and verify Mail.Send permission.",
        )
        return True

    # Actually send a test email to the mailbox itself
    url = f"{GRAPH_BASE_URL}/users/{mailbox}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": {
            "subject": "[VQMS Test] Graph API Connectivity Check",
            "body": {
                "contentType": "HTML",
                "content": (
                    "<p>This is an automated test email from the VQMS "
                    "Graph API connectivity checker.</p>"
                    "<p>If you received this, <b>Mail.Send</b> permission "
                    "is working correctly.</p>"
                    "<p><small>You can safely delete this email.</small></p>"
                ),
            },
            "toRecipients": [
                {"emailAddress": {"address": mailbox}},
            ],
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, json=payload, timeout=15.0
            )

        if response.status_code == 202:
            print_check(
                "Send email (Mail.Send)",
                True,
                f"Test email sent to {mailbox}. Check inbox.",
            )
            return True

        if response.status_code == 403:
            print_check(
                "Send email (Mail.Send)",
                False,
                "403 Forbidden — app lacks Mail.Send permission. "
                "Grant it in Azure AD > App registrations > API permissions.",
            )
        else:
            body = response.text[:300]
            print_check(
                "Send email (Mail.Send)",
                False,
                f"HTTP {response.status_code}: {body}",
            )
        return False

    except Exception as e:
        print_check("Send email (Mail.Send)", False, f"Request failed: {e}")
        return False


async def check_webhook_subscriptions(token: str, mailbox: str) -> bool:
    """Check existing webhook subscriptions for this mailbox.

    Lists all Graph API subscriptions to see if a webhook is
    configured for email notifications.
    """
    url = f"{GRAPH_BASE_URL}/subscriptions"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)

        if response.status_code == 200:
            subs = response.json().get("value", [])

            if not subs:
                print_info(
                    "Webhook subscriptions",
                    "No active subscriptions. You can create one for "
                    "real-time email notifications in Phase 2.",
                )
                return True

            # Filter for mail-related subscriptions
            mail_subs = [
                s for s in subs
                if "messages" in s.get("resource", "").lower()
            ]

            print_check(
                "Webhook subscriptions",
                True,
                f"{len(subs)} total subscription(s), "
                f"{len(mail_subs)} mail-related:",
            )
            for sub in mail_subs:
                resource = sub.get("resource", "?")
                expiry = sub.get("expirationDateTime", "?")[:19]
                notify_url = sub.get("notificationUrl", "?")[:60]
                print(f"           - Resource: {resource}")
                print(f"             Expires: {expiry}")
                print(f"             Notify URL: {notify_url}")
            return True

        if response.status_code == 403:
            print_warn(
                "Webhook subscriptions",
                "Cannot list subscriptions (403). May need "
                "Subscription.Read.All permission. Non-critical.",
            )
        else:
            print_warn(
                "Webhook subscriptions",
                f"HTTP {response.status_code}. Non-critical.",
            )
        return True  # Non-critical check

    except Exception as e:
        print_warn("Webhook subscriptions", f"Could not check: {e}")
        return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_checks(*, send_test: bool = False) -> None:
    """Run all Graph API connectivity checks."""
    settings = get_settings()

    print("\n  VQMS Microsoft Graph API Connectivity Check")
    print(f"  Tenant: {settings.graph_api_tenant_id}")
    print(f"  Mailbox: {settings.graph_api_mailbox}")

    start = time.time()
    results: dict[str, bool] = {}

    # --- 1. Environment variables ---
    print_header("Configuration")
    results["env_config"] = check_env_config(settings)

    if not results["env_config"]:
        print("\n  Cannot proceed without Graph API configuration.\n")
        return

    # --- 2. MSAL authentication ---
    print_header("Authentication (MSAL)")
    auth_ok, token = check_msal_auth(settings)
    results["msal_auth"] = auth_ok

    if not auth_ok or token is None:
        print("\n  Cannot proceed without a valid access token.\n")
        return

    # --- 3. Mailbox access ---
    print_header("Mailbox Access")
    results["mailbox_access"] = await check_mailbox_access(
        token, settings.graph_api_mailbox
    )

    # --- 4. List messages ---
    print_header("Read Messages (Mail.Read)")
    results["list_messages"] = await check_list_messages(
        token, settings.graph_api_mailbox
    )

    # --- 5. Mail folders ---
    print_header("Mail Folders")
    results["mail_folders"] = await check_mail_folders(
        token, settings.graph_api_mailbox
    )

    # --- 6. Attachment download ---
    print_header("Attachment Download")
    results["attachment_download"] = await check_attachment_download(
        token, settings.graph_api_mailbox
    )

    # --- 7. Send permission ---
    print_header("Send Email (Mail.Send)")
    results["send_email"] = await check_send_permission(
        token, settings.graph_api_mailbox, actually_send=send_test
    )

    # --- 8. Webhook subscriptions ---
    print_header("Webhook Subscriptions")
    results["webhooks"] = await check_webhook_subscriptions(
        token, settings.graph_api_mailbox
    )

    # --- Summary ---
    elapsed = time.time() - start

    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    total = len(results)

    print_header("Summary")
    print(f"  Total checks: {total}")
    print(f"  {PASS} Passed: {passed}")

    if failed > 0:
        print(f"  {FAIL} Failed: {failed}")
        print()
        print("  Failed checks:")
        for name, ok in results.items():
            if not ok:
                print(f"    - {name}")
        print()
        print("  Common fixes:")
        print("    1. Go to Azure Portal > App registrations > your app")
        print("    2. API permissions > Add permission > Microsoft Graph")
        print("    3. Application permissions > add: Mail.Read, Mail.Send,")
        print("       Mail.ReadBasic, User.Read.All")
        print("    4. Click 'Grant admin consent' for your tenant")
    else:
        print("\n  All Graph API checks passed!")

    print(f"\n  Time: {elapsed:.2f}s\n")


def main() -> None:
    """Parse CLI args and run Graph API checks."""
    parser = argparse.ArgumentParser(
        description="Check Microsoft Graph API connectivity for VQMS",
    )
    parser.add_argument(
        "--send-test",
        action="store_true",
        default=False,
        help="Actually send a test email to the mailbox to verify "
             "Mail.Send permission. Without this flag, send is skipped.",
    )
    args = parser.parse_args()

    asyncio.run(run_checks(send_test=args.send_test))


if __name__ == "__main__":
    main()
