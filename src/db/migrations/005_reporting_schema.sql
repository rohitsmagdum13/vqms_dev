-- =============================================================
-- 005_reporting_schema.sql — Reporting and SLA Metrics
-- =============================================================
-- Creates the reporting schema for SLA tracking, cost metrics,
-- and path distribution analytics.
--
-- Tables:
--   reporting.sla_metrics — SLA tracking per query execution
--
-- This table powers:
--   - SLA monitoring service (Step 13: 70/85/95% escalations)
--   - Admin dashboard (GET /admin/metrics)
--   - Vendor portal KPIs (GET /dashboard/kpis)
-- =============================================================

CREATE SCHEMA IF NOT EXISTS reporting;

-- sla_metrics: One row per query execution, tracking SLA compliance.
-- Created when a ticket is created (Step 12) and updated as the
-- query progresses through resolution and closure.
CREATE TABLE reporting.sla_metrics (
    id                  BIGSERIAL PRIMARY KEY,
    execution_id        VARCHAR(36) NOT NULL,
    ticket_id           VARCHAR(64),                   -- ServiceNow ticket sys_id
    vendor_id           VARCHAR(64),                   -- Salesforce Account ID
    vendor_tier         VARCHAR(20),                   -- PLATINUM, GOLD, SILVER, STANDARD
    urgency_level       VARCHAR(20),                   -- CRITICAL, HIGH, MEDIUM, LOW
    sla_target_hours    REAL NOT NULL,                 -- Target hours based on tier + urgency
    sla_elapsed_hours   REAL,                          -- Actual hours elapsed (updated on resolution)
    sla_breached        BOOLEAN NOT NULL DEFAULT FALSE,-- True if SLA target was missed
    processing_path     VARCHAR(1),                    -- A, B, or C
    first_response_at   TIMESTAMPTZ,                   -- When first email was sent to vendor
    resolved_at         TIMESTAMPTZ,                   -- When case was resolved
    total_cost_usd      REAL,                          -- Total LLM cost for this execution
    total_tokens_in     INTEGER,                       -- Total input tokens across all LLM calls
    total_tokens_out    INTEGER,                       -- Total output tokens across all LLM calls
    llm_calls_count     INTEGER DEFAULT 0,             -- Number of LLM calls made
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for dashboard queries and SLA monitoring
CREATE INDEX idx_sla_execution ON reporting.sla_metrics(execution_id);
CREATE INDEX idx_sla_vendor ON reporting.sla_metrics(vendor_id);
CREATE INDEX idx_sla_breached ON reporting.sla_metrics(sla_breached);
CREATE INDEX idx_sla_path ON reporting.sla_metrics(processing_path);
CREATE INDEX idx_sla_created ON reporting.sla_metrics(created_at);
CREATE INDEX idx_sla_tier ON reporting.sla_metrics(vendor_tier);
