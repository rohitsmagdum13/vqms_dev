# Invoice Payment Status Check Procedure

Category: billing

## Standard Payment Cycle

All vendor invoices are processed through a standard 3-step cycle:

1. **Invoice Receipt and Logging** (Day 1-2): Invoice received via email or portal, logged in the AP system with a unique tracking number.
2. **Three-Way Match Verification** (Day 3-5): Invoice matched against Purchase Order (PO) and Goods Receipt Note (GRN). All three documents must agree on item, quantity, and price.
3. **Approval and Payment Scheduling** (Day 5-10): Matched invoices routed for approval based on amount thresholds. Approved invoices scheduled for payment per vendor terms.

## Payment Terms by Vendor Tier

- **Platinum vendors**: Net 15 — payment within 15 days of invoice receipt
- **Gold vendors**: Net 30 — payment within 30 days of invoice receipt
- **Silver vendors**: Net 30 — payment within 30 days of invoice receipt
- **Standard vendors**: Net 45 — payment within 45 days of invoice receipt

## Payment Methods

- Wire transfer (amounts over $50,000)
- ACH transfer (standard payments under $50,000)
- Check (only on vendor request, adds 5 business days)

## How to Check Invoice Status

Vendors can check their invoice payment status through:
1. VQMS Portal: Login > Dashboard > Invoice Tracker
2. Email: Send query to vendor-support@company.com with invoice number in subject line
3. The system will respond with current status: Received, Under Review, Approved, Scheduled for Payment, or Paid

## Common Status Codes

- **RECEIVED**: Invoice logged, pending three-way match
- **UNDER_REVIEW**: Three-way match in progress or discrepancy found
- **APPROVED**: Match verified, pending payment scheduling
- **SCHEDULED**: Payment scheduled for next payment run (every Tuesday and Thursday)
- **PAID**: Payment processed, remittance advice sent to vendor email on file
- **ON_HOLD**: Issue detected — vendor will be contacted within 2 business days
