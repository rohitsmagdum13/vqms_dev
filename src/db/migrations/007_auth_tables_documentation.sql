-- =============================================================
-- Migration 007: Auth Tables Documentation
-- =============================================================
-- These tables ALREADY EXIST in the RDS public schema, created
-- by the local_vqm backend. This migration documents their
-- schema for developer reference and uses CREATE TABLE IF NOT
-- EXISTS so it is safe to run but will NOT modify existing data.
--
-- Tables:
--   public.tbl_users       — user accounts with hashed passwords
--   public.tbl_user_roles  — user-to-role mapping with audit trail
--
-- NOTE: These tables are in the public schema (not a VQMS
-- namespace like intake. or workflow.) because they were created
-- before the VQMS namespace convention was established.
-- =============================================================

-- User accounts — passwords are hashed with werkzeug
CREATE TABLE IF NOT EXISTS public.tbl_users (
    id              SERIAL PRIMARY KEY,
    user_name       VARCHAR(255) UNIQUE NOT NULL,
    email_id        VARCHAR(255) UNIQUE NOT NULL,
    tenant          VARCHAR(255) NOT NULL,
    password        VARCHAR(512) NOT NULL,       -- werkzeug password hash
    status          VARCHAR(50) DEFAULT 'ACTIVE', -- ACTIVE or INACTIVE

    -- Security Q&A for password recovery
    security_q1     VARCHAR(512),
    security_a1     VARCHAR(512),
    security_q2     VARCHAR(512),
    security_a2     VARCHAR(512),
    security_q3     VARCHAR(512),
    security_a3     VARCHAR(512)
);

-- User role assignments — links users to roles within tenants
CREATE TABLE IF NOT EXISTS public.tbl_user_roles (
    slno            SERIAL PRIMARY KEY,
    first_name      VARCHAR(255),
    last_name       VARCHAR(255),
    email_id        VARCHAR(255),
    user_name       VARCHAR(255),
    tenant          VARCHAR(255),
    role            VARCHAR(100),                -- ADMIN, VENDOR, REVIEWER
    created_by      VARCHAR(255),
    created_date    TIMESTAMP,
    modified_by     VARCHAR(255),
    modified_date   TIMESTAMP,
    deleted_by      VARCHAR(255),
    deleted_date    TIMESTAMP
);

-- Indexes for common lookups (IF NOT EXISTS for safety)
CREATE INDEX IF NOT EXISTS idx_tbl_users_email
    ON public.tbl_users (email_id);

CREATE INDEX IF NOT EXISTS idx_tbl_users_status
    ON public.tbl_users (status);

CREATE INDEX IF NOT EXISTS idx_tbl_user_roles_username
    ON public.tbl_user_roles (user_name);

CREATE INDEX IF NOT EXISTS idx_tbl_user_roles_tenant
    ON public.tbl_user_roles (tenant);
