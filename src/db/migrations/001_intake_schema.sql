-- =============================================================
-- 001_intake_schema.sql — Email Ingestion Tables
-- =============================================================
-- Creates the intake schema for storing email messages and
-- attachments received via Microsoft Graph API.
--
-- Tables:
--   intake.email_messages     — Parsed email metadata and S3 keys
--   intake.email_attachments  — Attachment metadata and S3 keys
--
-- Corresponds to Steps E1-E2 in the VQMS Solution Flow Document.
-- =============================================================

CREATE SCHEMA IF NOT EXISTS intake;

-- email_messages: One row per email received from Exchange Online.
-- The message_id (RFC 2822) is used as the idempotency key to
-- prevent duplicate processing. Thread correlation uses
-- conversation_id, in_reply_to, and the references chain.
CREATE TABLE intake.email_messages (
    id              BIGSERIAL PRIMARY KEY,
    message_id      VARCHAR(512) UNIQUE NOT NULL,   -- RFC 2822 Message-ID (idempotency key)
    conversation_id VARCHAR(512),                    -- MS Graph conversation ID (thread correlation)
    in_reply_to     VARCHAR(512),                    -- RFC 2822 In-Reply-To header
    sender_email    VARCHAR(320) NOT NULL,            -- Sender email (used for vendor matching)
    sender_name     VARCHAR(256),                    -- Sender display name
    recipients      JSONB NOT NULL DEFAULT '[]',     -- To and CC addresses as JSON array
    subject         TEXT NOT NULL,
    body_text       TEXT,                             -- Plain text body
    body_html       TEXT,                             -- HTML body (kept for reference)
    raw_s3_key      VARCHAR(1024),                    -- S3 key for raw .eml file (compliance)
    received_at     TIMESTAMP NOT NULL,                -- When Exchange Online received it (IST)
    correlation_id  VARCHAR(36) NOT NULL,             -- UUID4 tracing ID
    query_id        VARCHAR(20) NOT NULL,             -- VQ-2026-XXXX format
    execution_id    VARCHAR(36) NOT NULL,             -- UUID4 workflow execution ID
    created_at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- email_attachments: One row per attachment on an email.
-- Actual file content is stored in S3; this table has metadata only.
CREATE TABLE intake.email_attachments (
    id              BIGSERIAL PRIMARY KEY,
    email_id        BIGINT NOT NULL REFERENCES intake.email_messages(id) ON DELETE CASCADE,
    filename        VARCHAR(512) NOT NULL,
    content_type    VARCHAR(128),
    size_bytes      BIGINT,
    s3_key          VARCHAR(1024),                    -- S3 key in vqms-email-attachments-prod
    checksum        VARCHAR(128),                     -- SHA-256 for integrity checks
    created_at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- Indexes for common query patterns
CREATE INDEX idx_email_messages_correlation ON intake.email_messages(correlation_id);
CREATE INDEX idx_email_messages_query_id ON intake.email_messages(query_id);
CREATE INDEX idx_email_messages_sender ON intake.email_messages(sender_email);
CREATE INDEX idx_email_messages_conversation ON intake.email_messages(conversation_id);
CREATE INDEX idx_email_messages_received ON intake.email_messages(received_at);
CREATE INDEX idx_email_attachments_email ON intake.email_attachments(email_id);
