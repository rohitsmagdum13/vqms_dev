# VQMS Task Tracker

## Phase 1 — Foundation and Data Layer [COMPLETE]

- [x] Config module, all Pydantic models (10 files, 22 models, 7 enums)
- [x] PostgreSQL migrations (5 SQL files, 11 tables)
- [x] PostgreSQL cache (cache.kv_store) with key builders
- [x] Database connection pool, structured logging, ID generation
- [x] FastAPI app with health check
- [x] Tests: 71 passing (models, cache keys, correlation IDs)
- [x] Flow.md and README.md

## Phase 2 — Intake Services (Email + Portal) [COMPLETE]

### Cloud-Only Rewrite (Override Applied)
All adapters connect directly to real AWS services. No local/mock fallback modes.

- [x] Domain exceptions: DuplicateQueryError, VendorNotFoundError (`src/utils/exceptions.py`)
- [x] S3 storage adapter — boto3 direct, lazy client, reset_client() for moto (`src/storage/s3_client.py`)
- [x] SQS queue adapter — boto3 direct, URL caching, reset_client() for moto (`src/queues/sqs.py`)
- [x] EventBridge adapter — boto3 direct, FailedEntryCount check, reset_client() for moto (`src/events/eventbridge.py`)
- [x] Salesforce CRM stub with 3-step vendor resolution (`src/adapters/salesforce.py`)
- [x] Microsoft Graph API — real MSAL OAuth2 client_credentials, fetch + send email (`src/adapters/graph_api.py`)
- [x] SSH tunnel to RDS via sshtunnel (`src/db/connection.py`)
- [x] Settings update: SSH tunnel fields, Graph API fields, removed local backend flags (`config/settings.py`)
- [x] Portal submission service: validate, generate IDs, idempotency, event, queue (`src/services/portal_submission.py`)
- [x] Email intake service: fetch, idempotency, vendor resolution, thread correlation, S3 storage, event, queue (`src/services/email_intake.py`)
- [x] Portal API route: POST /queries with X-Vendor-ID header auth (`src/api/routes/queries.py`)
- [x] Webhook API route: POST /webhooks/ms-graph with validation and notifications (`src/api/routes/webhooks.py`)
- [x] Routes wired in main.py, SSH tunnel lifecycle in lifespan, health check phase 2
- [x] sshtunnel dependency added via `uv add`
- [x] .env.copy updated with SSH tunnel vars
- [x] CLAUDE.md updated: cloud-only constraints, SSH tunnel, Graph API sections
- [x] Tests: moto for AWS mocking, mock patches for service-level tests — 101 total passing
- [x] Flow.md updated with cloud-only adapter descriptions
- [x] README.md updated with cloud-only status and SSH tunnel setup

### Phase 2 Gate Criteria
- [x] Both paths produce valid SQS messages (verified in tests)
- [x] Idempotency works (duplicate detection via PostgreSQL cache, graceful on failure)
- [x] Vendor ID resolved by email, body regex, or name similarity (or UNRESOLVED)
- [x] Thread correlation returns NEW or EXISTING_OPEN
- [x] `uv run ruff check .` passes
- [x] `uv run pytest` passes (101 tests)

## Phase 3 — AI Pipeline Core (Steps 7-9) [COMPLETE]

### New Files Created
- [x] `src/models/kb.py` — KBSearchResult + KBSearchResponse models
- [x] `src/adapters/bedrock.py` — Bedrock LLM (Claude Sonnet 3.5) + embeddings (Titan Embed v2)
- [x] `src/agents/abc_agent.py` — Base agent class (Jinja2 templates, LLM calls, JSON parsing, budget tracking)
- [x] `src/agents/query_analysis.py` — Query Analysis Agent (LLM Call #1, two-attempt JSON parse)
- [x] `src/services/memory_context.py` — Vendor profile (cache → Salesforce) + episodic history (PostgreSQL)
- [x] `src/services/routing.py` — Deterministic routing rules engine (16-cell SLA matrix, team assignment)
- [x] `src/services/kb_search.py` — KB search via Titan Embed v2 + pgvector cosine similarity
- [x] `src/orchestration/nodes/__init__.py` — Package init
- [x] `src/orchestration/nodes/context_loading.py` — Step 7: status update, vendor profile, history, budget
- [x] `src/orchestration/nodes/query_analysis_node.py` — Step 8: wraps QueryAnalysisAgent, persists to DB/S3/EventBridge
- [x] `src/orchestration/nodes/confidence_check.py` — Conditional edge: >= 0.85 pass, < 0.85 fail
- [x] `src/orchestration/nodes/routing_and_kb_search.py` — Step 9: parallel asyncio.gather(routing, kb_search)
- [x] `src/orchestration/nodes/path_decision.py` — Conditional edge: Path A (KB match + facts) vs Path B
- [x] `src/orchestration/nodes/path_stubs.py` — Path A/B/C stubs (update DB, EventBridge, audit)
- [x] `src/orchestration/graph.py` — LangGraph StateGraph with PipelineState, conditional edges, compiled graph
- [x] `src/orchestration/sqs_consumer.py` — SQS long-poll consumer with delete-on-success-only
- [x] `prompts/query_analysis/v1.jinja` — Jinja2 prompt template for Query Analysis Agent
- [x] `data/knowledge_base/` — 5 sample KB articles (4 billing, 1 general)
- [x] `src/db/seeds/__init__.py` + `src/db/seeds/seed_kb_articles.py` — KB seeding script
- [x] `tests/unit/test_routing.py` — 24 unit tests (SLA matrix, team assignment, automation blocking)
- [x] `tests/manual/test_bedrock_connection.py` — Manual Bedrock LLM + embedding test
- [x] `tests/manual/test_kb_search.py` — Manual KB search test
- [x] `tests/manual/test_phase3_pipeline.py` — Full end-to-end pipeline test
- [x] `scripts/run_pipeline.py` — Pipeline runner (--consumer-only / --server-only)

### Modified Files
- [x] `config/settings.py` — Added 9 Bedrock fields (model IDs, temperature, retries, embedding config)
- [x] `src/models/workflow.py` — Added 4 LLM tracking fields to AnalysisResult (tokens, cost, latency)
- [x] `src/models/ticket.py` — Added sla_deadline + risk_flags to RoutingDecision
- [x] `main.py` — SQS consumer as background task in lifespan, health check phase=3

### Documentation
- [x] `tasks/todo.md` — Phase 3 marked complete
- [x] `Flow.md` — Steps 7, 8, 9 documented with function paths
- [x] `README.md` — Phase 3 status, KB seeding instructions, pipeline running instructions

### Phase 3 Gate Criteria
- [x] LangGraph graph compiles and executes end-to-end
- [x] SQS consumer picks up messages from real queue
- [x] Context loading fetches vendor profile (PostgreSQL cache → Salesforce)
- [x] Query Analysis Agent calls real Bedrock Claude and returns valid AnalysisResult
- [x] Confidence branching: >= 0.85 → routing, < 0.85 → Path C stub
- [x] Routing assigns correct team + SLA from rules matrix (24 unit tests)
- [x] KB search embeds via Titan Embed v2, searches pgvector
- [x] Path A/B decision based on KB match quality + has_specific_facts
- [x] All storage writes: PostgreSQL, S3 audit, EventBridge events
- [x] Correlation ID flows through every function

## Cross-Cutting: Dynamic LLM Provider Abstraction [COMPLETE]

Added multi-provider LLM support with automatic Bedrock → OpenAI fallback.

- [x] `src/llm/protocol.py` — LLMProvider Protocol (structural subtyping)
- [x] `src/adapters/bedrock.py` — Added BedrockProvider wrapper class
- [x] `src/adapters/openai_provider.py` — OpenAI provider (GPT-4o + text-embedding-3-small)
- [x] `src/llm/factory.py` — Factory with fallback chain (llm_complete, llm_embed)
- [x] `config/settings.py` — Added llm_provider, embedding_provider, 7 OpenAI settings
- [x] `.env.copy` — Added LLM_PROVIDER, EMBEDDING_PROVIDER, OPENAI_* env vars
- [x] `src/agents/abc_agent.py` — Changed invoke_llm → llm_complete (factory)
- [x] `src/services/kb_search.py` — Changed embed_text → llm_embed + unwrap vector
- [x] `src/db/seeds/seed_kb_articles.py` — Same embed change + unwrap
- [x] `src/models/workflow.py` — Added provider and was_fallback fields to AnalysisResult
- [x] `src/agents/query_analysis.py` — Populates provider/was_fallback in _build_analysis_result
- [x] `tests/unit/test_llm_factory.py` — 8 unit tests for fallback logic (all pass)
- [x] `tests/manual/test_llm_providers.py` — 6 manual provider integration tests
- [x] Documentation: README.md, Flow.md, CLAUDE.md updated
- [x] Verification: 165 tests pass, ruff clean, no direct bedrock/openai imports

## Next: Phase 4 — Response Generation and Delivery (Steps 10-12)
- [ ] Resolution Agent (Step 10A): LLM Call #2 using KB facts → full answer email
- [ ] Communication Drafting Agent (Step 10B): acknowledgment-only email (Path B)
- [ ] Quality & Governance Gate (Step 11): 7-check validation (ticket#, SLA, PII, etc.)
- [ ] ServiceNow ticket creation (Step 12): src/adapters/servicenow.py + src/services/ticket_ops.py
- [ ] Email delivery via MS Graph /sendMail (Step 12)
- [ ] Wire Path A and Path B end-to-end through LangGraph
