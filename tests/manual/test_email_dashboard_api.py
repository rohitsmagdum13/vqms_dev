"""Manual test script for Email Dashboard API endpoints.

Run with: uv run python tests/manual/test_email_dashboard_api.py

Calls all 4 email dashboard endpoints against a running server
and prints the responses. The server must be running on localhost:8000.

Equivalent curl commands for each endpoint:

# 1. List email chains (paginated)
# curl http://localhost:8000/emails?page=1&page_size=5

# 2. List with filters
# curl "http://localhost:8000/emails?status=New&priority=High&search=invoice"

# 3. Get email stats
# curl http://localhost:8000/emails/stats

# 4. Get single email chain
# curl http://localhost:8000/emails/VQ-2026-0001

# 5. Download attachment (replace IDs with real values)
# curl http://localhost:8000/emails/VQ-2026-0001/attachments/1/download
"""

from __future__ import annotations

import json
import sys

import httpx

BASE_URL = "http://localhost:8000"


def print_response(label: str, response: httpx.Response) -> None:
    """Print a labeled HTTP response."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  {response.request.method} {response.request.url}")
    print(f"  Status: {response.status_code}")
    print(f"{'=' * 60}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2, default=str))
    except Exception:
        print(response.text[:500])


def main() -> None:
    """Run all email dashboard API tests."""
    client = httpx.Client(base_url=BASE_URL, timeout=10.0)

    # --- Test 1: Health check (sanity) ---
    print("\nChecking server health...")
    try:
        health = client.get("/health")
        if health.status_code != 200:
            print(f"Server not healthy: {health.status_code}")
            sys.exit(1)
        print(f"Server OK: {health.json()}")
    except httpx.ConnectError:
        print(f"Cannot connect to {BASE_URL}. Is the server running?")
        print("Start it with: uv run uvicorn main:app --reload --port 8000")
        sys.exit(1)

    # --- Test 2: List email chains (default params) ---
    resp = client.get("/emails", params={"page": 1, "page_size": 5})
    print_response("List Email Chains (page=1, page_size=5)", resp)

    # --- Test 3: List with status filter ---
    resp = client.get("/emails", params={"status": "New", "page_size": 3})
    print_response("List Email Chains (status=New)", resp)

    # --- Test 4: List with search ---
    resp = client.get("/emails", params={"search": "invoice"})
    print_response("List Email Chains (search='invoice')", resp)

    # --- Test 5: Email stats ---
    resp = client.get("/emails/stats")
    print_response("Email Stats", resp)

    # --- Test 6: Single email chain ---
    # Try to get a real query_id from the list response
    list_resp = client.get("/emails", params={"page_size": 1})
    list_data = list_resp.json()
    if list_data.get("mail_chains"):
        first_chain = list_data["mail_chains"][0]
        if first_chain.get("mail_items"):
            # We don't have query_id in the chain response directly,
            # so we'll try a known pattern
            pass

    # Try with a sample query_id (may 404 if no data)
    resp = client.get("/emails/VQ-2026-0001")
    print_response("Single Email Chain (VQ-2026-0001)", resp)

    # --- Test 7: Attachment download ---
    resp = client.get("/emails/VQ-2026-0001/attachments/1/download")
    print_response("Attachment Download (VQ-2026-0001, att_id=1)", resp)

    # --- Test 8: Invalid filter (should return 422) ---
    resp = client.get("/emails", params={"status": "InvalidStatus"})
    print_response("Invalid Status Filter (expect 422)", resp)

    print("\n" + "=" * 60)
    print("  All email dashboard API tests completed.")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
