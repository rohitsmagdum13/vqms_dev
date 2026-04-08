"""Manual test script for Salesforce connection.

Run this to verify that your Salesforce credentials are working
and the adapter can query the CUSTOM Vendor objects:
  - Vendor_Account__c  (vendor companies)
  - Vendor_Contact__c  (vendor contacts)

Usage:
    uv run python tests/manual/test_salesforce_connection.py
    uv run python tests/manual/test_salesforce_connection.py --email rajesh.mehta@technova.com
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path so imports work when running directly
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env before importing anything that reads settings
from dotenv import load_dotenv  # noqa: E402

load_dotenv(project_root / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test Salesforce connection and Vendor object queries"
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Test find_contact_by_email with this email address",
    )
    args = parser.parse_args()

    # Import after dotenv is loaded so settings pick up .env values
    from src.adapters.salesforce import SalesforceAdapterError, get_salesforce_adapter

    print("=" * 60)
    print("  VQMS — Salesforce Connection Test (Custom Objects)")
    print("=" * 60)
    print()

    # --- Step 1: Connect ---
    print("[1/4] Connecting to Salesforce...")
    adapter = get_salesforce_adapter()

    try:
        sf = adapter.connect()
    except SalesforceAdapterError as exc:
        print(f"  [FAIL] Connection failed: {exc}")
        print()
        print("  Troubleshooting:")
        print("  - Check SALESFORCE_USERNAME in .env")
        print("  - Check SALESFORCE_PASSWORD in .env")
        print("  - Check SALESFORCE_SECURITY_TOKEN in .env")
        print("    (Reset: Setup > My Personal Information > Reset My Security Token)")
        print("  - Check SALESFORCE_LOGIN_URL (login.salesforce.com or test.salesforce.com)")
        sys.exit(1)

    print(f"  [PASS] Connected to: {sf.sf_instance}")
    print()

    # --- Step 2: List vendor contacts (Vendor_Contact__c) ---
    print("[2/4] Querying Vendor_Contact__c (LIMIT 5)...")
    try:
        result = sf.query(
            "SELECT Id, Name, Email__c, Vendor_Account__c "
            "FROM Vendor_Contact__c LIMIT 5"
        )
        records = result.get("records", [])
        total = result.get("totalSize", 0)
        print(f"  [PASS] Found {total} vendor contacts (showing up to 5):")
        for r in records:
            email = r.get("Email__c") or "(no email)"
            print(f"    - {r.get('Name', '?')} | {email} | {r.get('Id', '?')}")
    except Exception as exc:
        print(f"  [FAIL] Query failed: {exc}")
    print()

    # --- Step 3: List vendor accounts (Vendor_Account__c) ---
    print("[3/4] Querying Vendor_Account__c (LIMIT 5)...")
    try:
        result = sf.query(
            "SELECT Id, Name, Vendor_ID__c, Vendor_Tier__c, "
            "Vendor_Status__c, Category__c "
            "FROM Vendor_Account__c LIMIT 5"
        )
        records = result.get("records", [])
        total = result.get("totalSize", 0)
        print(f"  [PASS] Found {total} vendor accounts (showing up to 5):")
        for r in records:
            vid = r.get("Vendor_ID__c") or "(no vendor ID)"
            tier = r.get("Vendor_Tier__c") or "(no tier)"
            status = r.get("Vendor_Status__c") or "(no status)"
            print(f"    - {r.get('Name', '?')} | {vid} | {tier} | {status}")
    except Exception as exc:
        print(f"  [FAIL] Query failed: {exc}")
    print()

    # --- Step 4: Optional email lookup ---
    if args.email:
        print(f"[4/4] Looking up vendor contact by email: {args.email}")
        try:
            contact = adapter.find_contact_by_email(args.email)
            if contact:
                print("  [PASS] Vendor Contact found:")
                print(f"    Name:      {contact.get('Name')}")
                print(f"    Email:     {contact.get('Email')}")
                print(f"    ContactId: {contact.get('Id')}")
                print(f"    AccountId: {contact.get('AccountId')}")

                # Also look up the parent Vendor Account
                account_id = contact.get("AccountId")
                if account_id:
                    account = adapter.find_account_by_id(account_id)
                    if account:
                        print("  Vendor Account:")
                        print(f"    Name:       {account.get('Name')}")
                        print(f"    Vendor ID:  {account.get('Vendor_ID__c')}")
                        print(f"    Tier:       {account.get('Vendor_Tier__c')}")
                        print(f"    Status:     {account.get('Vendor_Status__c')}")
                        print(f"    Category:   {account.get('Category__c')}")
                        print(f"    SF Id:      {account.get('Id')}")
            else:
                print(f"  [INFO] No vendor contact found for email: {args.email}")
        except Exception as exc:
            print(f"  [FAIL] Lookup failed: {exc}")
    else:
        print("[4/4] Skipped email lookup (use --email <address> to test)")

    print()
    print("=" * 60)
    print("  Done. Salesforce connection is working.")
    print("=" * 60)


if __name__ == "__main__":
    main()
