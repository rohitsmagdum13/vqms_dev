-- =============================================================
-- 006_intake_add_detail_columns.sql — Add Detailed Fields
-- =============================================================
-- Adds new columns to intake.email_messages for detailed email
-- metadata: to/cc addresses, body preview, attachment flags,
-- thread info, auto-reply detection, language, vendor/query
-- references, and pipeline status.
--
-- These fields support the detailed JSON storage in S3 and
-- the same data being queryable in PostgreSQL.
--
-- IMPORTANT: This is an ALTER TABLE migration because the
-- original 001_intake_schema.sql already ran on RDS. New
-- installations should run both 001 and 006 in sequence.
-- =============================================================

-- Add to/cc address columns (JSONB arrays)
ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS to_address JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS cc_addresses JSONB DEFAULT '[]';

-- Add body preview (short text for quick display)
ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS body_preview TEXT;

-- Add attachment summary columns
ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS has_attachments BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS attachment_count INTEGER DEFAULT 0;

-- Add thread correlation columns
ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS thread_id VARCHAR(512),
    ADD COLUMN IF NOT EXISTS is_reply BOOLEAN DEFAULT FALSE;

-- Add auto-reply and language detection
ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS is_auto_reply BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS language VARCHAR(10);

-- Add pipeline status (NEW -> PROCESSING -> RESOLVED -> CLOSED)
ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'NEW';

-- Add vendor and query analysis fields
-- vendor_id is populated at intake time from Salesforce resolution
-- query_type, invoice_ref, po_ref, contract_ref, amount are
-- best-effort regex at intake; refined by Query Analysis Agent (Phase 3)
ALTER TABLE intake.email_messages
    ADD COLUMN IF NOT EXISTS vendor_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS query_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS invoice_ref VARCHAR(128),
    ADD COLUMN IF NOT EXISTS po_ref VARCHAR(128),
    ADD COLUMN IF NOT EXISTS contract_ref VARCHAR(128),
    ADD COLUMN IF NOT EXISTS amount NUMERIC(18,2);

-- Index on vendor_id for vendor-scoped queries
CREATE INDEX IF NOT EXISTS idx_email_messages_vendor ON intake.email_messages(vendor_id);

-- Index on status for pipeline filtering
CREATE INDEX IF NOT EXISTS idx_email_messages_status ON intake.email_messages(status);
