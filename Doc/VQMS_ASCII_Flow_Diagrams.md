# VQMS — Complete ASCII Flow Diagrams

## What This Document Covers

VQMS is at Phase 3 complete. Both entry points (portal and email) are working, the AI pipeline
(context loading, query analysis, routing, KB search) is built and tested, and path decision
logic routes queries to Path A, B, or C (stubs for now). This document traces every step with
two levels of detail: one for developers who need cache keys and SQL tables, and one for
stakeholders who need the business logic in plain English.

**Reference scenario used throughout:** A vendor user from a Silver-tier company submitting
a payment status inquiry for an overdue invoice via the VQMS portal (Steps P1-P6). The query
has high confidence (0.92), gets routed to Finance Team with a 4-hour SLA, finds a strong
KB match, and enters Path A (AI-Resolved).

---

# DETAILED TECHNICAL ASCII FLOW

This section covers every implemented step with exact file paths, function names,
cache key patterns, SQL table names, S3 bucket paths, and SQS/EventBridge identifiers.
Steps marked `[STUB]` have code that sets status but delegates real work to a future phase.
Steps marked `[NOT BUILT]` have no code at all.

---

## APPLICATION STARTUP

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 0: APPLICATION STARTUP                                                  │
│                                                                              │
│ File: main.py -> lifespan()                                                  │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP 0.1: CONFIGURE STRUCTURED LOGGING                                │
│     - src/utils/logger.py -> setup_logging()                                 │
│     - structlog with shared processors (contextvars, timestamps, log level)  │
│     - Console: human-readable in DEBUG, JSON in INFO+                        │
│     - File: data/logs/vqms_YYYY-MM-DD.log (RotatingFileHandler, 10MB, 5x)   │
│     - Silences noisy loggers: uvicorn.access, httpx, httpcore                │
│                                                                              │
│   SUB-STEP 0.2: SSH TUNNEL TO BASTION HOST                                  │
│     - src/db/connection.py -> start_ssh_tunnel()                             │
│     - Only runs if SSH_HOST is set in .env                                   │
│     - Path: local machine --SSH--> bastion EC2 --TCP--> RDS PostgreSQL       │
│     - Opens a random local port that forwards to RDS:5432                    │
│     - Requires paramiko<4.0.0 (4.0 removed DSSKey support)                  │
│                                                                              │
│   SUB-STEP 0.3: POSTGRESQL CONNECTION POOL                                   │
│     - src/db/connection.py -> init_db()                                      │
│     - Async SQLAlchemy engine with asyncpg driver                            │
│     - Pool: min=5, max=20, pool_pre_ping=True                               │
│     - Runs SELECT 1 to verify; stores engine in module singleton             │
│                                                                              │
│   SUB-STEP 0.4: POSTGRESQL CACHE (KV STORE)                                  │
│     - src/cache/kv_store.py -> init_cache()                                  │
│     - PostgreSQL-backed key-value cache table                                │
│     - Runs connectivity check to verify                                      │
│                                                                              │
│   SUB-STEP 0.5: SQS PIPELINE CONSUMER (BACKGROUND TASK)                     │
│     - src/orchestration/sqs_consumer.py -> start_consumer()                  │
│     - Launched as asyncio.create_task (name="sqs-pipeline-consumer")         │
│     - Long-polls vqms-query-intake-queue, feeds LangGraph pipeline           │
│     - Shutdown via asyncio.Event.set() -> task.cancel()                      │
│                                                                              │
│   SUB-STEP 0.6: CORS + ROUTER MOUNTING                                      │
│     - CORSMiddleware: allows localhost:4200 (Angular dev server)             │
│     - Routers: auth, queries, webhooks, dashboard, email_dashboard           │
│                                                                              │
│ Why each piece:                                                              │
│   - SSH tunnel: RDS is in a private subnet with no public access. The        │
│     bastion host is the only way in.                                         │
│   - Async pool: All DB calls use await. The pool avoids opening a new TCP    │
│     connection per request (200ms saved per query).                          │
│   - PG Cache: Key-value caching backed by PostgreSQL replaces external       │
│     cache dependencies.                                                      │
│   - Background consumer: Decouples HTTP API from pipeline processing.        │
│     The API returns immediately; the consumer processes at its own pace.     │
│                                                                              │
│ Failure behavior: Each step catches exceptions independently. If the         │
│ SSH tunnel fails, the app starts without a database. The GET /health         │
│ endpoint reports which                                                       │
│ components are connected.                                                    │
│                                                                              │
│ Output: FastAPI app running on port 8000 with all routes mounted             │
│                                                                              │
│ Time: ~2-5s | Cost: $0 | LLM: No                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## PORTAL ENTRY PATH (Steps P1 - P6)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP P1: VENDOR LOGIN                                                        │
│                                                                              │
│ File: src/api/routes/auth.py -> login()                                      │
│ Endpoint: POST /auth/login                                                   │
│ Status: [IMPLEMENTED — fake dev auth, real Cognito in Phase 7]               │
│                                                                              │
│ Input:  { "email": "vendor@company.com", "password": "anything" }            │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP P1.1: GENERATE FAKE CREDENTIALS                                  │
│     - Accepts any email/password (dev mode, no real validation)              │
│     - Generates deterministic vendor_id from email domain hash               │
│     - Returns fake JWT token string (not cryptographically signed)           │
│                                                                              │
│ Why fake auth:                                                               │
│   - Cognito user pool is not configured yet. Fake auth lets us test          │
│     the full portal flow without waiting for infrastructure setup.           │
│   - The vendor_id is deterministic (same email always gets same ID)          │
│     so test data is consistent across sessions.                              │
│                                                                              │
│ Services used:                                                               │
│   - None (pure computation, no external calls)                               │
│                                                                              │
│ Output: { "token": "fake-jwt-...", "vendor_id": "V-XXXX",                   │
│           "vendor_name": "company.com" }                                     │
│                                                                              │
│ Time: <10ms | Cost: $0 | LLM: No                                            │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP P2: DASHBOARD LOADS                                                     │
│                                                                              │
│ File: src/api/routes/dashboard.py -> get_kpis(), list_queries()              │
│ Endpoints: GET /dashboard/kpis, GET /queries                                 │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  X-Vendor-ID header (from login response)                             │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP P2.1: FETCH KPI COUNTS                                           │
│     - Queries workflow.case_execution WHERE vendor_id = :vid                 │
│     - Counts: total, open (status NOT IN resolved/closed), resolved          │
│     - Falls back to zeros if DB is unavailable                               │
│     - TODO: PG Cache at vqms:dashboard:{vendor_id} (5-min TTL)              │
│                                                                              │
│   SUB-STEP P2.2: FETCH RECENT QUERIES                                       │
│     - Queries workflow.case_execution WHERE vendor_id = :vid                 │
│     - ORDER BY created_at DESC, LIMIT :limit OFFSET :offset                 │
│     - Returns list of {query_id, subject, status, created_at}               │
│                                                                              │
│ Why direct DB query (no cache yet):                                          │
│   - KPI cache (vqms:dashboard:{vendor_id}, 300s TTL) is planned but not     │
│     wired up. In dev mode, direct DB queries are fast enough. We will add    │
│     the cache when dashboards see real traffic.                              │
│                                                                              │
│ Services used:                                                               │
│   - PostgreSQL (workflow.case_execution): Source of truth for query state     │
│                                                                              │
│ Output: { "total_queries": N, "open_queries": N, "resolved_queries": N,     │
│           "recent_queries": [...] }                                          │
│                                                                              │
│ Time: ~50-200ms | Cost: $0 | LLM: No                                        │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEPS P3-P5: QUERY WIZARD (CLIENT-SIDE ONLY)                                │
│                                                                              │
│ Files: frontend/src/app/pages/ (Angular components)                          │
│   - new-query-type/   (P3: pick query type)                                  │
│   - new-query-details/ (P4: fill in subject, description, priority, ref#)    │
│   - new-query-review/  (P5: review and confirm before submit)                │
│ Status: [IMPLEMENTED — browser-default styling, no Cognito]                  │
│                                                                              │
│ Input:  User interaction (clicks, form fields)                               │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP P3: PICK QUERY TYPE                                              │
│     - 4 options: Billing/Payment, Purchase Order, Contract, General          │
│     - Selection stored in Angular wizard service (in-memory state)           │
│     - No server call — pure client-side navigation                           │
│                                                                              │
│   SUB-STEP P4: FILL IN DETAILS                                              │
│     - Subject (required), Description (required), Priority (optional),       │
│       Reference Number (optional, e.g. invoice or PO number)                 │
│     - Form validation on the client side                                     │
│     - No server call — data accumulates in wizard service                    │
│                                                                              │
│   SUB-STEP P5: REVIEW AND CONFIRM                                           │
│     - Displays all fields for final review                                   │
│     - "Edit" goes back to P4, "Submit" triggers POST /queries               │
│                                                                              │
│ Why a wizard (not a single form):                                            │
│   - Breaking submission into steps reduces form abandonment. Vendors         │
│     see one question at a time instead of a wall of fields.                  │
│   - The review step catches mistakes before they enter the pipeline.         │
│                                                                              │
│ Services used:                                                               │
│   - None (all client-side until Submit)                                      │
│                                                                              │
│ Output: Complete QuerySubmission data ready for POST /queries                │
│                                                                              │
│ Time: User-paced | Cost: $0 | LLM: No                                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP P6: SUBMIT QUERY                                                        │
│                                                                              │
│ File: src/api/routes/queries.py -> create_query()                            │
│     → src/services/portal_submission.py -> submit_portal_query()             │
│ Endpoint: POST /queries (status_code=201)                                    │
│ Decorator: @log_api_call                                                     │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  QuerySubmission { subject, description, query_type, priority,        │
│         reference_number } + X-Vendor-ID and X-Vendor-Name headers           │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP P6.1: EXTRACT VENDOR IDENTITY                                    │
│     - vendor_id from X-Vendor-ID header (NEVER from request body)            │
│     - Returns 401 if header is missing                                       │
│     - Phase 7: Will extract from Cognito JWT claims instead                  │
│                                                                              │
│   SUB-STEP P6.2: GENERATE TRACKING IDS                                      │
│     - src/utils/correlation.py -> generate_correlation_id() → UUID4          │
│     - src/utils/correlation.py -> generate_execution_id() → "EX-" + UUID4   │
│     - src/utils/correlation.py -> generate_query_id() → "VQ-YYYYMMDD-NNNNN" │
│                                                                              │
│   SUB-STEP P6.3: IDEMPOTENCY CHECK                                          │
│     - PG Cache key: vqms:idempotency:portal:{vendor_id}:{subject}           │
│     - TTL: 604,800s (7 days)                                                │
│     - If key exists → raise DuplicateQueryError → HTTP 409 Conflict         │
│     - If key missing → set key with TTL → proceed                           │
│     - If cache unavailable → log warning, allow through (fail-open)         │
│                                                                              │
│   SUB-STEP P6.4: BUILD UNIFIED PAYLOAD                                      │
│     - src/models/query.py -> UnifiedQueryPayload                             │
│     - source=PORTAL, thread_status=NEW                                       │
│     - Same model that the email path produces — pipeline is source-agnostic  │
│                                                                              │
│   SUB-STEP P6.5: STORE CASE EXECUTION                                       │
│     - Table: workflow.case_execution                                         │
│     - INSERT with ON CONFLICT (execution_id) DO NOTHING                      │
│     - Fields: execution_id, query_id, correlation_id, vendor_id, source,     │
│       status=OPEN, created_at                                                │
│     - Graceful if DB unavailable — the query still gets queued               │
│                                                                              │
│   SUB-STEP P6.6: PUBLISH EVENT                                              │
│     - EventBridge bus: vqms-event-bus, source: com.vqms                      │
│     - Event: "QueryReceived"                                                 │
│     - Detail: {query_id, execution_id, source, vendor_id, subject,           │
│       query_type, submitted_at}                                              │
│                                                                              │
│   SUB-STEP P6.7: ENQUEUE FOR AI PIPELINE                                    │
│     - SQS queue: vqms-query-intake-queue                                     │
│     - Message body: UnifiedQueryPayload serialized as JSON                   │
│     - Message attribute: correlation_id                                      │
│                                                                              │
│ Why we use each service:                                                     │
│   - PG Cache (idempotency key): Prevents the same query from creating two    │
│     tickets if the vendor double-clicks Submit. 7-day TTL because vendor     │
│     might retry a few days later if they think it did not go through.        │
│   - PostgreSQL (case_execution): The permanent record of every query.        │
│     Caches are fast but they expire. This is the source of truth.            │
│   - EventBridge (QueryReceived): Lets dashboards, audit trail, and SLA       │
│     services react to new queries without coupling them to intake code.      │
│   - SQS (query-intake-queue): Decouples the API response from AI            │
│     processing so the vendor gets their query_id back in under 500ms.        │
│     The AI pipeline picks it up asynchronously.                              │
│                                                                              │
│ Services used:                                                               │
│   - PG Cache (vqms:idempotency:portal:*): Duplicate detection               │
│   - PostgreSQL (workflow.case_execution): Permanent state record             │
│   - EventBridge (QueryReceived): Event notification                          │
│   - SQS (vqms-query-intake-queue): Pipeline handoff                         │
│                                                                              │
│ Output: HTTP 201 { query_id: "VQ-20260408-12345",                           │
│                     execution_id: "EX-...",                                   │
│                     correlation_id: "...",                                    │
│                     status: "accepted" }                                      │
│                                                                              │
│ Time: ~100-300ms | Cost: ~$0.0001 (SQS + EventBridge) | LLM: No            │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                          [ SQS: vqms-query-intake-queue ]
                          [ Message waits for consumer  ]
```

---

## EMAIL ENTRY PATH (Steps E1 - E2)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP E1: EMAIL ARRIVES — WEBHOOK NOTIFICATION                                │
│                                                                              │
│ File: src/api/routes/webhooks.py -> handle_graph_notification()              │
│ Endpoint: POST /webhooks/ms-graph (status_code=202)                          │
│ Decorator: @log_api_call                                                     │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  Microsoft Graph change notification JSON payload                     │
│         { value: [{ resource: "users/.../messages/AAMk...",                  │
│           changeType: "created", clientState: "..." }] }                     │
│         OR: validationToken query param (subscription setup)                 │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP E1.1: SUBSCRIPTION VALIDATION (one-time setup)                   │
│     - If ?validationToken= is present in query params                        │
│     - Echo the token back as text/plain with HTTP 200                        │
│     - This is Microsoft's handshake to confirm webhook ownership             │
│                                                                              │
│   SUB-STEP E1.2: PROCESS CHANGE NOTIFICATIONS (normal flow)                 │
│     - Iterate over each notification in the value[] array                    │
│     - For each: call process_email_notification(resource)                    │
│     - Handle DuplicateQueryError gracefully (skip, continue batch)           │
│     - Return 202 Accepted with per-notification results                      │
│                                                                              │
│ Why webhook + 202 pattern:                                                   │
│   - Microsoft Graph requires a 2xx response within 3 seconds or it           │
│     retries. We return 202 immediately and process asynchronously.           │
│   - Processing can take several seconds (S3 upload, DB writes, SQS),        │
│     so synchronous processing would trigger Microsoft's retry logic.         │
│                                                                              │
│ Services used:                                                               │
│   - Microsoft Graph API (webhook subscription): Push notification            │
│                                                                              │
│ Output: HTTP 202 { processed: N, results: [...] }                           │
│                                                                              │
│ Time: <100ms (response) | Cost: $0 | LLM: No                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP E2: EMAIL PROCESSING (11-step pipeline)                                 │
│                                                                              │
│ File: src/services/email_intake.py -> process_email_notification()           │
│ Decorator: @log_service_call                                                 │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  resource string (MS Graph resource path to the email)                │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP E2.1: FETCH EMAIL VIA GRAPH API                                  │
│     - src/adapters/graph_api.py -> fetch_email_by_resource(resource)         │
│     - MSAL OAuth2 client_credentials flow (token cached with 5-min buffer)  │
│     - GET https://graph.microsoft.com/v1.0/{resource}                       │
│       ?$expand=attachments&$select=id,subject,body,from,toRecipients,...     │
│     - Returns EmailMessage model with parsed headers, body, attachments      │
│                                                                              │
│   SUB-STEP E2.2: IDEMPOTENCY CHECK                                          │
│     - PG Cache key: vqms:idempotency:{message_id}                           │
│     - TTL: 604,800s (7 days)                                                │
│     - Why 7 days: Exchange Online can redeliver emails up to 5 days          │
│       after the original send during recovery. 7 days covers that.          │
│     - If key exists → raise DuplicateQueryError → skip this email           │
│     - If cache unavailable → log warning, allow through (fail-open)         │
│                                                                              │
│   SUB-STEP E2.3: VENDOR RESOLUTION (Salesforce 3-step fallback)             │
│     - src/adapters/salesforce.py -> find_vendor_by_email()                   │
│     - Step 1: Exact email match on Vendor_Contact__c.Email__c               │
│       (confidence 0.95)                                                      │
│     - Step 2: Regex for vendor ID pattern in email body                      │
│       (V-\d{3,6}|VN-\d{4,6}|SF-\d{3,6}), then SOQL lookup                 │
│       (confidence 0.90)                                                      │
│     - Step 3: Fuzzy name match on Vendor_Account__c.Name                    │
│       (confidence 0.60)                                                      │
│     - If all fail → vendor_id = None (UNRESOLVED), pipeline proceeds        │
│       and the orchestrator can route to human review                         │
│                                                                              │
│   SUB-STEP E2.4: THREAD CORRELATION                                         │
│     - Checks in_reply_to, references headers, and conversation_id           │
│     - If found → thread_status = EXISTING_OPEN (reply to existing query)    │
│     - If not found → thread_status = NEW                                     │
│     - Uses PG Cache key: vqms:thread:{message_id} (24h TTL)                 │
│                                                                              │
│   SUB-STEP E2.5: UPLOAD ATTACHMENTS TO S3                                   │
│     - S3 bucket: vqms-email-attachments-prod                                 │
│     - Key pattern: attachments/{message_id}/{filename}                       │
│     - Each attachment uploaded individually via src/storage/s3_client.py     │
│     - Returns list of S3 URIs for each attachment                            │
│                                                                              │
│   SUB-STEP E2.6: STORE RAW EMAIL TO S3                                      │
│     - S3 bucket: vqms-email-raw-prod                                         │
│     - Key pattern: emails/{message_id}.json                                  │
│     - Stores complete JSON with all headers, body, attachment metadata       │
│     - This is the compliance copy — never modified after write              │
│                                                                              │
│   SUB-STEP E2.7: GENERATE TRACKING IDS                                      │
│     - Same as portal: correlation_id (UUID4), execution_id (EX-UUID4),      │
│       query_id (VQ-YYYYMMDD-NNNNN)                                          │
│                                                                              │
│   SUB-STEP E2.8: STORE EMAIL METADATA IN POSTGRESQL                         │
│     - Table: intake.email_messages — sender, recipients, subject, body,     │
│       message_id, conversation_id, in_reply_to, received_at, s3_key,        │
│       vendor_id, thread_status, reference_number, amount, has_attachments   │
│     - Table: intake.email_attachments — for each attachment: filename,      │
│       content_type, size_bytes, s3_key                                       │
│                                                                              │
│   SUB-STEP E2.9: STORE CASE EXECUTION                                       │
│     - Table: workflow.case_execution (same as portal path P6.5)              │
│     - source=EMAIL, status=OPEN, thread_status from E2.4                     │
│                                                                              │
│   SUB-STEP E2.10: PUBLISH EVENT                                             │
│     - EventBridge bus: vqms-event-bus, source: com.vqms                      │
│     - Event: "EmailIngested"                                                 │
│     - Detail: {query_id, execution_id, source, vendor_id, message_id,        │
│       thread_status, has_attachments}                                        │
│                                                                              │
│   SUB-STEP E2.11: ENQUEUE FOR AI PIPELINE                                   │
│     - SQS queue: vqms-email-intake-queue                                     │
│     - Message body: UnifiedQueryPayload serialized as JSON                   │
│     - Same payload structure as the portal path                              │
│                                                                              │
│ Why we use each service:                                                     │
│   - Graph API (MSAL OAuth2): Fetches the actual email content. Webhooks     │
│     only tell us something arrived — we still need to download it.           │
│   - PG Cache (idempotency): Exchange Online can redeliver the same email    │
│     during recovery mode. Without this check, one email could create         │
│     multiple tickets.                                                        │
│   - Salesforce (vendor resolution): We need to know which vendor account    │
│     this email belongs to for routing, SLA, and history lookup. The          │
│     3-step fallback handles edge cases like shared inboxes and personal      │
│     email addresses.                                                         │
│   - S3 (raw email): Stores the original email exactly as received for       │
│     compliance. If a vendor disputes our response, we have proof of what     │
│     they originally wrote.                                                   │
│   - S3 (attachments): Large attachments do not belong in PostgreSQL.        │
│     S3 gives us cheap, durable storage with presigned download URLs.         │
│   - PostgreSQL (email_messages + attachments): Searchable metadata index.   │
│     S3 holds the files, PostgreSQL holds the fields we query against.        │
│   - EventBridge (EmailIngested): Audit trail, dashboard updates, and SLA    │
│     service can react without being coupled to the intake code.              │
│   - SQS (email-intake-queue): Same decoupling pattern as portal.            │
│                                                                              │
│ Services used:                                                               │
│   - Microsoft Graph API: Email fetch                                         │
│   - PG Cache (vqms:idempotency:{message_id}): Duplicate detection           │
│   - PG Cache (vqms:thread:{message_id}): Thread correlation lookup           │
│   - Salesforce CRM (Vendor_Account__c, Vendor_Contact__c): Vendor match     │
│   - S3 (vqms-email-raw-prod): Raw email archive                             │
│   - S3 (vqms-email-attachments-prod): Attachment files                       │
│   - PostgreSQL (intake.email_messages): Email metadata                       │
│   - PostgreSQL (intake.email_attachments): Attachment metadata               │
│   - PostgreSQL (workflow.case_execution): Central state record               │
│   - EventBridge (EmailIngested): Event notification                          │
│   - SQS (vqms-email-intake-queue): Pipeline handoff                         │
│                                                                              │
│ Output: UnifiedQueryPayload on SQS queue, same as portal path               │
│                                                                              │
│ Time: ~1-3s | Cost: ~$0.001 (S3 + SQS + EventBridge) | LLM: No            │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                          [ SQS: vqms-email-intake-queue ]
                          [ Message waits for consumer   ]
```

---

## CONVERGENCE POINT — BOTH PATHS MEET HERE

```
                    ┌─────────────────────┐     ┌──────────────────────┐
                    │ Portal Path (P6)    │     │ Email Path (E2)      │
                    │ vqms-query-intake   │     │ vqms-email-intake    │
                    └────────┬────────────┘     └──────────┬───────────┘
                             │                             │
                             │  Both produce identical     │
                             │  UnifiedQueryPayload        │
                             │                             │
                             ▼                             ▼
                    ┌──────────────────────────────────────────────────┐
                    │         SQS CONSUMER (Pipeline Entry)            │
                    │  src/orchestration/sqs_consumer.py               │
                    │  -> start_consumer()                             │
                    │                                                  │
                    │  Long-poll: WaitTimeSeconds=20                   │
                    │  MaxNumberOfMessages=1                           │
                    │  VisibilityTimeout=300s (5 min)                  │
                    │                                                  │
                    │  On receive:                                     │
                    │    1. Deserialize JSON → PipelineState           │
                    │    2. graph.ainvoke(initial_state)               │
                    │    3. Success → delete message from SQS          │
                    │    4. Failure → leave for retry (3x → DLQ)      │
                    └───────────────────┬──────────────────────────────┘
                                        │
                                        ▼
                              ┌─────────────────────┐
                              │  LangGraph Pipeline  │
                              │  (Steps 7 → 9)      │
                              └─────────┬───────────┘
                                        │
                                        ▼
```

---

## UNIFIED AI PIPELINE (Steps 7 - 9)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: CONTEXT LOADING                                                      │
│                                                                              │
│ File: src/orchestration/nodes/context_loading.py -> context_loading(state)   │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  PipelineState with payload, correlation_id, execution_id, query_id   │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP 7.1: UPDATE CASE STATUS                                          │
│     - PostgreSQL: UPDATE workflow.case_execution                             │
│       SET status = 'analyzing' WHERE execution_id = :eid                     │
│     - Marks the query as actively being processed by the AI pipeline        │
│                                                                              │
│   SUB-STEP 7.2: CACHE WORKFLOW STATE                                        │
│     - PG Cache key: vqms:workflow:{execution_id}                             │
│     - TTL: 86,400s (24 hours)                                               │
│     - Value: JSON {status, query_id, vendor_id, step: "context_loading"}    │
│     - Why 24h: Most queries resolve in minutes to hours. 24h is a safe      │
│       upper bound. After that, the source of truth is PostgreSQL.           │
│                                                                              │
│   SUB-STEP 7.3: LOAD VENDOR PROFILE                                        │
│     - src/services/memory_context.py -> load_vendor_profile()                │
│     - First check: PG Cache key vqms:vendor:{vendor_id} (1h TTL)           │
│     - Cache miss: Salesforce CRM lookup → cache result in PG Cache          │
│     - Returns: VendorProfile {vendor_id, vendor_name, tier, risk_flags,     │
│       account_manager, payment_terms}                                        │
│     - Why 1h TTL: Vendor tier changes rarely (maybe monthly), but we do     │
│       not want to serve stale risk_flags for more than an hour in case      │
│       compliance updates them.                                               │
│                                                                              │
│   SUB-STEP 7.4: LOAD VENDOR HISTORY                                        │
│     - src/services/memory_context.py -> load_vendor_history()                │
│     - PostgreSQL: SELECT * FROM memory.episodic_memory                       │
│       WHERE vendor_id = :vid ORDER BY created_at DESC LIMIT 10              │
│     - Returns last 10 queries by this vendor for context enrichment         │
│                                                                              │
│   SUB-STEP 7.5: INITIALIZE BUDGET                                          │
│     - src/models/budget.py -> Budget(max_tokens_in=8000,                     │
│       max_tokens_out=4096, currency_limit_usd=0.50)                          │
│     - Tracks cumulative token usage and cost across all LLM calls           │
│       for this query execution                                               │
│                                                                              │
│   SUB-STEP 7.6: AUDIT LOG                                                   │
│     - PostgreSQL: INSERT INTO audit.action_log                               │
│       (correlation_id, execution_id, action="CONTEXT_LOADED",                │
│        actor="system", timestamp)                                            │
│                                                                              │
│ Why we use each service:                                                     │
│   - PG Cache (vendor cache): Salesforce API calls take 200-500ms. Caching  │
│     the profile for 1 hour means we pay that cost once per vendor per        │
│     hour, not once per query.                                                │
│   - PostgreSQL (episodic_memory): Past queries give the AI context.          │
│     If a vendor asked about the same invoice last week, the AI knows        │
│     there is an ongoing issue and can reference the previous interaction.    │
│   - PostgreSQL (audit.action_log): Every state transition is recorded.       │
│     If something goes wrong, we can trace exactly what happened.            │
│                                                                              │
│ Services used:                                                               │
│   - PostgreSQL (workflow.case_execution): Status update                      │
│   - PG Cache (vqms:workflow:{execution_id}): Fast state cache                │
│   - PG Cache (vqms:vendor:{vendor_id}): Vendor profile cache                │
│   - Salesforce CRM (fallback): Vendor profile lookup                        │
│   - PostgreSQL (memory.episodic_memory): Vendor query history               │
│   - PostgreSQL (audit.action_log): Audit trail                              │
│                                                                              │
│ Output: PipelineState enriched with vendor_profile, vendor_history, budget   │
│                                                                              │
│ Time: ~200-800ms | Cost: $0 | LLM: No                                      │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 8: QUERY ANALYSIS AGENT (LLM CALL #1)                                  │
│                                                                              │
│ File: src/orchestration/nodes/query_analysis_node.py -> query_analysis()     │
│ Agent: src/agents/query_analysis.py -> QueryAnalysisAgent.analyze_query()    │
│ Base:  src/agents/abc_agent.py -> BaseAgent                                  │
│ Decorator: @log_llm_call (on factory), @log_service_call (on node)          │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  PipelineState with payload (subject, description, query_type),       │
│         vendor_profile (tier, risk_flags), vendor_history (last 10 queries)  │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP 8.1: RENDER PROMPT TEMPLATE                                      │
│     - Template: prompts/query_analysis/v1.jinja (Jinja2)                     │
│     - Variables: subject, description, query_type, vendor_name, vendor_tier, │
│       vendor_history (last 3 summaries), reference_number                    │
│     - System prompt: "You are a vendor query analysis agent.                 │
│       Return ONLY a valid JSON object."                                      │
│                                                                              │
│   SUB-STEP 8.2: CALL LLM VIA FACTORY                                       │
│     - src/llm/factory.py -> llm_complete(prompt, system_prompt,              │
│       temperature=0.1, max_tokens=1024)                                      │
│     - Primary: Amazon Bedrock Claude Sonnet 3.5                              │
│       (anthropic.claude-3-5-sonnet-20241022-v2:0)                           │
│     - Fallback: OpenAI GPT-4o (if Bedrock fails)                            │
│     - Temperature=0.1 for classification precision (low creativity)          │
│     - Typical: ~1500 tokens in, ~500 tokens out                             │
│                                                                              │
│   SUB-STEP 8.3: PARSE LLM RESPONSE INTO ANALYSISRESULT                     │
│     - Strip markdown fences (```json ... ```) if present                    │
│     - json.loads() → validate against AnalysisResult Pydantic model          │
│     - Fields: intent_classification, extracted_entities (invoices, dates,    │
│       amounts, PO numbers), urgency_level, sentiment, confidence_score,      │
│       multi_issue_detected, suggested_category                               │
│     - On parse failure: append fix instruction, retry LLM once              │
│     - On second failure: return low-confidence result (confidence=0.30)      │
│       which routes to Path C (human review) — safe fallback                 │
│                                                                              │
│   SUB-STEP 8.4: PERSIST ANALYSIS RESULT                                    │
│     - PostgreSQL: UPDATE workflow.case_execution SET                          │
│       analysis_result = :json, status = 'analysis_complete',                 │
│       intent = :intent, urgency = :urgency, confidence = :score             │
│     - PG Cache: UPDATE vqms:workflow:{execution_id} with                     │
│       {confidence, intent, urgency, step: "query_analysis"}                 │
│                                                                              │
│   SUB-STEP 8.5: UPLOAD PROMPT SNAPSHOT FOR AUDIT                           │
│     - S3 bucket: vqms-knowledge-artifacts-prod                               │
│     - Key: audit/prompts/{execution_id}/query_analysis.json                  │
│     - Contains: rendered prompt, raw LLM response, parsed result            │
│     - Why: Prompt audit trail for compliance. If the AI makes a wrong        │
│       classification, we can inspect exactly what it saw and said.           │
│                                                                              │
│   SUB-STEP 8.6: PUBLISH EVENT + AUDIT LOG                                  │
│     - EventBridge: "AnalysisCompleted" with intent, confidence, urgency      │
│     - PostgreSQL: INSERT INTO audit.action_log                               │
│       (action="ANALYSIS_COMPLETED", ...)                                     │
│                                                                              │
│ Why we use each service:                                                     │
│   - Bedrock Claude Sonnet 3.5: Best balance of speed (~3s) and accuracy     │
│     for classification tasks. Temperature 0.1 keeps outputs consistent.     │
│   - LLM Factory (fallback): If Bedrock has an outage, the pipeline          │
│     switches to OpenAI GPT-4o automatically. The vendor does not notice.    │
│   - S3 (prompt snapshot): Every LLM call is auditable. We can replay        │
│     the exact prompt months later to debug a misclassification.             │
│                                                                              │
│ Services used:                                                               │
│   - Amazon Bedrock (Claude Sonnet 3.5): LLM inference                       │
│   - OpenAI GPT-4o (fallback): LLM inference if Bedrock fails               │
│   - PostgreSQL (workflow.case_execution): Result persistence                 │
│   - PG Cache (vqms:workflow:{execution_id}): Fast state update               │
│   - S3 (vqms-knowledge-artifacts-prod): Prompt audit trail                   │
│   - EventBridge (AnalysisCompleted): Event notification                      │
│   - PostgreSQL (audit.action_log): Audit trail                              │
│                                                                              │
│ Output: PipelineState with analysis_result (AnalysisResult as dict)          │
│                                                                              │
│ Time: ~2-5s | Cost: ~$0.012 (1500 tokens in, 500 out) | LLM: Yes           │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ DECISION POINT 1: CONFIDENCE CHECK                                           │
│                                                                              │
│ File: src/orchestration/nodes/confidence_check.py -> confidence_check()      │
│ Type: LangGraph conditional edge function (NOT a regular node)               │
│ Decorator: @log_policy_decision                                              │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  PipelineState with analysis_result.confidence_score                  │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   - Reads confidence_score from analysis_result                              │
│   - Threshold: settings.agent_confidence_threshold (default 0.85)            │
│   - This threshold is configurable via AGENT_CONFIDENCE_THRESHOLD env var    │
│                                                                              │
│ Branching:                                                                   │
│   confidence >= 0.85  →  returns "pass"  →  routing_and_kb_search            │
│   confidence <  0.85  →  returns "fail"  →  path_c_stub                      │
│                                                                              │
│ Why 0.85 threshold:                                                          │
│   - Below 0.85, the AI is not sure enough about the query's intent to        │
│     make routing and KB search decisions. Sending an uncertain analysis      │
│     to routing could assign the wrong team or miss the right KB articles.    │
│   - Path C pauses the workflow entirely until a human reviewer validates     │
│     the AI's analysis, so false positives (AI is wrong but confident)        │
│     are the bigger risk. 0.85 is conservative enough to catch most           │
│     ambiguous queries without flooding reviewers with easy ones.             │
│                                                                              │
│ Output: "pass" or "fail" (string, used by LangGraph conditional edge)        │
│                                                                              │
│ Time: <1ms | Cost: $0 | LLM: No                                             │
└──────────────────────────────────────────────────────────────────────────────┘
                          │                              │
               ┌──────────┘                              └──────────┐
               │ confidence >= 0.85                   confidence < 0.85 │
               ▼                                                    ▼
   [ routing_and_kb_search ]                          [ path_c_stub ]
   [ Step 9 below ]                                   [ See Path C stub ]
```

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 9: ROUTING + KB SEARCH (PARALLEL EXECUTION)                             │
│                                                                              │
│ File: src/orchestration/nodes/routing_and_kb_search.py                       │
│     -> routing_and_kb_search(state)                                          │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  PipelineState with analysis_result, vendor_profile                   │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   Both sub-steps run IN PARALLEL via asyncio.gather():                       │
│                                                                              │
│   ┌─────────────────────────────────┐ ┌─────────────────────────────────┐    │
│   │ SUB-STEP 9A: ROUTING ENGINE    │ │ SUB-STEP 9B: KB SEARCH         │    │
│   │                                 │ │                                 │    │
│   │ src/services/routing.py         │ │ src/services/kb_search.py       │    │
│   │   -> route_query()              │ │   -> search_kb()                │    │
│   │                                 │ │                                 │    │
│   │ Pure rules, NO LLM:            │ │ Embedding + vector search:      │    │
│   │                                 │ │                                 │    │
│   │ 1. SLA matrix lookup:          │ │ 1. Embed query text via         │    │
│   │    VendorTier × UrgencyLevel   │ │    llm_embed() → Titan Embed   │    │
│   │    → SLA hours                  │ │    v2 (1536 dimensions)         │    │
│   │                                 │ │                                 │    │
│   │    PLATINUM:                    │ │ 2. pgvector cosine similarity:  │    │
│   │      CRITICAL=1h, HIGH=2h      │ │    SELECT * FROM                │    │
│   │      MEDIUM=4h,   LOW=8h       │ │    memory.embedding_index       │    │
│   │    GOLD:                        │ │    WHERE category = :cat        │    │
│   │      CRITICAL=2h, HIGH=4h      │ │    ORDER BY embedding           │    │
│   │      MEDIUM=8h,   LOW=16h      │ │      <=> :vec::vector           │    │
│   │    SILVER:                      │ │    LIMIT 5                      │    │
│   │      CRITICAL=4h, HIGH=4h      │ │                                 │    │
│   │      MEDIUM=8h,   LOW=24h      │ │ 3. Filter by threshold:         │    │
│   │    STANDARD:                    │ │    KB_MATCH_THRESHOLD = 0.80    │    │
│   │      CRITICAL=4h, HIGH=8h      │ │                                 │    │
│   │      MEDIUM=24h,  LOW=48h      │ │ 4. Detect specific facts via    │    │
│   │                                 │ │    7 regex patterns:            │    │
│   │ 2. Team assignment:            │ │    - Dollar amounts ($X,XXX)    │    │
│   │    invoice_payment → Finance   │ │    - Dates (MM/DD/YYYY)         │    │
│   │    purchase_order → Procurement│ │    - Net payment terms           │    │
│   │    contract → Contract         │ │    - Numbered steps (1. 2. 3.)  │    │
│   │    general → General Support   │ │    - Timeframes (X days/weeks)  │    │
│   │                                 │ │    - Percentages (X%)           │    │
│   │ 3. Check automation block:     │ │    - Rupee amounts              │    │
│   │    risk_flags contains         │ │                                 │    │
│   │    "BLOCK_AUTOMATION" → block  │ │ Output: KBSearchResponse with   │    │
│   │                                 │ │   ranked KBSearchResult items,  │    │
│   │ Output: RoutingDecision with   │ │   top_score, has_specific_facts │    │
│   │   team, sla_hours, sla_deadline│ │                                 │    │
│   └─────────────────────────────────┘ └─────────────────────────────────┘    │
│                                                                              │
│ Why parallel:                                                                │
│   - Routing is ~10ms (pure rules). KB search is ~500-1500ms (embedding +    │
│     pgvector query). Running them in parallel means total time equals        │
│     the slower one, not the sum.                                             │
│                                                                              │
│ Why we use each service:                                                     │
│   - SLA matrix (in-memory dict): Fast lookup, no DB query needed. The       │
│     matrix is small (16 cells) and changes rarely — config, not data.       │
│   - Bedrock Titan Embed v2: Converts query text to a 1536-dim vector        │
│     that captures semantic meaning. "My invoice is late" and "payment       │
│     not received" produce similar vectors.                                   │
│   - pgvector (memory.embedding_index): Stores pre-embedded KB article       │
│     chunks. Cosine similarity finds the most relevant articles even          │
│     when the exact words differ.                                             │
│                                                                              │
│ Services used:                                                               │
│   - In-memory SLA matrix: Routing rules                                      │
│   - Amazon Bedrock Titan Embed v2: Query embedding                           │
│   - PostgreSQL pgvector (memory.embedding_index): Vector similarity search  │
│   - PostgreSQL (workflow.routing_decision): Routing result persistence       │
│                                                                              │
│ Output: PipelineState with routing_decision + kb_search_response             │
│                                                                              │
│ Time: ~500-1500ms | Cost: ~$0.0001 (embedding) | LLM: Embedding only       │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ DECISION POINT 2: PATH DECISION                                              │
│                                                                              │
│ File: src/orchestration/nodes/path_decision.py -> path_decision(state)       │
│ Type: LangGraph conditional edge function                                    │
│ Decorator: @log_policy_decision                                              │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Input:  PipelineState with kb_search_response, routing_decision              │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   Evaluates three conditions:                                                │
│     1. KB top_score >= 0.80 (configurable via KB_MATCH_THRESHOLD)            │
│     2. At least one KB result has has_specific_facts = True                  │
│     3. routing_decision.automation_blocked = False                           │
│                                                                              │
│ Branching:                                                                   │
│   All three pass  →  "path_a"  →  Path A: AI-Resolved                       │
│   Any one fails   →  "path_b"  →  Path B: Human-Team-Resolved               │
│                                                                              │
│ Why three conditions:                                                        │
│   - High similarity alone is not enough. A KB article could match well       │
│     but only contain general guidance, not specific dates or amounts.        │
│     The Resolution Agent needs concrete facts to write a useful answer.     │
│   - The automation block flag lets compliance or account managers force      │
│     a query to go to a human team regardless of KB quality.                 │
│                                                                              │
│ Output: "path_a" or "path_b" (string, used by LangGraph conditional edge)    │
│                                                                              │
│ Time: <1ms | Cost: $0 | LLM: No                                             │
└──────────────────────────────────────────────────────────────────────────────┘
                          │                              │
               ┌──────────┘                              └──────────┐
               │ path_a (AI resolves)               path_b (human team) │
               ▼                                                    ▼
```

---

## PATH STUBS (Phase 4-5 placeholders)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ PATH A STUB: AI-RESOLVED                                                     │
│                                                                              │
│ File: src/orchestration/nodes/path_stubs.py -> path_a_stub(state)            │
│ Status: [STUB — Phase 4 will add Resolution Agent]                           │
│                                                                              │
│ What it does now:                                                            │
│   - Sets selected_path = "A"                                                 │
│   - UPDATE workflow.case_execution SET status = 'resolving_ai',              │
│     selected_path = 'A'                                                      │
│   - UPDATE PG Cache vqms:workflow:{execution_id} with path + status          │
│   - Publish EventBridge "PathASelected"                                      │
│   - INSERT INTO audit.action_log (action="PATH_A_SELECTED")                  │
│                                                                              │
│ What Phase 4 will add:                                                       │
│   - Resolution Agent (LLM Call #2): Generates full resolution email          │
│     using KB articles as source material                                     │
│   - Quality & Governance Gate: 7-check validation on the draft               │
│   - ServiceNow ticket creation (team MONITORS, not investigates)             │
│   - Email delivery via MS Graph /sendMail                                    │
│                                                                              │
│ Time: ~50ms (stub) | Cost: $0 | LLM: No (stub)                             │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ PATH B STUB: HUMAN-TEAM-RESOLVED                                            │
│                                                                              │
│ File: src/orchestration/nodes/path_stubs.py -> path_b_stub(state)            │
│ Status: [STUB — Phase 4 will add Communication Agent]                        │
│                                                                              │
│ What it does now:                                                            │
│   - Sets selected_path = "B"                                                 │
│   - UPDATE workflow.case_execution SET status = 'awaiting_team_resolution',  │
│     selected_path = 'B'                                                      │
│   - UPDATE PG Cache vqms:workflow:{execution_id} with path + status          │
│   - Publish EventBridge "PathBSelected"                                      │
│   - INSERT INTO audit.action_log (action="PATH_B_SELECTED")                  │
│                                                                              │
│ What Phase 4 will add:                                                       │
│   - Communication Drafting Agent: Acknowledgment-only email (NOT a           │
│     resolution — no answer content, just "we received it, ticket is          │
│     INC..., our team is reviewing")                                          │
│   - Quality Gate validation                                                  │
│   - ServiceNow ticket creation (team MUST investigate)                       │
│   - Acknowledgment email delivery via MS Graph                               │
│   - Later: team marks resolved → Communication Agent drafts resolution      │
│     from team's notes (LLM Call #2)                                          │
│                                                                              │
│ Time: ~50ms (stub) | Cost: $0 | LLM: No (stub)                             │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ PATH C STUB: LOW-CONFIDENCE HUMAN REVIEW                                     │
│                                                                              │
│ File: src/orchestration/nodes/path_stubs.py -> path_c_stub(state)            │
│ Status: [STUB — Phase 5 will add TriagePackage + Step Functions]             │
│                                                                              │
│ What it does now:                                                            │
│   - Sets selected_path = "C"                                                 │
│   - UPDATE workflow.case_execution SET status = 'awaiting_human_review',     │
│     selected_path = 'C'                                                      │
│   - UPDATE PG Cache vqms:workflow:{execution_id} with path + status          │
│   - Publish EventBridge "HumanReviewRequired"                                │
│   - INSERT INTO audit.action_log (action="PATH_C_SELECTED")                  │
│                                                                              │
│ What Phase 5 will add:                                                       │
│   - Create TriagePackage: original query + AI analysis + confidence          │
│     breakdown + suggested routing + suggested draft                          │
│   - Push to vqms-human-review-queue (SQS)                                    │
│   - Step Functions pause via callback token pattern — NOTHING happens        │
│     until human reviewer acts                                                │
│   - Reviewer corrects via POST /triage/{id}/review                           │
│   - SendTaskSuccess resumes workflow with corrected data                     │
│   - SLA clock starts AFTER review, not before                                │
│                                                                              │
│ Time: ~50ms (stub) | Cost: $0 | LLM: No (stub)                             │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## CROSS-CUTTING: LLM FACTORY

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ LLM FACTORY — SINGLE ENTRY POINT FOR ALL AI CALLS                           │
│                                                                              │
│ File: src/llm/factory.py                                                     │
│ Protocol: src/llm/protocol.py -> LLMProvider                                 │
│ Providers:                                                                   │
│   - src/adapters/bedrock.py -> BedrockProvider                               │
│   - src/adapters/openai_provider.py -> OpenAIProvider                        │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Two public functions (the ONLY way to call LLMs in the codebase):            │
│                                                                              │
│   llm_complete(prompt, system_prompt, temperature, max_tokens)               │
│     → { text, tokens_in, tokens_out, cost_usd, latency_ms,                  │
│         model, provider, was_fallback }                                      │
│                                                                              │
│   llm_embed(text)                                                            │
│     → { vector: list[float], tokens, cost_usd, latency_ms,                  │
│         model, provider, was_fallback }                                      │
│                                                                              │
│ Provider modes (set via LLM_PROVIDER / EMBEDDING_PROVIDER env vars):         │
│                                                                              │
│   bedrock_with_openai_fallback  (default)                                    │
│     → Try Bedrock first. If it fails, switch to OpenAI.                      │
│                                                                              │
│   openai_with_bedrock_fallback                                               │
│     → Try OpenAI first. If it fails, switch to Bedrock.                      │
│                                                                              │
│   bedrock_only                                                               │
│     → Bedrock only. Raises LLMProviderError if Bedrock fails.                │
│                                                                              │
│   openai_only                                                                │
│     → OpenAI only. Raises LLMProviderError if OpenAI fails.                  │
│                                                                              │
│ Embedding compatibility:                                                     │
│   - Bedrock Titan Embed v2: 1536 dimensions                                  │
│   - OpenAI text-embedding-3-small: 1536 dimensions (explicitly set)          │
│   - Both produce the same vector size → pgvector index works with either    │
│                                                                              │
│ Cost tracking (per call):                                                    │
│   - Bedrock Claude: $0.003/1K input + $0.015/1K output                      │
│   - Bedrock Titan Embed: $0.0001/1K tokens                                   │
│   - OpenAI GPT-4o: $0.005/1K input + $0.015/1K output                      │
│   - OpenAI text-embedding-3-small: $0.00002/1K tokens                        │
│                                                                              │
│ Why a factory with fallback:                                                 │
│   - One env var change switches the entire system between providers.          │
│     Useful during Bedrock outages or when comparing model quality.           │
│   - Fallback mode keeps the pipeline running if the primary provider         │
│     has a transient failure. The vendor does not notice the switch.           │
│   - Nobody imports from bedrock.py or openai_provider.py directly.           │
│     All calls go through the factory. This means we can add a third          │
│     provider (Anthropic direct API, Google Vertex, etc.) without             │
│     touching any code outside src/llm/.                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## CROSS-CUTTING: PRODUCTION LOGGING SYSTEM

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ STRUCTURED LOGGING — EVERY ACTION IS TRACEABLE                               │
│                                                                              │
│ Files:                                                                       │
│   - src/utils/logger.py -> setup_logging() + 4 decorators                    │
│   - src/utils/log_context.py -> LogContext (frozen dataclass)                 │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Log destinations:                                                            │
│   - Console: human-readable in DEBUG, JSON in INFO+                          │
│   - File: data/logs/vqms_YYYY-MM-DD.log                                     │
│     RotatingFileHandler: 10 MB max, 5 backups                                │
│                                                                              │
│ Four decorators applied across the codebase:                                 │
│                                                                              │
│   @log_api_call      → FastAPI route handlers                                │
│     Logs: method, path, status_code, latency_ms, correlation_id              │
│     Applied to: create_query, handle_graph_notification, get_kpis, etc.      │
│                                                                              │
│   @log_service_call  → Services, adapters, orchestration nodes               │
│     Logs: service_name, function, latency_ms, success/error                  │
│     Applied to: submit_portal_query, process_email_notification, etc.        │
│                                                                              │
│   @log_llm_call      → LLM factory functions                                │
│     Logs: tokens_in, tokens_out, cost_usd, model, provider, was_fallback,   │
│           latency_ms                                                         │
│     Applied to: llm_complete, llm_embed                                      │
│                                                                              │
│   @log_policy_decision → Conditional routing functions                       │
│     Logs: decision, threshold, actual_value, safety_flags                    │
│     Applied to: confidence_check, path_decision                              │
│                                                                              │
│ LogContext dataclass (frozen/immutable):                                      │
│   - correlation_id, execution_id, query_id                                   │
│   - agent_role, step, status, tool                                           │
│   - latency_ms, tokens_in, tokens_out, cost_usd                             │
│   - model, provider, was_fallback                                            │
│   - policy_decision, safety_flags                                            │
│   - Methods: to_dict(), with_update(), with_llm_result(), from_state()       │
│   - Flows through the entire pipeline as extra={} in log calls               │
│                                                                              │
│ Why structured JSON logging:                                                 │
│   - A single vendor query touches 10+ services, multiple DB writes,          │
│     and at least one LLM call. With unstructured text logs, finding          │
│     all events for one query means grepping through thousands of lines.      │
│   - Structured JSON with correlation_id lets us filter for one query:        │
│     jq 'select(.correlation_id == "abc-123")' vqms.log                      │
│   - The cost_usd and tokens fields let us track AI spending per query        │
│     without a separate billing system.                                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## CROSS-CUTTING: DATABASE ARCHITECTURE

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ POSTGRESQL — 5 SCHEMAS, 11 TABLES, SSH TUNNEL ACCESS                        │
│                                                                              │
│ File: src/db/connection.py                                                   │
│ Migrations: src/db/migrations/ (6 SQL files)                                 │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Connection path:                                                             │
│   Local machine ──SSH──> Bastion EC2 ──TCP──> RDS PostgreSQL                 │
│   (sshtunnel lib)        (port 22)           (port 5432)                     │
│                                                                              │
│ Schemas and tables:                                                          │
│                                                                              │
│   intake (2 tables):                                                         │
│     email_messages     — sender, recipients, subject, body, message_id,     │
│                          s3_key, vendor_id, thread_status, reference, amount │
│     email_attachments  — filename, content_type, size_bytes, s3_key          │
│                                                                              │
│   workflow (3 tables):                                                       │
│     case_execution     — THE central state table. Every query gets one row. │
│                          status, analysis_result (JSONB), selected_path,     │
│                          vendor_id, source, created_at, updated_at           │
│     ticket_link        — Links execution_id to ServiceNow ticket_id          │
│     routing_decision   — team, sla_hours, sla_deadline, automation_level     │
│                                                                              │
│   memory (3 tables):                                                         │
│     episodic_memory       — Past query summaries per vendor (for context)    │
│     vendor_profile_cache  — Cached Salesforce vendor data                    │
│     embedding_index       — pgvector column (1536 dims), HNSW index          │
│                              (m=16, ef_construction=64) for KB search        │
│                                                                              │
│   audit (2 tables):                                                          │
│     action_log         — Every state transition with correlation_id,         │
│                          timestamp, actor, action, details (JSONB)           │
│     validation_results — Quality Gate results (Phase 4)                      │
│                                                                              │
│   reporting (1 table):                                                       │
│     sla_metrics        — SLA tracking data (Phase 6)                         │
│                                                                              │
│ Connection pool: async SQLAlchemy + asyncpg, min=5, max=20                   │
│ pgvector extension: HNSW index for approximate nearest neighbor              │
│   (faster than exact search at the cost of tiny accuracy loss)               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## CROSS-CUTTING: CACHE KEY FAMILIES

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ PG CACHE — 7 KEY FAMILIES WITH PURPOSE-DRIVEN TTLS                           │
│                                                                              │
│ File: src/cache/kv_store.py                                                  │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ Key Pattern                          │ TTL       │ Why That TTL              │
│ ─────────────────────────────────────┼───────────┼─────────────────────────  │
│ vqms:idempotency:{id}               │ 7 days    │ Exchange Online can        │
│   (email message_id or              │ (604800s) │ redeliver emails up to     │
│    portal:{vendor}:{subject})       │           │ 5 days during recovery.    │
│                                      │           │ 7 days covers that.        │
│ ─────────────────────────────────────┼───────────┼─────────────────────────  │
│ vqms:session:{token}                 │ 8 hours   │ Matches a typical work     │
│                                      │ (28800s)  │ session. Avoids re-auth    │
│                                      │           │ every request.             │
│ ─────────────────────────────────────┼───────────┼─────────────────────────  │
│ vqms:vendor:{vendor_id}              │ 1 hour    │ Vendor data changes        │
│                                      │ (3600s)   │ rarely, but risk_flags     │
│                                      │           │ could be updated by        │
│                                      │           │ compliance mid-day.        │
│ ─────────────────────────────────────┼───────────┼─────────────────────────  │
│ vqms:workflow:{execution_id}         │ 24 hours  │ Most queries resolve in    │
│                                      │ (86400s)  │ minutes to hours. 24h     │
│                                      │           │ covers edge cases. After   │
│                                      │           │ that, PostgreSQL is the    │
│                                      │           │ source of truth.           │
│ ─────────────────────────────────────┼───────────┼─────────────────────────  │
│ vqms:sla:{ticket_id}                 │ No expiry │ SLA state is actively      │
│                                      │ (0)       │ managed by the SLA         │
│                                      │           │ monitor which deletes      │
│                                      │           │ keys explicitly.           │
│ ─────────────────────────────────────┼───────────┼─────────────────────────  │
│ vqms:dashboard:{vendor_id}           │ 5 minutes │ KPI queries hit multiple   │
│                                      │ (300s)    │ tables. Vendors do not     │
│                                      │           │ need real-time dashboard   │
│                                      │           │ data. 5 min is fine.       │
│ ─────────────────────────────────────┼───────────┼─────────────────────────  │
│ vqms:thread:{message_id}             │ 24 hours  │ Thread correlation is      │
│                                      │ (86400s)  │ needed during active       │
│                                      │           │ processing. Irrelevant     │
│                                      │           │ after resolution.          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## CROSS-CUTTING: EMAIL DASHBOARD APIS

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ EMAIL DASHBOARD — 4 ENDPOINTS FOR THE ANGULAR INBOX VIEW                     │
│                                                                              │
│ File: src/api/routes/email_dashboard.py                                      │
│ Service: src/services/email_dashboard_service.py                             │
│ Status: [IMPLEMENTED]                                                        │
│                                                                              │
│ GET /emails                                                                  │
│   - Paginated list of email chains (limit, offset)                           │
│   - Filters: status (New/Reopened/Resolved), priority (High/Medium/Low)      │
│   - Search: text search across subject and body                              │
│   - Sort: by timestamp/status/priority, asc/desc                             │
│   - Response: MailChainListResponse { items, total, limit, offset }          │
│                                                                              │
│ GET /emails/stats                                                            │
│   - Aggregate statistics for dashboard header                                │
│   - Total count, counts by status, counts by priority, recent counts         │
│   - Response: EmailStatsResponse                                             │
│                                                                              │
│ GET /emails/{query_id}                                                       │
│   - Single email chain with all thread messages                              │
│   - Response: MailChainResponse { chain, messages }                          │
│                                                                              │
│ GET /emails/{query_id}/attachments/{attachment_id}/download                   │
│   - Generates presigned S3 URL for attachment download                       │
│   - URL expires in 1 hour                                                    │
│   - Response: AttachmentDownloadResponse { download_url, expires_in }        │
│                                                                              │
│ Why these endpoints:                                                         │
│   - The Angular frontend needs a clean API contract to render the email      │
│     inbox view. These endpoints match the TypeScript types (MailItem,        │
│     MailChain, Attachment, User) that the frontend expects.                  │
│   - Presigned URLs avoid proxying large attachment files through our         │
│     API server. The browser downloads directly from S3.                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## COMPLETE PIPELINE SUMMARY

```
    PORTAL PATH                              EMAIL PATH
    ───────────                              ──────────
    Angular Wizard (P1-P5)                   MS Graph Webhook (E1)
         │                                        │
         ▼                                        ▼
    POST /queries (P6)                   process_email_notification (E2)
    ┌─ idempotency check ─┐              ┌─ fetch email ──────────────┐
    │  generate IDs        │              │  idempotency check         │
    │  store case_execution│              │  vendor resolution (SF)    │
    │  EventBridge event   │              │  thread correlation        │
    │  SQS enqueue         │              │  S3 raw + attachments      │
    └──────────┬───────────┘              │  store metadata + case     │
               │                          │  EventBridge event         │
               │                          │  SQS enqueue               │
               │                          └──────────┬────────────────┘
               │                                     │
               └──────────────┬──────────────────────┘
                              │
                              ▼
                    [ SQS Consumer ]
                    [ LangGraph Pipeline ]
                              │
                    Step 7: Context Loading
                    (vendor profile, history, budget)
                              │
                    Step 8: Query Analysis (LLM #1)
                    (intent, urgency, confidence)
                              │
                    ┌─── confidence >= 0.85? ───┐
                    │ YES                    NO  │
                    ▼                            ▼
             Step 9: Routing               PATH C STUB
             + KB Search (parallel)    (awaiting_human_review)
                    │
             ┌── KB match >= 0.80
             │   + has_specific_facts?
             │   + not blocked?
             │ YES              NO
             ▼                  ▼
        PATH A STUB        PATH B STUB
     (resolving_ai)   (awaiting_team_resolution)
```

---

# SIMPLE MANAGER-FRIENDLY ASCII FLOW

This section explains the same system in plain English. No service names,
no cache keys, no SQL tables. If you are not a developer, read this section.

---

```
┌──────────────────────────────────────────────────────────────────┐
│  STEP 1: VENDOR LOGS INTO THE PORTAL                             │
│                                                                  │
│  What comes in:  An email address and password.                  │
│                                                                  │
│  What happens:   The vendor opens the VQMS portal in their       │
│  browser and logs in. Right now, any email/password works         │
│  because we are using a temporary login system for testing.       │
│  Later, this will use the company's single sign-on (SSO) so      │
│  vendors use their existing credentials.                         │
│                                                                  │
│  After login, the vendor sees a dashboard showing how many       │
│  queries they have open, how many are resolved, and a list       │
│  of their recent submissions.                                    │
│                                                                  │
│  Why this step:  Without it, anyone could submit queries         │
│  pretending to be any vendor. The login ties every query          │
│  to a verified vendor account.                                   │
│                                                                  │
│  What goes out:  A logged-in session with the vendor's identity  │
│  attached to every future action.                                │
│                                                                  │
│  Time: A few seconds                                             │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 2: VENDOR FILLS OUT THE QUERY FORM                         │
│                                                                  │
│  What comes in:  The vendor decides to submit a new query.       │
│                                                                  │
│  What happens:   A three-step wizard walks the vendor through    │
│  the submission:                                                 │
│                                                                  │
│  Screen 1 — Pick the type of query (billing, purchase order,     │
│  contract, or general question).                                 │
│                                                                  │
│  Screen 2 — Fill in the details: subject line, full              │
│  description of the issue, priority level, and any reference     │
│  numbers (like an invoice number or PO number).                  │
│                                                                  │
│  Screen 3 — Review everything before submitting. The vendor      │
│  can go back and edit if something looks wrong.                  │
│                                                                  │
│  Nothing is sent to the server until the vendor clicks Submit.   │
│                                                                  │
│  Why this step:  Breaking it into small screens reduces           │
│  mistakes. The review screen catches typos and missing details   │
│  before they enter the system.                                   │
│                                                                  │
│  What goes out:  A complete query ready to be submitted.         │
│                                                                  │
│  Time: However long the vendor takes to fill it out              │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 3: SYSTEM ACCEPTS THE QUERY                                │
│                                                                  │
│  What comes in:  The completed query form from the vendor.       │
│                                                                  │
│  What happens:   Five things happen in under half a second:      │
│                                                                  │
│  1. The system checks if this exact query was already            │
│     submitted. If the vendor accidentally double-clicked         │
│     Submit, it catches the duplicate and returns the same        │
│     tracking number instead of creating two tickets.             │
│                                                                  │
│  2. Three tracking numbers are generated: a query ID that        │
│     the vendor sees (like VQ-2026-12345), an internal            │
│     execution ID for tracing, and a correlation ID that          │
│     follows this query through every system it touches.          │
│                                                                  │
│  3. The query is saved to the permanent database.                │
│                                                                  │
│  4. A notification event is fired so other parts of the system   │
│     (dashboards, audit logs) know a new query arrived.           │
│                                                                  │
│  5. The query is placed into a processing queue for the AI       │
│     to pick up.                                                  │
│                                                                  │
│  The vendor immediately gets back their tracking number.         │
│  They do not wait for the AI to finish analyzing.                │
│                                                                  │
│  Why this step:  Without it, a slow AI response would make       │
│  the vendor wait 10+ seconds staring at a spinner. By            │
│  queuing the work, the vendor gets their tracking number         │
│  instantly and the AI works in the background.                   │
│                                                                  │
│  What goes out:  A tracking number back to the vendor.           │
│  Behind the scenes, the query sits in a queue waiting for AI.    │
│                                                                  │
│  Time: Under half a second                                       │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 3B: WHAT HAPPENS WHEN A VENDOR EMAILS INSTEAD              │
│                                                                  │
│  What comes in:  An email sent to the shared vendor support      │
│  mailbox.                                                        │
│                                                                  │
│  What happens:   The system watches the mailbox and picks        │
│  up new emails automatically. No person checks the inbox.        │
│                                                                  │
│  For each email, it does six things:                             │
│                                                                  │
│  1. Downloads the full email content and any attachments.        │
│                                                                  │
│  2. Checks if this email was already processed. Email            │
│     systems sometimes deliver the same message twice during      │
│     outages. This check prevents duplicate tickets.              │
│                                                                  │
│  3. Figures out which vendor sent it by matching the sender's    │
│     email address against the CRM database. If the email         │
│     address does not match, it looks for a vendor ID number      │
│     in the email body, then tries matching by company name.      │
│                                                                  │
│  4. Checks if this is a reply to an existing query (to avoid     │
│     creating a new ticket for a follow-up message).              │
│                                                                  │
│  5. Saves a permanent copy of the original email and any         │
│     attachments to the file store. This copy is never modified   │
│     — it is the legal record of what the vendor wrote.           │
│                                                                  │
│  6. Places the email into the same processing queue as portal    │
│     queries. From this point forward, the system treats          │
│     email queries and portal queries identically.                │
│                                                                  │
│  Why this step:  Most vendor queries come via email. Without     │
│  automatic pickup, someone would have to manually read every     │
│  email and enter it into the system. That takes 5-10 minutes     │
│  per email and introduces human error.                           │
│                                                                  │
│  What goes out:  The email becomes a query in the same queue     │
│  as portal submissions, ready for AI analysis.                   │
│                                                                  │
│  Time: 1-3 seconds per email                                     │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 4: AI LOADS CONTEXT ABOUT THE VENDOR                       │
│                                                                  │
│  What comes in:  A query from the processing queue.              │
│                                                                  │
│  What happens:   Before the AI reads the query, it loads         │
│  everything it knows about this vendor:                          │
│                                                                  │
│  - The vendor's importance tier (Platinum, Gold, Silver, or      │
│    Standard), which determines how fast we need to respond.      │
│                                                                  │
│  - Any risk flags (like "this vendor has overdue payments" or    │
│    "do not auto-respond to this vendor").                        │
│                                                                  │
│  - The vendor's last 10 queries, so the AI knows if this is     │
│    a recurring issue or a brand-new question.                    │
│                                                                  │
│  This context is cached so we do not look it up from scratch     │
│  every time the same vendor submits a query.                     │
│                                                                  │
│  Why this step:  Without context, the AI would treat every       │
│  query in isolation. If a vendor asked about the same invoice    │
│  three times this week, the AI should know that and escalate,    │
│  not send the same first-time response again.                    │
│                                                                  │
│  What goes out:  The query enriched with vendor history and      │
│  profile information, ready for analysis.                        │
│                                                                  │
│  Time: Under a second                                            │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 5: AI READS AND CLASSIFIES THE QUERY                       │
│                                                                  │
│  What comes in:  The query text plus vendor context.             │
│                                                                  │
│  What happens:   This is the first AI call. The AI reads the     │
│  query and produces a structured analysis:                       │
│                                                                  │
│  - What type of question is this? (billing, PO, contract,       │
│    general)                                                      │
│                                                                  │
│  - How urgent is it? (critical, high, medium, low)               │
│                                                                  │
│  - What specific details did it mention? (invoice numbers,       │
│    dates, dollar amounts, PO numbers)                            │
│                                                                  │
│  - What is the vendor's mood? (neutral, concerned, frustrated,   │
│    escalating)                                                   │
│                                                                  │
│  - How confident is the AI in this analysis? (0 to 100%)         │
│                                                                  │
│  If the AI is less than 85% confident, it stops and flags        │
│  the query for a human to review before doing anything else.     │
│  This is the safety net — the system never guesses when it       │
│  is unsure.                                                      │
│                                                                  │
│  The AI call takes about 3 seconds and costs about 1.2 cents.    │
│                                                                  │
│  Why this step:  Without classification, every query would       │
│  need a human to read it, figure out what it is about, and       │
│  decide where to send it. That takes 5-10 minutes per query.     │
│  The AI does it in 3 seconds.                                    │
│                                                                  │
│  What goes out:  A structured classification with intent,        │
│  urgency, entities, and a confidence score.                      │
│                                                                  │
│  Time: About 3 seconds                                           │
└──────────────────────────────────────────────────────────────────┘
                                 │
                       ┌─── Is the AI at least ───┐
                       │    85% confident?         │
                       │ YES                    NO │
                       ▼                           ▼
               [ Continue ]              [ Stop. A human reviewer ]
               [ to Step 6 ]             [ checks the AI's work  ]
                       │                 [ before anything else   ]
                       │                 [ happens. (Phase 5)     ]
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 6: SYSTEM ROUTES THE QUERY AND SEARCHES FOR ANSWERS        │
│                                                                  │
│  What comes in:  The AI's classification of the query.           │
│                                                                  │
│  What happens:   Two things happen at the same time:             │
│                                                                  │
│  First, the routing engine assigns the query to the right        │
│  team and sets a response deadline:                              │
│                                                                  │
│    - Billing questions go to Finance Team                        │
│    - Purchase order questions go to Procurement Team             │
│    - Contract questions go to Contract Team                      │
│    - Everything else goes to General Support                     │
│                                                                  │
│  The deadline depends on two things: how important the vendor    │
│  is and how urgent the query is. A critical query from a         │
│  Platinum vendor must be answered in 1 hour. A low-priority      │
│  query from a Standard vendor gets 48 hours.                     │
│                                                                  │
│  Second, the system searches the knowledge base for existing     │
│  answers. It converts the query into a mathematical              │
│  representation and compares it against every article in the     │
│  knowledge base to find the most similar ones. It also checks    │
│  whether the matching articles contain specific facts (dates,    │
│  amounts, steps) — not just general guidance.                    │
│                                                                  │
│  Then comes the key decision:                                    │
│                                                                  │
│  If the knowledge base has a strong match with real facts,       │
│  the AI will draft a full response. (Path A)                     │
│                                                                  │
│  If the knowledge base does not have a good enough answer,       │
│  the system sends the vendor an acknowledgment ("we received     │
│  your query, ticket number is..., our team is reviewing")        │
│  and a human team investigates. (Path B)                         │
│                                                                  │
│  Why this step:  Routing makes sure every query reaches the      │
│  right people with the right urgency. The knowledge base         │
│  search is what makes Path A possible — when the answer          │
│  already exists, why make a human type it out again?             │
│                                                                  │
│  What goes out:  A routing assignment (team + deadline) and      │
│  a decision: Path A (AI can answer) or Path B (humans must       │
│  investigate).                                                   │
│                                                                  │
│  Time: About 1 second                                            │
└──────────────────────────────────────────────────────────────────┘
                                 │
                       ┌── Does the knowledge ──┐
                       │   base have a good      │
                       │   enough answer?         │
                       │ YES                  NO  │
                       ▼                          ▼
              ┌───────────────┐          ┌───────────────┐
              │ Path A:       │          │ Path B:       │
              │ AI will draft │          │ System sends  │
              │ a full answer │          │ acknowledgment│
              │ from the      │          │ and a human   │
              │ knowledge base│          │ team takes    │
              │ (Phase 4)     │          │ over (Phase 4)│
              └───────────────┘          └───────────────┘
```

---

```
┌──────────────────────────────────────────────────────────────────┐
│  BEHIND THE SCENES: HOW EVERYTHING IS TRACKED                    │
│                                                                  │
│  What happens:   Every single action the system takes is         │
│  recorded. Every email fetch, every database write, every        │
│  AI call, every routing decision — all logged with a             │
│  correlation ID that ties them together.                         │
│                                                                  │
│  If a vendor calls and asks "what happened to my query?",        │
│  we can pull up the full history in seconds: when it was         │
│  received, what the AI classified it as, which team it was       │
│  routed to, what the response deadline is, and how much the      │
│  AI processing cost.                                             │
│                                                                  │
│  The AI calls also track their own costs. Each analysis costs    │
│  about 1.2 cents. When the system is handling thousands of       │
│  queries per month, these costs add up, and we can see           │
│  exactly where the money goes.                                   │
│                                                                  │
│  Why this matters:  Compliance requires a full audit trail.      │
│  If a vendor disputes our response, we can show exactly what     │
│  the AI saw, what it decided, and why. Every original email      │
│  is saved in its unmodified form as a legal record.              │
│                                                                  │
│  Time: Zero added time (logging happens alongside every step)    │
└──────────────────────────────────────────────────────────────────┘
```

---

```
┌──────────────────────────────────────────────────────────────────┐
│  BEHIND THE SCENES: THE AI CAN SWITCH BRAINS                    │
│                                                                  │
│  What happens:   The system is not locked into one AI            │
│  provider. Right now it uses Amazon's AI service as the          │
│  primary brain, with OpenAI as a backup. If Amazon's service     │
│  goes down, the system automatically switches to OpenAI          │
│  and keeps working. The vendor never knows.                      │
│                                                                  │
│  Both AI providers produce the same type of analysis. Both       │
│  can convert text into the mathematical representations          │
│  used for knowledge base search. Switching between them          │
│  requires changing one configuration value, not rewriting        │
│  code.                                                           │
│                                                                  │
│  Why this matters:  If we only had one AI provider and it        │
│  went down, every query would be stuck until it came back.       │
│  The fallback means the system keeps running even during         │
│  outages. It also lets us compare providers to see which         │
│  one gives better results for our specific use case.             │
└──────────────────────────────────────────────────────────────────┘
```

---

```
┌──────────────────────────────────────────────────────────────────┐
│  BEHIND THE SCENES: DATABASE ACCESS THROUGH A SECURE TUNNEL      │
│                                                                  │
│  What happens:   The database lives inside a private network     │
│  that is not directly reachable from the internet or from        │
│  developer machines. To connect, our system creates a secure     │
│  encrypted tunnel through a gateway server (called a bastion     │
│  host). The tunnel opens when the application starts and         │
│  stays open until it shuts down.                                 │
│                                                                  │
│  Why this matters:  Direct database access from the internet     │
│  is a security risk. The tunnel means the database is only       │
│  reachable through an authorized gateway, which is standard      │
│  security practice for enterprise systems.                       │
└──────────────────────────────────────────────────────────────────┘
```

---

# WHAT IS NOT BUILT YET

## Currently Working (Phases 1-3)

Both ways to submit a query (portal and email) work end to end. The AI reads
and classifies every query, figures out which team should handle it, searches
the knowledge base for existing answers, and decides whether the AI can answer
directly (Path A) or a human team needs to investigate (Path B). All of this
is logged, tracked, and auditable. The email dashboard shows incoming emails
with filtering and sorting. The portal has a working wizard for submitting
queries.

128 automated tests verify this works correctly.

## What Comes Next

**Phase 4 — AI Responses and Ticket Creation**
The AI will draft actual response emails (Path A: full answer from knowledge
base, Path B: acknowledgment with ticket number). Every draft goes through
seven safety checks before sending: correct ticket number format, accurate
deadline wording, required sections present, no restricted terms, reasonable
length, source citations included, and no personal data leaked. Tickets get
created automatically in ServiceNow. Emails get sent via the same system that
receives them.

**Phase 5 — Human Review for Uncertain Queries**
When the AI is not confident enough (Path C), the workflow pauses completely.
A human reviewer sees everything the AI figured out, corrects any mistakes,
and sends the query back through the pipeline with the corrected information.
The response deadline does not start until the reviewer finishes.

**Phase 6 — Deadline Monitoring and Closure**
The system will watch every open query and fire alerts at 70%, 85%, and 95% of
the response deadline. When a vendor confirms their issue is resolved, the
query closes automatically. If there is no confirmation after 5 business days,
it closes on its own. Reopened queries get linked to the original ticket.

**Phase 7 — Portal Polish and Real Authentication**
Replace the temporary login with real single sign-on. Add styling to the
portal. Build the human reviewer's interface. Add an admin dashboard with
metrics on response times, AI costs, and path distribution.

**Phase 8 — Production Readiness**
Connect all the real external systems (Salesforce, ServiceNow, email sending).
Run the full reference scenario end-to-end: a vendor submits a payment inquiry,
the AI finds the answer in the knowledge base, drafts a response, passes safety
checks, creates a ticket, and sends the email — all in about 11 seconds for
about 3.3 cents.

---

## Summary

```
┌──────────────────────────────────────────────────────────────────┐
│  WHERE WE ARE TODAY                                              │
│                                                                  │
│  Working now:                                                    │
│    - Vendors can submit queries via portal (6-screen wizard)     │
│    - Emails are picked up automatically from the shared inbox    │
│    - AI classifies every query in ~3 seconds                     │
│    - System routes to the right team with the right deadline     │
│    - Knowledge base is searched for existing answers             │
│    - Path A/B/C decision is made automatically                   │
│    - Everything is logged and traceable                          │
│    - AI provider can switch between Amazon and OpenAI            │
│    - 128 automated tests verify correctness                      │
│                                                                  │
│  Coming next (Phase 4):                                          │
│    - AI drafts actual response emails                            │
│    - Safety checks on every outgoing email                       │
│    - Automatic ticket creation in ServiceNow                     │
│    - Email delivery to vendors                                   │
│                                                                  │
│  Target end state:                                               │
│    - Vendor submits a common question                            │
│    - AI finds the answer, writes the response, checks it,       │
│      creates a ticket, and sends the email                       │
│    - Total time: ~11 seconds                                     │
│    - Total cost: ~3.3 cents                                      │
│    - Human involvement: zero (for common questions)              │
│    - Uncommon questions go to the right team automatically       │
│    - Uncertain queries get human review before proceeding        │
└──────────────────────────────────────────────────────────────────┘
```
