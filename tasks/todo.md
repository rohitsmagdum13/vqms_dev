# VQMS Task Tracker

## Phase 1 — Foundation and Data Layer [COMPLETE]

- [x] Config module, all Pydantic models (10 files, 22 models, 7 enums)
- [x] PostgreSQL migrations (5 SQL files, 11 tables)
- [x] Redis client with 7 key families
- [x] Database connection pool, structured logging, ID generation
- [x] FastAPI app with health check
- [x] Tests: 71 passing (models, redis keys, correlation IDs)
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
- [x] Idempotency works (duplicate detection via Redis, graceful on Redis failure)
- [x] Vendor ID resolved by email, body regex, or name similarity (or UNRESOLVED)
- [x] Thread correlation returns NEW or EXISTING_OPEN
- [x] `uv run ruff check .` passes
- [x] `uv run pytest` passes (101 tests)

## Next: Phase 3 — AI Pipeline Core (Steps 7-9)
- [ ] LangGraph orchestrator with SQS consumer and context loading (Step 7)
- [ ] Query Analysis Agent with Bedrock Claude prompt (Step 8)
- [ ] Routing Service: deterministic rules engine (Step 9A)
- [ ] KB Search Service: embed query + cosine similarity (Step 9B)
- [ ] Confidence branching: >= 0.85 -> Path A/B, < 0.85 -> Path C
