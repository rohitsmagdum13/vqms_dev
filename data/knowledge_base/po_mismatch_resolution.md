# Purchase Order Mismatch Resolution

Category: billing

## What is a Three-Way Match Failure?

A three-way match failure occurs when the Invoice, Purchase Order (PO), and Goods Receipt Note (GRN) do not agree. Common mismatches include:

- **Price mismatch**: Invoice unit price differs from PO unit price
- **Quantity mismatch**: Invoiced quantity differs from received quantity (GRN)
- **Item mismatch**: Invoice line items do not match PO line items
- **Tax mismatch**: Tax amount on invoice does not match expected calculation

## Resolution Process

### Step 1: Identify the Discrepancy (1-2 business days)
- AP team runs automated three-way match
- System flags specific lines with discrepancies
- Discrepancy report generated with PO number, invoice number, and details

### Step 2: Vendor Communication (2-3 business days)
- AP sends discrepancy notice to vendor via email
- Notice includes: specific lines, expected vs actual values, supporting documents needed
- Vendor has 5 business days to respond

### Step 3: Resolution Options
- **Credit Note**: Vendor issues credit note for the difference
- **Revised Invoice**: Vendor submits corrected invoice
- **PO Amendment**: If PO was incorrect, buyer submits PO amendment
- **Partial Payment**: Pay matched lines, hold mismatched lines for resolution

### Step 4: Payment After Resolution (1-3 business days)
- Once discrepancy resolved, invoice re-enters the standard payment cycle
- Priority processing applied to previously held invoices
- Payment typically within 3 business days of resolution

## Common Tolerance Thresholds

- Price variance up to 2% is auto-approved
- Quantity variance up to 5 units or 3% (whichever is less) is auto-approved
- Tax rounding differences up to $1.00 are auto-approved
- Variances exceeding these thresholds require manual review

## Prevention Tips for Vendors

1. Always reference the correct PO number on invoices
2. Match invoice line items exactly to PO line items
3. Verify quantities against delivery receipts before invoicing
4. Use the correct tax rate as specified in the PO terms
5. Submit invoices within 30 days of delivery to avoid GRN expiry
