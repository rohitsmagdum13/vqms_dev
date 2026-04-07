-- =============================================================
-- 002_workflow_schema.sql — Workflow State Tables
-- =============================================================
-- Creates the workflow schema for tracking query execution state,
-- ServiceNow ticket links, and routing decisions.
--
-- Tables:
--   workflow.case_execution    — Central state table for every query
--   workflow.ticket_link       — Links between queries and ServiceNow tickets
--   workflow.routing_decision  — Routing rules engine output
--
-- case_execution is the single source of truth for "what happened
-- to this query" and is the most frequently queried table.
-- =============================================================

CREATE SCHEMA IF NOT EXISTS workflow;

-- case_execution: One row per query that enters VQMS.
-- Both email and portal paths create a case_execution record
-- at intake time. Status is updated at each pipeline step.
CREATE TABLE workflow.case_execution (
    id              BIGSERIAL PRIMARY KEY,
    execution_id    VARCHAR(36) UNIQUE NOT NULL,      -- UUID4 primary identifier
    query_id        VARCHAR(20) UNIQUE NOT NULL,      -- VQ-2026-XXXX (human-readable)
    correlation_id  VARCHAR(36) NOT NULL,              -- UUID4 tracing ID
    status          VARCHAR(50) NOT NULL DEFAULT 'new',
    source          VARCHAR(10) NOT NULL,              -- 'email' or 'portal'
    vendor_id       VARCHAR(64),                       -- Salesforce Account ID (null if UNRESOLVED)
    analysis_result JSONB,                             -- Serialized AnalysisResult from Step 8
    routing_decision JSONB,                            -- Serialized RoutingDecision from Step 9A
    selected_path   VARCHAR(1),                        -- A, B, or C
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ                        -- Set when case is closed/resolved
);

-- ticket_link: Tracks which ServiceNow tickets are associated
-- with each query. A query can have multiple links (create,
-- update, reopen scenarios).
CREATE TABLE workflow.ticket_link (
    id              BIGSERIAL PRIMARY KEY,
    execution_id    VARCHAR(36) NOT NULL,
    ticket_id       VARCHAR(64) NOT NULL,              -- ServiceNow incident sys_id
    ticket_number   VARCHAR(32),                       -- INC0012345 (human-readable)
    link_type       VARCHAR(20) NOT NULL,              -- CREATED, UPDATED, REOPENED
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- routing_decision: Output of the deterministic routing engine.
-- Records why a query was routed to a specific team and path.
CREATE TABLE workflow.routing_decision (
    id                BIGSERIAL PRIMARY KEY,
    execution_id      VARCHAR(36) NOT NULL,
    assigned_team     VARCHAR(128) NOT NULL,
    routing_reason    TEXT,
    sla_hours         REAL NOT NULL,                   -- SLA target based on tier + urgency
    vendor_tier       VARCHAR(20),                     -- PLATINUM, GOLD, SILVER, STANDARD
    urgency_level     VARCHAR(20),                     -- CRITICAL, HIGH, MEDIUM, LOW
    confidence_score  REAL,
    path              VARCHAR(1) NOT NULL,             -- A, B, or C
    automation_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_case_execution_query ON workflow.case_execution(query_id);
CREATE INDEX idx_case_execution_correlation ON workflow.case_execution(correlation_id);
CREATE INDEX idx_case_execution_vendor ON workflow.case_execution(vendor_id);
CREATE INDEX idx_case_execution_status ON workflow.case_execution(status);
CREATE INDEX idx_case_execution_created ON workflow.case_execution(created_at);
CREATE INDEX idx_ticket_link_execution ON workflow.ticket_link(execution_id);
CREATE INDEX idx_ticket_link_ticket ON workflow.ticket_link(ticket_id);
CREATE INDEX idx_routing_decision_execution ON workflow.routing_decision(execution_id);
