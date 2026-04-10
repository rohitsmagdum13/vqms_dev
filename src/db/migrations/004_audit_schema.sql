-- =============================================================
-- 004_audit_schema.sql — Audit Trail Tables
-- =============================================================
-- Creates the audit schema for logging every action and
-- recording Quality Gate validation results.
--
-- Tables:
--   audit.action_log          — Every state transition and action
--   audit.validation_results  — Quality Gate check outcomes
--
-- Every side-effect in VQMS writes to audit.action_log.
-- This is a hard requirement from the architecture doc, not optional.
-- =============================================================

CREATE SCHEMA IF NOT EXISTS audit;

-- action_log: Records every meaningful action in the system.
-- Used for compliance, debugging, and post-incident analysis.
-- Every entry has a correlation_id for tracing and a timestamp.
CREATE TABLE audit.action_log (
    id              BIGSERIAL PRIMARY KEY,
    correlation_id  VARCHAR(36) NOT NULL,              -- UUID4 tracing ID
    execution_id    VARCHAR(36),                       -- VQMS execution ID (null for system actions)
    actor           VARCHAR(128) NOT NULL,             -- Service name, agent name, or user ID
    action          VARCHAR(128) NOT NULL,             -- What happened (e.g., 'email_parsed', 'draft_created')
    details         JSONB DEFAULT '{}',                -- Additional context as JSON
    created_at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- validation_results: Records the outcome of every Quality Gate check.
-- Each draft goes through up to 7 checks before being sent.
-- Failed validations trigger DRAFT_REJECTED status.
CREATE TABLE audit.validation_results (
    id              BIGSERIAL PRIMARY KEY,
    execution_id    VARCHAR(36) NOT NULL,
    passed          BOOLEAN NOT NULL,
    checks_run      JSONB NOT NULL DEFAULT '[]',       -- List of check names executed
    failures        JSONB NOT NULL DEFAULT '[]',       -- Specific failures with details
    warnings        JSONB NOT NULL DEFAULT '[]',       -- Non-blocking warnings
    pii_detected    BOOLEAN NOT NULL DEFAULT FALSE,    -- True if PII found (blocks sending)
    redraft_count   INTEGER NOT NULL DEFAULT 0,        -- How many re-drafts attempted (max 2)
    created_at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')
);

-- Indexes for common audit queries
CREATE INDEX idx_action_log_correlation ON audit.action_log(correlation_id);
CREATE INDEX idx_action_log_execution ON audit.action_log(execution_id);
CREATE INDEX idx_action_log_created ON audit.action_log(created_at);
CREATE INDEX idx_action_log_actor ON audit.action_log(actor);
CREATE INDEX idx_validation_execution ON audit.validation_results(execution_id);
