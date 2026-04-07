-- =============================================================
-- 003_memory_schema.sql — Memory and Context Tables
-- =============================================================
-- Creates the memory schema for episodic memory, vendor profile
-- caching, and vector embeddings for KB search.
--
-- Tables:
--   memory.episodic_memory      — Past query history per vendor
--   memory.vendor_profile_cache — Cached Salesforce vendor data
--   memory.embedding_index      — KB article vector embeddings (pgvector)
--
-- Requires the pgvector extension for the embedding_index table.
-- =============================================================

CREATE SCHEMA IF NOT EXISTS memory;

-- Enable pgvector extension for vector similarity search.
-- Requires pgvector to be installed on the PostgreSQL server.
-- See: https://github.com/pgvector/pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- episodic_memory: Stores summaries of past vendor interactions.
-- Agents load these to understand a vendor's history and patterns
-- when processing a new query (Step 7: context loading).
CREATE TABLE memory.episodic_memory (
    id              BIGSERIAL PRIMARY KEY,
    memory_id       VARCHAR(36) UNIQUE NOT NULL,      -- UUID4 identifier
    vendor_id       VARCHAR(64) NOT NULL,              -- Salesforce Account ID (indexed for fast lookup)
    query_id        VARCHAR(20) NOT NULL,              -- Which query this memory relates to
    summary         TEXT NOT NULL,                     -- Brief description of query and resolution
    resolution_path VARCHAR(1),                        -- A, B, or C
    resolved_at     TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',                -- Extra context: category, urgency, satisfaction
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- vendor_profile_cache: PostgreSQL backup of Redis-cached vendor data.
-- Primary cache is Redis (1-hour TTL). On cache miss, we check this
-- table before hitting Salesforce API.
CREATE TABLE memory.vendor_profile_cache (
    id              BIGSERIAL PRIMARY KEY,
    vendor_id       VARCHAR(64) UNIQUE NOT NULL,
    vendor_name     VARCHAR(256) NOT NULL,
    vendor_tier     VARCHAR(20) NOT NULL DEFAULT 'standard',
    profile_data    JSONB DEFAULT '{}',                -- Full profile: email, manager, risk flags, etc.
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_seconds     INTEGER NOT NULL DEFAULT 3600      -- 1 hour default
);

-- embedding_index: Vector embeddings for KB article chunks.
-- Used by KB Search Service (Step 9B) to find relevant articles
-- via cosine similarity. Embeddings are 1536-dimensional (Titan Embed v2).
CREATE TABLE memory.embedding_index (
    id              BIGSERIAL PRIMARY KEY,
    record_id       VARCHAR(36) UNIQUE NOT NULL,      -- UUID4 identifier
    source_document VARCHAR(512) NOT NULL,             -- KB article ID or filename
    chunk_text      TEXT NOT NULL,                     -- Text content of this chunk
    embedding       vector(1536),                      -- Titan Embed v2 produces 1536-dim vectors
    metadata        JSONB DEFAULT '{}',                -- category, chunk_index, document_id, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_episodic_vendor ON memory.episodic_memory(vendor_id);
CREATE INDEX idx_episodic_query ON memory.episodic_memory(query_id);
CREATE INDEX idx_episodic_created ON memory.episodic_memory(created_at);
CREATE INDEX idx_vendor_cache_vendor ON memory.vendor_profile_cache(vendor_id);

-- HNSW index for fast approximate nearest neighbor search on embeddings.
-- m=16 and ef_construction=64 are good defaults from pgvector docs.
CREATE INDEX idx_embedding_hnsw ON memory.embedding_index
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
