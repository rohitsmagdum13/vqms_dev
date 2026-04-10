# VQMS API Reference

**Base URL:** `http://localhost:8000`
**Auth:** Currently header-based (`X-Vendor-ID`). TODO: Cognito JWT in Phase 7.
**Content-Type:** `application/json`

## Quick Reference Table

| # | Method | URL | Purpose | Auth | Status |
|---|--------|-----|---------|------|--------|
| 1 | GET | `/health` | Health check | None | [IMPLEMENTED] |
| 2 | POST | `/queries` | Submit vendor query (portal entry point) | X-Vendor-ID header | [IMPLEMENTED] |
| 3 | GET | `/queries` | List queries for a vendor | X-Vendor-ID header | [IMPLEMENTED] |
| 4 | GET | `/queries/{query_id}` | Get single query details | X-Vendor-ID header | [IMPLEMENTED] |
| 5 | POST | `/webhooks/ms-graph` | Microsoft Graph email webhook | None (HMAC TODO) | [IMPLEMENTED] |
| 6 | POST | `/auth/login` | Fake vendor login (dev only) | None | [IMPLEMENTED] |
| 7 | GET | `/dashboard/kpis` | Portal dashboard KPI counts | X-Vendor-ID header | [IMPLEMENTED] |
| 8 | GET | `/emails` | List email chains (paginated) | None (TODO: JWT) | [IMPLEMENTED] |
| 9 | GET | `/emails/stats` | Email dashboard statistics | None (TODO: JWT) | [IMPLEMENTED] |
| 10 | GET | `/emails/{query_id}` | Get single email chain | None (TODO: JWT) | [IMPLEMENTED] |
| 11 | GET | `/emails/{query_id}/attachments/{attachment_id}/download` | Download attachment (presigned URL) | None (TODO: JWT) | [IMPLEMENTED] |

---

### API #1: Health Check

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/health` |
| File | `main.py` |
| Function | `health_check()` |
| Auth | None |
| Status | [IMPLEMENTED] |

**What it does:**
1. Checks whether PostgreSQL is reachable (via `check_db_health()`)
2. Returns app metadata and connectivity status

**Request:**
- No request body
- No query parameters
- No headers required

**Example call:**
```
curl http://localhost:8000/health
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "phase": 2,
  "app_name": "vqms",
  "app_env": "development",
  "version": "1.0.0",
  "database": "connected"
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| status | string | Always `"ok"` if the server is running |
| phase | integer | Current development phase (hardcoded to `2`) |
| app_name | string | From `APP_NAME` env var |
| app_env | string | From `APP_ENV` env var (`development`, `staging`, `production`) |
| version | string | From `APP_VERSION` env var |
| database | string | `"connected"` or `"disconnected"` |

**Error responses:**
- None. Always returns 200 if the server is up. Backend connectivity is reported in the response body.

---

### API #2: Submit Query (Portal Entry Point)

| Field | Detail |
|-------|--------|
| Method | POST |
| URL | `/queries` |
| File | `src/api/routes/queries.py` |
| Function | `create_query()` |
| Auth | `X-Vendor-ID` header (required) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Validates `X-Vendor-ID` header is present (returns 401 if missing)
2. Parses and validates request body via `QuerySubmission` Pydantic model
3. Calls `submit_portal_query()` which runs the 7-step portal intake pipeline:
   - Generates `query_id` (VQ-YYYY-NNNN format), `execution_id` (UUID), `correlation_id` (UUID)
   - Checks cache for duplicate submission (idempotency via `vqms:idempotency:{query_id}`)
   - Inserts into PostgreSQL `workflow.case_execution` with status `new`
   - Publishes `QueryReceived` event to EventBridge
   - Pushes `UnifiedQueryPayload` to SQS `vqms-query-intake-queue`
4. Returns the generated identifiers and status

**Request headers:**
| Header | Required | Description |
|--------|----------|-------------|
| Content-Type | Yes | `application/json` |
| X-Vendor-ID | Yes | Salesforce Account ID (e.g., `SF-001`). In Phase 7, this will come from Cognito JWT. |
| X-Vendor-Name | No | Vendor display name. Defaults to `"Portal Vendor"` if omitted. |
| X-Correlation-ID | No | Optional tracing ID. Auto-generated if omitted. |

**Request body:**
```json
{
  "query_type": "billing",
  "subject": "Invoice Payment Status",
  "description": "When will invoice #INV-2026-0451 be paid?",
  "priority": "high",
  "reference_number": "PO-XXX-12345"
}
```

**Request body fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| query_type | string | Yes | One of: `billing`, `shipping`, `returns`, `contract`, `technical`, `general` |
| subject | string | Yes | Short summary of the query |
| description | string | Yes | Full details of the vendor's question |
| priority | string | No | `low`, `medium`, `high`, or `critical`. Defaults to `medium`. |
| reference_number | string | No | PO number, invoice number, or other reference |

**Example call:**
```
curl -X POST http://localhost:8000/queries -H "Content-Type: application/json" -H "X-Vendor-ID: SF-001" -H "X-Vendor-Name: Acme Corporation" -d "{\"query_type\": \"billing\", \"subject\": \"Invoice Payment Status\", \"description\": \"When will invoice #INV-2026-0451 be paid?\", \"priority\": \"high\", \"reference_number\": \"PO-XXX-12345\"}"
```

**Response (201 Created):**
```json
{
  "query_id": "VQ-2026-0001",
  "execution_id": "550e8400-e29b-41d4-a716-446655440000",
  "correlation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "accepted"
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| query_id | string | Unique query identifier in `VQ-YYYY-NNNN` format |
| execution_id | string | UUID for this specific execution/workflow instance |
| correlation_id | string | UUID for tracing this query through the entire pipeline |
| status | string | Always `"accepted"` on success |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 401 | Missing `X-Vendor-ID` header | `{"detail": "Missing X-Vendor-ID header. Vendor identity is required."}` |
| 409 | Duplicate submission (idempotency) | `{"detail": "Duplicate query: <identifier>"}` |
| 422 | Pydantic validation fails (missing/invalid fields) | `{"detail": [validation errors]}` |

**Storage writes:**
- **PostgreSQL:** INSERT into `workflow.case_execution`
- **PostgreSQL cache:** SET `vqms:idempotency:{query_id}` with 7-day TTL
- **EventBridge:** `QueryReceived` event to `vqms-event-bus`
- **SQS:** `UnifiedQueryPayload` message to `vqms-query-intake-queue`

---

### API #3: List Queries

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/queries` |
| File | `src/api/routes/dashboard.py` |
| Function | `list_queries()` |
| Auth | `X-Vendor-ID` header (required) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Validates `X-Vendor-ID` header is present (returns 401 if missing)
2. If database is not connected, returns empty list with `total: 0` (graceful degradation)
3. Counts total queries for this vendor in `workflow.case_execution`
4. Fetches paginated results ordered by `created_at DESC`
5. Returns query list with pagination metadata

**Request headers:**
| Header | Required | Description |
|--------|----------|-------------|
| X-Vendor-ID | Yes | Salesforce Account ID |

**Query parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| limit | integer | 20 | Max results per page (1-100) |
| offset | integer | 0 | Number of results to skip |

**Example call:**
```
curl -H "X-Vendor-ID: SF-001" "http://localhost:8000/queries?limit=10&offset=0"
```

**Response (200 OK):**
```json
{
  "vendor_id": "SF-001",
  "queries": [
    {
      "query_id": "VQ-2026-0003",
      "correlation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "status": "new",
      "source": "portal",
      "created_at": "2026-04-08T10:30:00",
      "updated_at": "2026-04-08T10:30:00"
    }
  ],
  "total": 1
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| vendor_id | string | The vendor ID from the request header |
| queries | array | List of query objects |
| queries[].query_id | string | Query identifier |
| queries[].correlation_id | string | Correlation ID for tracing |
| queries[].status | string | Current status (e.g., `new`, `analyzing`, `resolved`, `closed`) |
| queries[].source | string | Entry point: `portal` or `email` |
| queries[].created_at | string | ISO 8601 datetime when the query was created |
| queries[].updated_at | string | ISO 8601 datetime of last update |
| total | integer | Total number of queries for this vendor (for pagination) |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 401 | Missing `X-Vendor-ID` header | `{"detail": "Missing X-Vendor-ID header."}` |

**Note:** Database failures return `{"vendor_id": "...", "queries": [], "total": 0}` (200 OK) rather than an error. This is intentional graceful degradation.

---

### API #4: Get Query Detail

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/queries/{query_id}` |
| File | `src/api/routes/dashboard.py` |
| Function | `get_query_detail()` |
| Auth | `X-Vendor-ID` header (required) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Validates `X-Vendor-ID` header is present (returns 401 if missing)
2. Returns 503 if database is not connected (no graceful degradation here)
3. Looks up the query in `workflow.case_execution` by `query_id`
4. Returns 404 if query not found
5. Verifies the query's `vendor_id` matches the requesting vendor (returns 403 if mismatch)
6. Returns full query details

**Request headers:**
| Header | Required | Description |
|--------|----------|-------------|
| X-Vendor-ID | Yes | Salesforce Account ID. Must match the query's stored vendor_id. |

**Path parameters:**
| Param | Type | Description |
|-------|------|-------------|
| query_id | string | The query identifier (e.g., `VQ-2026-0001`) |

**Example call:**
```
curl -H "X-Vendor-ID: SF-001" http://localhost:8000/queries/VQ-2026-0001
```

**Response (200 OK):**
```json
{
  "query_id": "VQ-2026-0001",
  "execution_id": "550e8400-e29b-41d4-a716-446655440000",
  "correlation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "new",
  "source": "portal",
  "vendor_id": "SF-001",
  "selected_path": null,
  "created_at": "2026-04-08T10:30:00",
  "updated_at": "2026-04-08T10:30:00",
  "completed_at": null
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| query_id | string | Query identifier |
| execution_id | string | UUID for this workflow instance |
| correlation_id | string | UUID for pipeline tracing |
| status | string | Current status |
| source | string | Entry point: `portal` or `email` |
| vendor_id | string | Salesforce Account ID of the owning vendor |
| selected_path | string or null | Processing path (`A`, `B`, `C`) once routing is complete. `null` before routing. |
| created_at | string | ISO 8601 datetime |
| updated_at | string | ISO 8601 datetime |
| completed_at | string or null | ISO 8601 datetime when resolved/closed. `null` if still open. |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 401 | Missing `X-Vendor-ID` header | `{"detail": "Missing X-Vendor-ID header."}` |
| 403 | Query belongs to a different vendor | `{"detail": "Query does not belong to this vendor."}` |
| 404 | Query ID not found in database | `{"detail": "Query VQ-2026-0001 not found."}` |
| 500 | Database query failure | `{"detail": "Failed to retrieve query details."}` |
| 503 | Database not connected | `{"detail": "Database not connected."}` |

---

### API #5: Microsoft Graph Email Webhook

| Field | Detail |
|-------|--------|
| Method | POST |
| URL | `/webhooks/ms-graph` |
| File | `src/api/routes/webhooks.py` |
| Function | `handle_graph_notification()` |
| Auth | None (TODO: HMAC/Token validation) |
| Status | [IMPLEMENTED] |

**What it does:**

This endpoint handles two scenarios:

**Scenario A — Subscription validation:**
1. When Microsoft Graph creates or renews a webhook subscription, it sends a `validationToken` as a query parameter
2. The endpoint echoes the token back as plain text with `200 OK`

**Scenario B — Change notification:**
1. Microsoft Graph sends a JSON payload with an array of changed resources (new emails)
2. For each notification, calls `process_email_notification()` which runs the full 11-step email intake pipeline:
   - Fetches the email from Graph API
   - Checks cache idempotency
   - Resolves vendor via Salesforce
   - Correlates email thread
   - Uploads attachments to S3
   - Stores raw email JSON in S3
   - Stores email record in PostgreSQL
   - Builds `UnifiedQueryPayload`
   - Publishes `EmailIngested` event to EventBridge
   - Enqueues payload to SQS
3. Returns results for each notification processed

**Query parameters (Scenario A only):**
| Param | Type | Description |
|-------|------|-------------|
| validationToken | string | Token sent by Graph for subscription validation |

**Request body (Scenario B):**
```json
{
  "value": [
    {
      "resource": "users/vendorsupport@company.com/messages/AAMkAD...",
      "changeType": "created",
      "clientState": "optional-state",
      "subscriptionId": "sub-id-uuid",
      "tenantId": "tenant-uuid"
    }
  ]
}
```

**Request body fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| value | array | Yes | Array of notification objects |
| value[].resource | string | Yes | Graph API resource path for the email |
| value[].changeType | string | No | Type of change (usually `created`) |
| value[].clientState | string | No | Client state for validation |
| value[].subscriptionId | string | No | Graph subscription ID |
| value[].tenantId | string | No | Azure AD tenant ID |

**Example call (subscription validation):**
```
curl -X POST "http://localhost:8000/webhooks/ms-graph?validationToken=abc123"
```

**Response (200 OK — plain text):**
```
abc123
```

**Example call (change notification):**
```
curl -X POST http://localhost:8000/webhooks/ms-graph -H "Content-Type: application/json" -d "{\"value\": [{\"resource\": \"users/vendorsupport@company.com/messages/AAMkAD123\", \"changeType\": \"created\"}]}"
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "processed": 1,
  "results": [
    {
      "query_id": "VQ-2026-0001",
      "execution_id": "550e8400-e29b-41d4-a716-446655440000",
      "correlation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
      "status": "accepted"
    }
  ]
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| status | string | `"accepted"` |
| processed | integer | Number of notifications processed in this batch |
| results | array | Per-notification results |
| results[].query_id | string | Generated query ID (if successful) |
| results[].status | string | `"accepted"` or `"duplicate"` |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 400 | No `value` array and no `validationToken` | `{"detail": "Invalid notification: no value array provided."}` |

**Note:** Duplicate emails within a batch are not treated as errors. They are logged and returned with `"status": "duplicate"` in the results array.

**Storage writes (per notification):**
- **S3:** Raw email JSON to `vqms-email-raw-prod`, attachments to `vqms-email-attachments-prod`
- **PostgreSQL:** INSERT into `intake.email_messages`
- **PostgreSQL:** INSERT into `workflow.case_execution`
- **PostgreSQL cache:** SET `vqms:idempotency:{message_id}` with 7-day TTL
- **EventBridge:** `EmailIngested` event to `vqms-event-bus`
- **SQS:** `UnifiedQueryPayload` message to `vqms-email-intake-queue`

---

### API #6: Fake Login (Dev Only)

| Field | Detail |
|-------|--------|
| Method | POST |
| URL | `/auth/login` |
| File | `src/api/routes/auth.py` |
| Function | `fake_login()` |
| Auth | None |
| Status | [IMPLEMENTED] — Dev stub. Will be replaced by Cognito JWT in Phase 7. |

**What it does:**
1. Accepts any email and password (password is ignored)
2. Generates a deterministic `vendor_id` from the email domain using `hash(domain) % 100000`
3. Returns a fake JWT token and vendor identity

This endpoint exists solely to allow the Angular frontend to simulate the login flow (Step P1) without real Cognito infrastructure.

**Request body:**
```json
{
  "email": "john@acme.com",
  "password": "anything"
}
```

**Request body fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| email | string | Yes | Vendor email address |
| password | string | Yes | Ignored in dev mode (any value accepted) |

**Example call:**
```
curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"email\": \"john@acme.com\", \"password\": \"anything\"}"
```

**Response (200 OK):**
```json
{
  "token": "fake-jwt-dev-VN-12345",
  "vendor_id": "VN-12345",
  "email": "john@acme.com",
  "vendor_name": "Acme",
  "role": "VENDOR"
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| token | string | Fake JWT token in format `fake-jwt-dev-{vendor_id}` |
| vendor_id | string | Deterministic vendor ID derived from email domain (format: `VN-NNNNN`) |
| email | string | The email that was submitted |
| vendor_name | string | Derived from email domain (e.g., `acme.com` becomes `Acme`) |
| role | string | Always `"VENDOR"` in dev mode |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 422 | Missing email or password field | `{"detail": [validation errors]}` |

**Note:** The same email always produces the same `vendor_id`, so `john@acme.com` and `jane@acme.com` get the same vendor ID (both share the `acme.com` domain).

---

### API #7: Dashboard KPIs

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/dashboard/kpis` |
| File | `src/api/routes/dashboard.py` |
| Function | `get_dashboard_kpis()` |
| Auth | `X-Vendor-ID` header (required) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Validates `X-Vendor-ID` header is present (returns 401 if missing)
2. If database is not connected, returns all-zero KPIs (graceful degradation)
3. Counts open queries (statuses: `new`, `analyzing`, `routing`, `drafting`, `validating`, `sending`, `awaiting_human_review`, `awaiting_team_resolution`)
4. Counts resolved/closed queries (statuses: `resolved`, `closed`)
5. Returns KPI counts (average resolution hours is stubbed at `0` for now)

**Request headers:**
| Header | Required | Description |
|--------|----------|-------------|
| X-Vendor-ID | Yes | Salesforce Account ID |

**Example call:**
```
curl -H "X-Vendor-ID: SF-001" http://localhost:8000/dashboard/kpis
```

**Response (200 OK):**
```json
{
  "vendor_id": "SF-001",
  "open_queries": 3,
  "resolved_queries": 12,
  "avg_resolution_hours": 0
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| vendor_id | string | The vendor ID from the request header |
| open_queries | integer | Count of queries in active/open statuses |
| resolved_queries | integer | Count of queries in `resolved` or `closed` status |
| avg_resolution_hours | integer | Average resolution time in hours. Currently stubbed at `0`. TODO: calculate from `completed_at - created_at`. |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 401 | Missing `X-Vendor-ID` header | `{"detail": "Missing X-Vendor-ID header."}` |

**Note:** Database failures return all-zero KPIs with 200 OK rather than an error. This is intentional graceful degradation so the frontend dashboard can still render.

---

### API #8: List Email Chains

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/emails` |
| File | `src/api/routes/email_dashboard.py` |
| Function | `list_email_chains()` |
| Auth | None (TODO: Cognito JWT in Phase 7) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Validates filter/sort query parameters (returns 422 if invalid)
2. Queries `intake.email_messages` joined with `workflow.case_execution`
3. Groups emails by `query_id` (each query_id = one chain)
4. Fetches attachments from `intake.email_attachments` for each email
5. Maps workflow `status` to dashboard display status ("New", "Reopened", "Resolved")
6. Maps routing priority to display priority ("High", "Medium", "Low")
7. Returns paginated results with mail items sorted newest first within each chain

**Query parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | integer | 1 | Page number (1-based, min 1) |
| page_size | integer | 20 | Items per page (1-100) |
| status | string | null | Filter: "New", "Reopened", "Resolved" |
| priority | string | null | Filter: "High", "Medium", "Low" |
| search | string | null | Search in subject and body text (ILIKE) |
| sort_by | string | "timestamp" | Sort field: "timestamp", "status", "priority" |
| sort_order | string | "desc" | Sort direction: "asc" or "desc" |

**Example call:**
```
curl "http://localhost:8000/emails?page=1&page_size=5&status=New&search=invoice"
```

**Response (200 OK):**
```json
{
  "total": 42,
  "page": 1,
  "page_size": 5,
  "mail_chains": [
    {
      "mail_items": [
        {
          "from": { "name": "Rajesh Mehta", "email": "rajesh@technova.com" },
          "to": [{ "name": "vendor-support@company.com", "email": "vendor-support@company.com" }],
          "cc": [],
          "subject": "Payment Status Inquiry - Invoice #INV-2026-0451",
          "body": "We are writing regarding the payment status of invoice #INV-2026-0451...",
          "timestamp": "2026-04-08T10:30:00+00:00",
          "attachments": [
            {
              "name": "invoice_copy.pdf",
              "size": 245760,
              "file_format": "PDF",
              "url": "s3://vqms-email-attachments-prod/attachments/msg-id/invoice_copy.pdf"
            }
          ]
        }
      ],
      "status": "New",
      "priority": "High"
    }
  ]
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| total | integer | Total chains matching filters (for pagination) |
| page | integer | Current page number |
| page_size | integer | Items per page |
| mail_chains | array | Array of MailChain objects |
| mail_chains[].mail_items | array | Emails in thread, newest first |
| mail_chains[].mail_items[].from | object | Sender: `{name, email}` |
| mail_chains[].mail_items[].to | array | To recipients: `[{name, email}]` |
| mail_chains[].mail_items[].cc | array | CC recipients: `[{name, email}]` |
| mail_chains[].mail_items[].subject | string | Email subject |
| mail_chains[].mail_items[].body | string | Plain text body |
| mail_chains[].mail_items[].timestamp | string | ISO 8601 with timezone |
| mail_chains[].mail_items[].attachments | array | Attachment metadata |
| mail_chains[].status | string | "New", "Reopened", or "Resolved" |
| mail_chains[].priority | string | "High", "Medium", or "Low" |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 422 | Invalid status, priority, sort_by, or sort_order | `{"detail": "Invalid status filter. Must be one of: ..."}` |

**Note:** Returns empty `mail_chains: []` if database is unavailable (graceful degradation).

---

### API #9: Email Stats

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/emails/stats` |
| File | `src/api/routes/email_dashboard.py` |
| Function | `get_email_stats()` |
| Auth | None (TODO: Cognito JWT in Phase 7) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Counts total email-sourced queries in `workflow.case_execution`
2. Counts by mapped status category (New, Reopened, Resolved)
3. Counts by priority from `routing_decision` JSONB (defaults to Medium if unrouted)
4. Counts emails received today and in the last 7 days

**Example call:**
```
curl http://localhost:8000/emails/stats
```

**Response (200 OK):**
```json
{
  "total_emails": 156,
  "new_count": 23,
  "reopened_count": 5,
  "resolved_count": 128,
  "priority_breakdown": {
    "High": 15,
    "Medium": 45,
    "Low": 96
  },
  "today_count": 7,
  "this_week_count": 34
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| total_emails | integer | Total email-sourced queries |
| new_count | integer | Queries in active/open statuses |
| reopened_count | integer | Queries with status "reopened" |
| resolved_count | integer | Queries with status "resolved" or "closed" |
| priority_breakdown | object | Count per priority: `{"High": N, "Medium": N, "Low": N}` |
| today_count | integer | Queries created today (UTC) |
| this_week_count | integer | Queries created in the last 7 days |

**Error responses:**
- None. Returns all-zero stats if database is unavailable.

---

### API #10: Get Email Chain

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/emails/{query_id}` |
| File | `src/api/routes/email_dashboard.py` |
| Function | `get_email_chain()` |
| Auth | None (TODO: Cognito JWT in Phase 7) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Looks up `workflow.case_execution` for status and priority
2. Fetches all emails in `intake.email_messages` with matching `query_id`
3. Fetches attachments from `intake.email_attachments` for each email
4. Builds MailChainResponse with all emails sorted newest first
5. Returns 404 if query_id not found

**Path parameters:**
| Param | Type | Description |
|-------|------|-------------|
| query_id | string | VQMS query ID (e.g., `VQ-2026-0001`) |

**Example call:**
```
curl http://localhost:8000/emails/VQ-2026-0001
```

**Response (200 OK):**
```json
{
  "mail_items": [
    {
      "from": { "name": "Rajesh Mehta", "email": "rajesh@technova.com" },
      "to": [{ "name": "vendor-support@company.com", "email": "vendor-support@company.com" }],
      "cc": [],
      "subject": "Re: Payment Status Inquiry - Invoice #INV-2026-0451",
      "body": "Thank you for the update...",
      "timestamp": "2026-04-08T14:30:00+00:00",
      "attachments": []
    },
    {
      "from": { "name": "Rajesh Mehta", "email": "rajesh@technova.com" },
      "to": [{ "name": "vendor-support@company.com", "email": "vendor-support@company.com" }],
      "cc": [],
      "subject": "Payment Status Inquiry - Invoice #INV-2026-0451",
      "body": "We are writing regarding...",
      "timestamp": "2026-04-08T10:30:00+00:00",
      "attachments": [
        {
          "name": "invoice_copy.pdf",
          "size": 245760,
          "file_format": "PDF",
          "url": "s3://vqms-email-attachments-prod/attachments/msg-id/invoice_copy.pdf"
        }
      ]
    }
  ],
  "status": "New",
  "priority": "High"
}
```

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 404 | Query ID not found | `{"detail": "Email chain not found for query_id: VQ-2026-0001"}` |

---

### API #11: Download Attachment

| Field | Detail |
|-------|--------|
| Method | GET |
| URL | `/emails/{query_id}/attachments/{attachment_id}/download` |
| File | `src/api/routes/email_dashboard.py` |
| Function | `download_attachment()` |
| Auth | None (TODO: Cognito JWT in Phase 7) |
| Status | [IMPLEMENTED] |

**What it does:**
1. Verifies the attachment exists in `intake.email_attachments`
2. Verifies the attachment belongs to an email in the specified query chain
3. Generates a presigned S3 URL for the attachment file (1-hour expiry)
4. Returns the presigned URL (the frontend can redirect or open it in a new tab)

**Path parameters:**
| Param | Type | Description |
|-------|------|-------------|
| query_id | string | VQMS query ID (e.g., `VQ-2026-0001`) |
| attachment_id | integer | Database ID of the attachment |

**Example call:**
```
curl http://localhost:8000/emails/VQ-2026-0001/attachments/1/download
```

**Response (200 OK):**
```json
{
  "download_url": "https://vqms-email-attachments-prod.s3.amazonaws.com/attachments/msg-id/invoice_copy.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&..."
}
```

**Response fields:**
| Field | Type | Description |
|-------|------|-------------|
| download_url | string | Presigned S3 URL, valid for 1 hour |

**Error responses:**
| Status | When | Response |
|--------|------|----------|
| 404 | Attachment not found or doesn't belong to query | `{"detail": "Attachment 1 not found for query VQ-2026-0001"}` |

---

## Planned APIs (Not Built Yet)

These endpoints are defined in the architecture doc and CLAUDE.md but have no code yet:

| Method | URL | Purpose | Planned Phase |
|--------|-----|---------|---------------|
| GET | `/triage/queue` | List pending triage packages for human review portal (Path C) | Phase 5 |
| POST | `/triage/{id}/review` | Human reviewer submits corrections for low-confidence queries (Path C) | Phase 5 |
| POST | `/webhooks/servicenow` | ServiceNow resolution-prepared callback (Step 15, Path B) | Phase 6 |
| GET | `/admin/metrics` | SLA, path distribution, and cost reporting metrics | Phase 7 |
