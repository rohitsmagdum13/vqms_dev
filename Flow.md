```
================================================================================
     VQMS -- END-TO-END RUNTIME WALKTHROUGH
     Phase 3 Complete | Auth + Vendor CRUD Merged | LangGraph + Bedrock + pgvector
================================================================================
```

This document traces exactly how a vendor query moves through the codebase,
function by function. Every step shows the real file, function, input, output,
and storage writes. Steps that have working code say [IMPLEMENTED]. Steps that
exist only as empty `__init__.py` files or are not yet coded say [STUB] or
[NOT BUILT].

---

## TABLE OF CONTENTS

```
  PART 0:  Application Startup .......................... [IMPLEMENTED]
  PART 0B: Authentication Flow (Login/Logout/JWT) ...... [IMPLEMENTED]
  PART 0C: Vendor CRUD (GET/PUT via Salesforce) ........ [IMPLEMENTED]
  PART 1:  Email Entry Point (Steps E1 - E2) ........... [IMPLEMENTED]
  PART 2:  Portal Entry Point (Steps P1 - P6) .......... [IMPLEMENTED]
  PART 3:  SQS Consumer + Context Loading (Step 7) ..... [IMPLEMENTED]
  PART 4:  Query Analysis -- LLM Call #1 (Step 8) ...... [IMPLEMENTED]
  PART 5:  Routing + KB Search (Step 9) ................ [IMPLEMENTED]
  PART 5B: Path Decision + Stubs (A/B/C) ............... [IMPLEMENTED — stubs for Phase 4]
  PART 6:  Path A -- AI-Resolved (Steps 10A-12A) ....... [NOT BUILT -- Phase 4]
  PART 7:  Path B -- Human-Team-Resolved ............... [NOT BUILT -- Phase 4]
  PART 8:  Path C -- Low-Confidence Review ............. [NOT BUILT -- Phase 5]
  PART 9:  SLA Monitoring (Step 13) .................... [NOT BUILT -- Phase 6]
  PART 10: Closure and Reopen (Step 16) ................ [NOT BUILT -- Phase 6]
  ---      What Is Built
  ---      What Is Stubbed
  ---      What Is Not Built Yet
```

---

## PART 0: APPLICATION STARTUP

```
  File: main.py -> lifespan()
  Status: [IMPLEMENTED]

  +=====================================================================+
  |                        STARTUP SEQUENCE                              |
  +=====================================================================+
  |                                                                      |
  |  Step 1: Configure Logging                                           |
  +---------------------------------------------------------------------+
  | src/utils/logger.py -> setup_logging()                               |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | What happens:                                                        |
  |   1. Configures structlog with shared processors                     |
  |      (contextvars, log level, logger name, ISO timestamps)           |
  |   2. Console handler: human-readable in DEBUG, JSON otherwise        |
  |   3. File handler: always JSON, writes to data/logs/vqms_YYYY-MM-DD |
  |      RotatingFileHandler: 10 MB max, keeps 5 backups                 |
  |   4. Silences noisy loggers (uvicorn.access, httpx, httpcore)        |
  |                                                                      |
  | Storage writes:                                                      |
  |   File: data/logs/vqms_YYYY-MM-DD.log                               |
  +---------------------------------------------------------------------+
  |                           |                                          |
  |                           v                                          |
  |  Step 2: SSH Tunnel (if SSH_HOST is set in .env)                     |
  +---------------------------------------------------------------------+
  | src/db/connection.py -> start_ssh_tunnel()                           |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | Input:                                                               |
  |   SSH_HOST, SSH_PORT, SSH_USERNAME, SSH_PRIVATE_KEY_PATH             |
  |   RDS_HOST, RDS_PORT                                                 |
  |                                                                      |
  | What happens:                                                        |
  |   1. Creates SSHTunnelForwarder (sshtunnel library)                  |
  |   2. local machine ---SSH---> bastion host ---TCP---> RDS            |
  |   3. Opens a random local port that forwards to RDS:5432             |
  |   4. Starts the tunnel daemon thread                                 |
  |                                                                      |
  | Output: (local_host, local_port) tuple                               |
  | Note: Requires paramiko<4.0.0 (paramiko 4.0.0 removed DSSKey)       |
  +---------------------------------------------------------------------+
  |                           |                                          |
  |                           v                                          |
  |  Step 3: PostgreSQL Connection                                       |
  +---------------------------------------------------------------------+
  | src/db/connection.py -> init_db()                                    |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | Input: database_url, pool_min=5, pool_max=20                         |
  | What happens:                                                        |
  |   1. Creates async SQLAlchemy engine (asyncpg driver)                |
  |   2. Runs SELECT 1 to verify connection                              |
  |   3. Stores engine in module-level _engine singleton                 |
  | Output: AsyncEngine stored globally                                  |
  +---------------------------------------------------------------------+
  |                           |                                          |
  |                           v                                          |
  |  Step 4: Redis Connection                                            |
  +---------------------------------------------------------------------+
  | src/cache/redis_client.py -> init_redis()                            |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | Input: host, port, password, db, ssl                                 |
  | What happens:                                                        |
  |   1. Creates async Redis client (redis.asyncio)                      |
  |   2. Runs PING to verify connection                                  |
  | Output: Redis client stored in module-level _redis_client            |
  +---------------------------------------------------------------------+
  |                                                                      |
  |  NOTE: Each step is try/except. If any fails, app still starts.      |
  |        Health check at GET /health reports which services connected.  |
  +=====================================================================+

  +=====================================================================+
  |                       SHUTDOWN SEQUENCE                              |
  +=====================================================================+
  |  1. close_db()        -- disposes SQLAlchemy engine                  |
  |  2. stop_ssh_tunnel() -- closes SSH tunnel forwarder                 |
  |  3. close_redis()     -- closes Redis connection                    |
  +=====================================================================+

  +=====================================================================+
  |                       MIDDLEWARE REGISTERED                           |
  +=====================================================================+
  |  AuthMiddleware              src/api/middleware/auth_middleware.py    |
  |    - Skips: /health, /auth/login, /docs, /openapi.json, /redoc,    |
  |      /webhooks/*                                                    |
  |    - Validates Bearer JWT on all other routes                        |
  |    - Sets request.state: username, role, tenant, is_authenticated   |
  |    - Adds X-New-Token header if token near expiry                   |
  +=====================================================================+

  +=====================================================================+
  |                       ROUTES REGISTERED                              |
  +=====================================================================+
  |  POST /auth/login            src/api/routes/auth.py                 |
  |  POST /auth/logout           src/api/routes/auth.py                 |
  |  GET  /vendors               src/api/routes/vendors.py              |
  |  PUT  /vendors/{vendor_id}   src/api/routes/vendors.py              |
  |  POST /queries               src/api/routes/queries.py              |
  |  POST /webhooks/ms-graph     src/api/routes/webhooks.py             |
  |  GET  /health                main.py -> health_check()              |
  +=====================================================================+
```

---

## PART 0B: AUTHENTICATION FLOW (Login / Logout / JWT)

User authentication merged from local_vqm backend. JWT-based auth with
Redis token blacklist. Middleware validates tokens on all protected routes.

```
  +=====================================================================+
  |                     LOGIN FLOW                                       |
  +=====================================================================+
  |                                                                      |
  |  Client sends POST /auth/login                                       |
  +---------------------------------------------------------------------+
  | src/api/routes/auth.py -> login()                                    |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | Input: LoginRequest { username_or_email, password }                  |
  | What happens:                                                        |
  |   1. Calls src/services/auth.py -> authenticate_user()               |
  |   2. authenticate_user():                                            |
  |      a. Gets engine via get_engine()                                 |
  |      b. Queries public.tbl_users by username OR email                |
  |      c. Checks account status == "ACTIVE"                            |
  |      d. Verifies password via werkzeug.check_password_hash           |
  |         (wrapped in asyncio.to_thread — CPU-bound)                   |
  |      e. Queries public.tbl_user_roles for role + tenant              |
  |      f. Calls create_access_token(user_name, role, tenant)           |
  |         - JWT claims: sub, role, tenant, exp, iat, jti (UUID)        |
  |         - Signed with settings.jwt_secret_key (HS256)                |
  |         - TTL: settings.session_timeout_seconds (default 30 min)     |
  |   3. Returns LoginResponse { token, user_name, email, role, tenant } |
  |                                                                      |
  | On failure: Returns 401 { "detail": "..." }                          |
  |   - "Invalid credentials" (wrong user/password)                      |
  |   - "Account is inactive" (status != ACTIVE)                         |
  |   - "No role assigned to this user"                                  |
  |   - "Database not available"                                         |
  +=====================================================================+

  +=====================================================================+
  |                     REQUEST AUTHENTICATION (Middleware)               |
  +=====================================================================+
  |                                                                      |
  |  Every request (except skip paths) passes through:                   |
  +---------------------------------------------------------------------+
  | src/api/middleware/auth_middleware.py -> AuthMiddleware.dispatch()     |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | Skip paths (no auth needed):                                         |
  |   /health, /auth/login, /docs, /openapi.json, /redoc, /webhooks/*   |
  |                                                                      |
  | What happens:                                                        |
  |   1. Extract Bearer token from Authorization header                  |
  |   2. Call src/services/auth.py -> validate_token(token)              |
  |      a. Decode JWT with jose.jwt.decode()                            |
  |      b. Check all 6 required claims present (sub, role, tenant,      |
  |         exp, iat, jti)                                               |
  |      c. Check Redis blacklist: auth_blacklist_key(jti) -> exists?    |
  |         If Redis is down, allow token through (graceful degradation) |
  |   3. If valid: set request.state.username, .role, .tenant,           |
  |      .is_authenticated = True → continue to route handler            |
  |   4. If invalid/missing: return 401 JSON immediately                 |
  |   5. After route handler: check refresh_token_if_expiring()          |
  |      If token has < 300s remaining, create new token + blacklist old |
  |      Add X-New-Token response header with fresh token                |
  +=====================================================================+

  +=====================================================================+
  |                     LOGOUT FLOW                                      |
  +=====================================================================+
  |                                                                      |
  |  Client sends POST /auth/logout with Authorization: Bearer <token>   |
  +---------------------------------------------------------------------+
  | src/api/routes/auth.py -> logout()                                   |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | What happens:                                                        |
  |   1. Extract Bearer token from header                                |
  |   2. Call src/services/auth.py -> blacklist_token(token)             |
  |      a. Decode JWT (verify_exp=False — allows blacklisting expired)  |
  |      b. Extract JTI from claims                                      |
  |      c. Store in Redis: vqms:auth:blacklist:<jti> = "blacklisted"    |
  |         TTL = 1800s (matches JWT lifetime)                           |
  |   3. Return { "message": "Logged out successfully" }                 |
  |                                                                      |
  | Storage writes:                                                      |
  |   Redis: vqms:auth:blacklist:<jti> (30-min TTL, auto-cleanup)        |
  +=====================================================================+
```

---

## PART 0C: VENDOR CRUD (GET / PUT via Salesforce Standard Account)

Vendor management endpoints merged from local_vqm. These query the STANDARD
Salesforce Account object (not the custom Vendor_Account__c used by the AI
pipeline). Both coexist in the Salesforce adapter.

```
  +=====================================================================+
  |                     GET /vendors — List Active Vendors                |
  +=====================================================================+
  |                                                                      |
  | src/api/routes/vendors.py -> list_vendors()                          |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | Auth: Requires valid JWT (any role)                                  |
  |                                                                      |
  | What happens:                                                        |
  |   1. Calls SalesforceAdapter.get_all_active_vendors()                |
  |   2. SOQL: SELECT Id, Name, Vendor_ID__c, Website, ... FROM Account |
  |      WHERE Vendor_Status__c = 'Active'                               |
  |   3. Returns list[VendorAccountData]                                 |
  |                                                                      |
  | Note: Queries STANDARD Account, not custom Vendor_Account__c.        |
  +=====================================================================+

  +=====================================================================+
  |                     PUT /vendors/{vendor_id} — Update Vendor          |
  +=====================================================================+
  |                                                                      |
  | src/api/routes/vendors.py -> update_vendor()                         |
  | Status: [IMPLEMENTED]                                                |
  |                                                                      |
  | Auth: Requires valid JWT (any role)                                  |
  | Input: VendorUpdateRequest (at least one field required)             |
  |                                                                      |
  | What happens:                                                        |
  |   1. Validate VendorUpdateRequest (model_validator ensures >= 1 field)|
  |   2. Call to_salesforce_fields() — snake_case → SF API names         |
  |      e.g. billing_city → BillingCity, vendor_tier → Vendor_Tier__c   |
  |   3. Call SalesforceAdapter.update_vendor_account()                  |
  |      a. Finds Account by Vendor_ID__c = vendor_id                   |
  |      b. Calls sf.Account.update(sf_id, fields)                      |
  |   4. Returns VendorUpdateResult { success, vendor_id,                |
  |      updated_fields, message }                                       |
  +=====================================================================+
```

---

## PART 1: EMAIL ENTRY POINT (Steps E1 - E2)

A vendor sends an email to the shared mailbox. Microsoft Graph detects the
new email and sends a webhook notification to our FastAPI endpoint.

```
═══════════════════════════════════════════════════════════════
 STEP E1: Webhook Receives Notification
═══════════════════════════════════════════════════════════════

        +=============================================+
        | handle_graph_notification()                 |
        | File: src/api/routes/webhooks.py            |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input:                                      |
        |   GraphNotificationPayload (Pydantic model) |
        |     .value: list of GraphNotificationValue  |
        |       .resource: str (e.g. "messages/AAMk") |
        |       .changeType: str ("created")          |
        |                                             |
        | OR: ?validationToken=<token> (query param)  |
        |                                             |
        | What happens inside:                        |
        |  1. If validationToken present:             |
        |     -> Echo token as plain text (HTTP 200)  |
        |     -> This is Graph subscription handshake |
        |  2. If payload.value has notifications:     |
        |     -> For each notification, call          |
        |        process_email_notification(resource)  |
        |     -> Catch DuplicateQueryError per item   |
        |        and mark it as "duplicate"           |
        |                                             |
        | Output:                                     |
        |   HTTP 200 + plain text (validation)        |
        |   HTTP 202 + JSON (notification accepted)   |
        |   HTTP 400 (empty payload)                  |
        |                                             |
        | Response body (notification):               |
        |   { "status": "accepted",                   |
        |     "processed": 1,                         |
        |     "results": [ {                          |
        |       "query_id": "VQ-2026-XXXX",           |
        |       "execution_id": "<uuid>",             |
        |       "correlation_id": "<uuid>",           |
        |       "vendor_id": "SF-XXX" or "UNRESOLVED",|
        |       "thread_status": "NEW",               |
        |       "status": "accepted"                  |
        |     } ] }                                   |
        +=============================================+
               |
               | calls process_email_notification()
               v

═══════════════════════════════════════════════════════════════
 STEP E2.1: Fetch Email from Exchange Online
═══════════════════════════════════════════════════════════════

        +=============================================+
        | process_email_notification(resource)         |
        | File: src/services/email_intake.py          |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Sub-call: fetch_email_by_resource(resource)  |
        | File: src/adapters/graph_api.py             |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input:                                      |
        |   resource: str (Graph API resource path)   |
        |                                             |
        | What happens inside:                        |
        |  1. _get_access_token() via MSAL            |
        |     client_credentials OAuth2 flow           |
        |     (cached for ~55 minutes)                |
        |  2. GET {GRAPH_BASE_URL}/{resource}         |
        |     with Bearer token                       |
        |  3. Parse response JSON into EmailMessage:  |
        |     - sender (from.emailAddress)            |
        |     - to_addresses (toRecipients[])         |
        |     - cc_addresses (ccRecipients[])         |
        |     - subject, body (text or stripped HTML) |
        |     - body_preview (bodyPreview, max 200ch) |
        |     - received_at (receivedDateTime)        |
        |     - conversation_id (thread correlation)  |
        |     - in_reply_to, references (headers)     |
        |     - is_auto_reply (header + subject check)|
        |  4. If hasAttachments == true:              |
        |     -> GET {resource}/attachments           |
        |     -> Decode base64 contentBytes           |
        |     -> Store in EmailAttachment.content_bytes|
        |                                             |
        | Output: EmailMessage (Pydantic model)       |
        |   Fields: message_id, conversation_id,      |
        |   in_reply_to, references, sender_email,    |
        |   sender_name, to_addresses, cc_addresses,  |
        |   subject, body_text, body_html,            |
        |   body_preview, received_at, attachments,   |
        |   is_auto_reply, language                   |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP E2.2: Idempotency Check
═══════════════════════════════════════════════════════════════

        +=============================================+
        | _check_email_idempotency(message_id)        |
        | File: src/services/email_intake.py          |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input:                                      |
        |   message_id: str (RFC 2822 Message-ID)     |
        |                                             |
        | What happens inside:                        |
        |  1. Build key via idempotency_key()         |
        |     Key: vqms:idempotency:email:<message_id>|
        |     TTL: 604800 seconds (7 days)            |
        |  2. Redis GET on the key                    |
        |  3. If EXISTS -> raise DuplicateQueryError   |
        |  4. If NOT EXISTS -> Redis SET with TTL      |
        |  5. If Redis down -> log warning, continue   |
        |     (graceful degradation)                  |
        |                                             |
        | Storage writes:                             |
        |   Redis key: vqms:idempotency:email:<msg_id>|
        |   Value: "1"                                |
        |   TTL: 604800 seconds (7 days)              |
        |                                             |
        | Output: None (raises DuplicateQueryError    |
        |         if duplicate, else continues)       |
        +=============================================+
               |
               | if not duplicate, continue
               v

═══════════════════════════════════════════════════════════════
 STEP E2.3: Vendor Resolution (Salesforce — REAL)
═══════════════════════════════════════════════════════════════

        +=============================================+
        | resolve_vendor(sender_email, sender_name,   |
        |                body_text)                   |
        | File: src/services/vendor_resolution.py     |
        | Adapter: src/adapters/salesforce.py         |
        | Status: [IMPLEMENTED — real Salesforce]     |
        +=============================================+
        |                                             |
        | Input:                                      |
        |   sender_email: str                         |
        |   sender_name: str                          |
        |   body_text: str                            |
        |                                             |
        | Connection:                                 |
        |   simple-salesforce library                 |
        |   Auth: username + password + security_token|
        |   Login URL from SALESFORCE_LOGIN_URL env   |
        |   Lazy connect on first query               |
        |                                             |
        | NOTE: This org uses CUSTOM Salesforce objects |
        |   Vendor_Account__c (not standard Account)  |
        |   Vendor_Contact__c (not standard Contact)  |
        |   Vendor IDs: "V-001", "V-002" etc.         |
        |                                             |
        | What happens inside (3-step fallback):      |
        |                                             |
        |  Step 1: _match_by_email(sender_email)      |
        |     SOQL: SELECT Id, Vendor_Account__c,     |
        |           Email__c, Name                    |
        |           FROM Vendor_Contact__c            |
        |           WHERE Email__c = '<sender_email>' |
        |           LIMIT 1                           |
        |     If found, lookup parent Vendor Account: |
        |     SOQL: SELECT Id, Name, Vendor_ID__c,    |
        |           Vendor_Tier__c, Vendor_Status__c,  |
        |           Category__c                       |
        |           FROM Vendor_Account__c            |
        |           WHERE Id = '<Vendor_Account__c>'  |
        |     -> VendorMatch(EMAIL_EXACT, 0.95)       |
        |     vendor_id = Vendor_ID__c (e.g. "V-001") |
        |     vendor_tier = mapped from Vendor_Tier__c |
        |                                             |
        |  Step 2: _match_by_id_in_body(body_text)    |
        |     Regex: (V-\d{3,6}|VN-\d{4,6}|          |
        |             SF-\d{3,6})                     |
        |     If ID found, lookup by Vendor_ID__c:    |
        |     SOQL: SELECT Id, Name, Vendor_ID__c,    |
        |           Vendor_Tier__c, Vendor_Status__c,  |
        |           Category__c                       |
        |           FROM Vendor_Account__c            |
        |           WHERE Vendor_ID__c = '<found_id>' |
        |           LIMIT 1                           |
        |     -> VendorMatch(VENDOR_ID_BODY, 0.90)    |
        |                                             |
        |  Step 3: _match_by_name(sender_name)        |
        |     SOQL: SELECT Id, Name, Vendor_ID__c,    |
        |           Vendor_Tier__c                    |
        |           FROM Vendor_Account__c            |
        |           WHERE Name LIKE '%<sender_name>%' |
        |           LIMIT 5                           |
        |     -> VendorMatch(NAME_SIMILARITY, 0.60)   |
        |                                             |
        |  Step 4: If all fail -> return None         |
        |     (vendor_id = "UNRESOLVED")              |
        |                                             |
        | Graceful degradation:                       |
        |   If Salesforce is down or credentials are  |
        |   wrong, logs the error and returns None.   |
        |   Pipeline continues with UNRESOLVED vendor.|
        |                                             |
        | Output: VendorMatch | None                  |
        |   Fields: vendor_id (Vendor_ID__c e.g.      |
        |   "V-001"), vendor_name, vendor_tier        |
        |   (mapped from Vendor_Tier__c),             |
        |   match_method, match_confidence            |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP E2.4: Thread Correlation
═══════════════════════════════════════════════════════════════

        +=============================================+
        | _determine_thread_status(email)             |
        | File: src/services/email_intake.py          |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input: EmailMessage object                  |
        |                                             |
        | What happens inside:                        |
        |  1. Check email.in_reply_to or              |
        |     email.references (RFC 2822 headers)     |
        |  2. If either present -> "EXISTING_OPEN"    |
        |  3. If only conversation_id -> "NEW"        |
        |     (Phase 2 limitation: full thread lookup  |
        |      from PostgreSQL not yet implemented)   |
        |  4. Otherwise -> "NEW"                      |
        |                                             |
        | Output: str ("NEW" | "EXISTING_OPEN")       |
        |                                             |
        | NOTE: "REPLY_TO_CLOSED" detection requires  |
        |       checking ticket status in ServiceNow  |
        |       — not yet implemented (Phase 6)       |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP E2.5: Upload Attachments to S3
═══════════════════════════════════════════════════════════════

        +=============================================+
        | _upload_attachments_to_s3(email)            |
        | File: src/services/email_intake.py          |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input: EmailMessage with attachments        |
        |                                             |
        | What happens inside:                        |
        |  For each attachment with content_bytes:    |
        |  1. Sanitize message_id (remove < >)        |
        |  2. Build S3 key:                           |
        |     attachments/<message_id>/<filename>     |
        |  3. upload_file() via src/storage/s3_client |
        |  4. Set att.s3_key = key (for DB record)    |
        |  5. Skip attachments without content_bytes  |
        |                                             |
        | Storage writes:                             |
        |   S3 bucket: vqms-email-attachments-prod    |
        |   Key: attachments/<msg_id>/<filename>      |
        |   Content: raw file bytes (PDF, DOCX, etc.) |
        |                                             |
        | Output: None (mutates att.s3_key in place)  |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP E2.6: Store Detailed Email JSON in S3
═══════════════════════════════════════════════════════════════

        +=============================================+
        | _serialize_email_for_storage(email,         |
        |   vendor_id, thread_status)                 |
        | File: src/services/email_intake.py          |
        | Status: [IMPLEMENTED]                       |
        |                                             |
        | Then: upload_file(bucket, key, content)     |
        | File: src/storage/s3_client.py              |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input: EmailMessage + vendor_id + status    |
        |                                             |
        | What happens inside:                        |
        |  1. Best-effort regex extraction from body: |
        |     - invoice_ref: (?:invoice|inv)[#:\s-]*  |
        |     - po_ref: (?:PO|purchase order)[#:\s-]* |
        |     - contract_ref: (?:contract)[#:\s-]*    |
        |     - amount: (?:\$|USD|INR|EUR|GBP)\d+     |
        |  2. Determine is_reply from headers         |
        |  3. Build JSON dict with 30+ fields:        |
        |     email_id, from_address, from_name,      |
        |     to_address, cc_addresses, subject,      |
        |     body_text, body_html, body_preview,     |
        |     has_attachments, attachment_count,       |
        |     attachments (with s3_key), received_at, |
        |     thread_id, conversation_id, in_reply_to,|
        |     references, is_reply, is_auto_reply,    |
        |     language, status ("NEW"), vendor_id,     |
        |     query_type (null), invoice_ref, po_ref, |
        |     contract_ref, amount                    |
        |  4. JSON serialize with indent=2            |
        |  5. Upload via boto3 put_object             |
        |                                             |
        | Storage writes:                             |
        |   S3 bucket: vqms-email-raw-prod            |
        |   Key: emails/<message_id>.json             |
        |   Content: detailed JSON (UTF-8 bytes)      |
        |                                             |
        | Output: s3_uri (s3://bucket/key)            |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP E2.7: Generate Tracking IDs
═══════════════════════════════════════════════════════════════

        +=============================================+
        | generate_correlation_id()                   |
        | generate_execution_id()                     |
        | generate_query_id()                         |
        | File: src/utils/correlation.py              |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Output:                                     |
        |   correlation_id: UUID4 string              |
        |     (follows query through entire pipeline) |
        |   execution_id: UUID4 string                |
        |     (one per workflow orchestrator run)      |
        |   query_id: "VQ-YYYY-NNNN" format           |
        |     (human-readable, shown to vendors)      |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP E2.8: Store Email Record in PostgreSQL
═══════════════════════════════════════════════════════════════

        +=============================================+
        | _store_email_record(email, s3_key,          |
        |   correlation_id, query_id, execution_id,   |
        |   vendor_id, thread_status)                 |
        | File: src/services/email_intake.py          |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input: EmailMessage + all tracking IDs      |
        |                                             |
        | What happens inside:                        |
        |  1. Extract references (invoice, PO, etc.)  |
        |  2. Serialize to/cc as JSON arrays           |
        |  3. INSERT INTO intake.email_messages with   |
        |     30+ columns (all detail fields)         |
        |     ON CONFLICT (message_id) DO NOTHING     |
        |     RETURNING id                            |
        |  4. If row returned (new):                  |
        |     -> For each attachment, INSERT INTO     |
        |        intake.email_attachments             |
        |  5. If row is None (duplicate): skip        |
        |  6. Graceful: if DB down, log + continue    |
        |                                             |
        | Storage writes:                             |
        |   PostgreSQL: intake.email_messages          |
        |     (message_id, sender_email, sender_name, |
        |      to_address, cc_addresses, subject,     |
        |      body_text, body_html, body_preview,    |
        |      has_attachments, attachment_count,      |
        |      raw_s3_key, received_at, thread_id,    |
        |      is_reply, is_auto_reply, language,     |
        |      status, vendor_id, query_type,         |
        |      invoice_ref, po_ref, contract_ref,     |
        |      amount, correlation_id, query_id,      |
        |      execution_id)                          |
        |   PostgreSQL: intake.email_attachments       |
        |     (email_id, filename, content_type,      |
        |      size_bytes, s3_key)                    |
        |                                             |
        | Output: None                                |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP E2.9: Build Payload + Store CaseExecution + Publish + Enqueue
═══════════════════════════════════════════════════════════════

        +=============================================+
        | process_email_notification() continued      |
        | File: src/services/email_intake.py          |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Sub-step A: Build UnifiedQueryPayload       |
        |   Pydantic model combining:                 |
        |   query_id, execution_id, correlation_id,   |
        |   source=EMAIL, vendor_id, vendor_name,     |
        |   subject, description (body_text),         |
        |   thread_status, message_id, received_at    |
        |                                             |
        | Sub-step B: Store CaseExecution             |
        |   _store_case_execution()                   |
        |   INSERT INTO workflow.case_execution       |
        |     (execution_id, query_id, correlation_id,|
        |      status=NEW, source=email, vendor_id)   |
        |   ON CONFLICT (execution_id) DO NOTHING     |
        |   Graceful: if DB down, log + continue      |
        |                                             |
        | Sub-step C: Publish EventBridge event       |
        |   publish_event(detail_type="EmailIngested")|
        |   File: src/events/eventbridge.py           |
        |   Detail: query_id, execution_id, source,   |
        |     vendor_id, message_id, subject,         |
        |     thread_status, sender_email             |
        |   Bus: vqms-event-bus                       |
        |   Source: com.vqms                          |
        |                                             |
        | Sub-step D: Enqueue to SQS                  |
        |   publish(queue_name, message)              |
        |   File: src/queues/sqs.py                   |
        |   Queue: vqms-email-intake-queue            |
        |   Message: UnifiedQueryPayload as JSON      |
        |   Attribute: correlation_id                 |
        |                                             |
        | Storage writes:                             |
        |   PostgreSQL: workflow.case_execution        |
        |   EventBridge: EmailIngested event           |
        |   SQS: vqms-email-intake-queue message       |
        |                                             |
        | Output: dict with query_id, execution_id,   |
        |   correlation_id, status, vendor_id,        |
        |   thread_status                             |
        +=============================================+
               |
               | Message sits in SQS waiting for
               | the LangGraph orchestrator (Phase 3)
               v
        [END OF EMAIL PATH — waits for Phase 3 consumer]
```

---

## PART 2: PORTAL ENTRY POINT (Steps P1 - P6)

A vendor logs into the VQMS portal, fills in a query form, and submits it.
The portal frontend POSTs to our API.

All portal steps (P1-P6) are now implemented as a minimal Angular frontend
with zero styling (browser defaults only). The full flow:

- Step P1 (Login): `frontend/src/app/pages/login/login.component.ts`
  → POST /auth/login (fake auth, any email/password works)
  → Status: [IMPLEMENTED -- fake auth, no Cognito]

- Step P2 (Dashboard): `frontend/src/app/pages/portal/portal.component.ts`
  → GET /dashboard/kpis (KPI counts from PostgreSQL)
  → GET /queries (list queries for vendor from PostgreSQL)
  → Status: [IMPLEMENTED -- basic KPIs from PostgreSQL, no Redis cache]

- Step P3 (Type Selection): `frontend/src/app/pages/new-query-type/new-query-type.component.ts`
  → No server calls (browser-only, stores type in WizardService)
  → Status: [IMPLEMENTED -- browser-only wizard, zero server calls]

- Step P4 (Details Form): `frontend/src/app/pages/new-query-details/new-query-details.component.ts`
  → No server calls (browser-only, stores form data in WizardService)
  → Status: [IMPLEMENTED -- browser-only wizard, zero server calls]

- Step P5 (Review): `frontend/src/app/pages/new-query-review/new-query-review.component.ts`
  → No server calls until user clicks "Submit Query"
  → Status: [IMPLEMENTED -- browser-only wizard, zero server calls]

- Step P6 (Submit): triggered from review page
  → POST /queries with X-Vendor-ID header (from login session)
  → Returns query_id, execution_id, correlation_id, status
  → Status: [IMPLEMENTED -- POST /queries, returns query_id]

Backend routes supporting the portal:
- `src/api/routes/auth.py` → POST /auth/login (fake dev auth)
- `src/api/routes/dashboard.py` → GET /dashboard/kpis, GET /queries, GET /queries/{id}
- `src/api/routes/queries.py` → POST /queries (portal submission)

```
═══════════════════════════════════════════════════════════════
 STEP P6: Portal Query Submission
═══════════════════════════════════════════════════════════════

        +=============================================+
        | create_query(submission, headers)            |
        | File: src/api/routes/queries.py             |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input:                                      |
        |   HTTP POST /queries                        |
        |   Headers:                                  |
        |     X-Vendor-ID: str (REQUIRED)             |
        |     X-Vendor-Name: str (optional)           |
        |     X-Correlation-ID: str (optional)        |
        |   Body: QuerySubmission (Pydantic model)    |
        |     query_type: str (billing, technical...) |
        |     subject: str (non-empty)                |
        |     description: str (non-empty)            |
        |     priority: str (low, medium, high, crit) |
        |     reference_number: str | None            |
        |     attachments: list[str]                  |
        |                                             |
        | What happens inside:                        |
        |  1. Extract vendor_id from X-Vendor-ID      |
        |     header (NEVER from request body)        |
        |     In production: from Cognito JWT claims  |
        |  2. If no vendor_id -> HTTP 401             |
        |  3. Call submit_portal_query() service      |
        |                                             |
        | Output:                                     |
        |   HTTP 201: { query_id, execution_id,       |
        |               correlation_id, status }      |
        |   HTTP 401: missing vendor_id               |
        |   HTTP 409: duplicate query                 |
        |   HTTP 422: validation error                |
        +=============================================+
               |
               | calls submit_portal_query()
               v

═══════════════════════════════════════════════════════════════
 STEP P6 (service layer): Full Portal Pipeline
═══════════════════════════════════════════════════════════════

        +=============================================+
        | submit_portal_query(submission, vendor_id,  |
        |   vendor_name, correlation_id)              |
        | File: src/services/portal_submission.py     |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | What happens inside (7 sub-steps):          |
        |                                             |
        |  1. Generate or use provided correlation_id |
        |  2. Generate execution_id + query_id        |
        |  3. Idempotency check:                      |
        |     _check_idempotency("portal:{vendor_id}: |
        |       {subject}")                           |
        |     Redis key: vqms:idempotency:portal:...  |
        |     TTL: 604800 (7 days)                    |
        |     -> DuplicateQueryError if exists         |
        |     -> Graceful if Redis down               |
        |                                             |
        |  4. Build UnifiedQueryPayload:              |
        |     source=PORTAL, vendor_id from JWT/header|
        |     subject, description, query_type,       |
        |     priority, reference_number              |
        |     thread_status=None, message_id=None     |
        |                                             |
        |  5. Store CaseExecution in PostgreSQL:      |
        |     INSERT INTO workflow.case_execution     |
        |     ON CONFLICT DO NOTHING                  |
        |     Graceful: if DB down, log + continue    |
        |                                             |
        |  6. Publish EventBridge event:              |
        |     detail_type="QueryReceived"             |
        |     Bus: vqms-event-bus                     |
        |                                             |
        |  7. Enqueue to SQS:                         |
        |     Queue: vqms-query-intake-queue          |
        |     Message: UnifiedQueryPayload as JSON    |
        |                                             |
        | Storage writes:                             |
        |   Redis: vqms:idempotency:portal:<vendor>:  |
        |          <subject> (TTL 7 days)             |
        |   PostgreSQL: workflow.case_execution        |
        |   EventBridge: QueryReceived event           |
        |   SQS: vqms-query-intake-queue message       |
        |                                             |
        | Output: dict with query_id, execution_id,   |
        |   correlation_id, status="accepted"         |
        +=============================================+
               |
               | Message sits in SQS waiting for
               | the LangGraph orchestrator (Phase 3)
               v
        [END OF PORTAL PATH — waits for Phase 3 consumer]
```

---

## PART 3: SQS CONSUMER + CONTEXT LOADING (Step 7)

Both email and portal paths produce a `UnifiedQueryPayload` on SQS.
The SQS consumer polls the queue, deserializes the message, builds
a LangGraph PipelineState, and runs the full AI pipeline.

```
  +=====================================================+
  | UnifiedQueryPayload (on SQS)                        |
  | File: src/models/query.py                           |
  +=====================================================+
  | query_id:         "VQ-2026-XXXX"                    |
  | execution_id:     "<uuid>"                          |
  | correlation_id:   "<uuid>"                          |
  | source:           "email" | "portal"                |
  | vendor_id:        "SF-XXX" | "UNRESOLVED" | None    |
  | vendor_name:      "Vendor Corp" | None              |
  | subject:          "Invoice query..."                |
  | description:      "Full body text..."               |
  | query_type:       "billing" | None (email path)     |
  | priority:         "high" | None (email path)        |
  | reference_number: "INV-2026-XXXX" | None            |
  | thread_status:    "NEW" | "EXISTING_OPEN" | None    |
  | message_id:       "<RFC2822 id>" | None (portal)    |
  | received_at:      "2026-04-07T05:15:37+00:00"       |
  +=====================================================+
        |
        v

═══════════════════════════════════════════════════════════════
 STEP 7.0: SQS Consumer Polls Message
═══════════════════════════════════════════════════════════════

        +=============================================+
        | start_consumer(shutdown_event)              |
        | File: src/orchestration/sqs_consumer.py     |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | What happens:                               |
        |  1. Long-poll SQS (WaitTimeSeconds=20,      |
        |     VisibilityTimeout=300)                   |
        |  2. Uses raw boto3 receive_message           |
        |     (NOT the existing consume() which        |
        |      auto-deletes — we need delete-on-       |
        |      success-only for reliability)           |
        |  3. Deserialize JSON → dict                  |
        |  4. Build PipelineState TypedDict with       |
        |     12 fields (payload, IDs, nulls)          |
        |  5. Call graph.ainvoke(initial_state)         |
        |  6. On success: delete_message               |
        |  7. On failure: log error, leave message     |
        |     for retry/DLQ (3 retries max)            |
        |                                              |
        | Also started as background task in:          |
        |   main.py -> lifespan() -> asyncio.create_task |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP 7.1-7.4: Context Loading Node
═══════════════════════════════════════════════════════════════

        +=============================================+
        | context_loading_node(state)                 |
        | File: src/orchestration/nodes/              |
        |       context_loading.py                    |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input: PipelineState (payload + IDs)        |
        |                                             |
        | What happens inside:                        |
        |  7.1 Update workflow.case_execution          |
        |      status → "analyzing"                    |
        |      via _update_case_status()               |
        |                                              |
        |  7.2 Cache workflow state in Redis            |
        |      Key: vqms:workflow:<execution_id>        |
        |      TTL: 24 hours                            |
        |      via _cache_workflow_state()              |
        |                                              |
        |  7.3 Load vendor profile                     |
        |      File: src/services/memory_context.py    |
        |      → load_vendor_profile(vendor_id,        |
        |          sender_email, correlation_id)        |
        |      First checks Redis cache                |
        |        (vqms:vendor:<id>, 1h TTL)             |
        |      On miss → Salesforce adapter:            |
        |        find_account_by_vendor_id()             |
        |        find_account_by_id()                    |
        |        find_contact_by_email()                 |
        |      Caches result in Redis for 1 hour        |
        |      Returns: VendorProfile | None            |
        |                                              |
        |  7.4 Load vendor history                     |
        |      File: src/services/memory_context.py    |
        |      → load_vendor_history(vendor_id,        |
        |          correlation_id)                      |
        |      SQL: SELECT summary, resolution_path,    |
        |        metadata FROM memory.episodic_memory   |
        |        WHERE vendor_id = :id                  |
        |        ORDER BY created_at DESC LIMIT 10      |
        |      Returns: list[dict]                      |
        |                                              |
        |  7.5 Initialize Budget from settings          |
        |      (max_tokens_in, max_tokens_out,          |
        |       currency_limit_usd from .env)            |
        |                                              |
        |  7.6 Write audit log + publish event          |
        |      EventBridge: AnalysisStarted              |
        |      audit.action_log: context_loaded          |
        |                                              |
        | Storage writes:                               |
        |   PostgreSQL: workflow.case_execution (status) |
        |   Redis: vqms:workflow:<exec_id> (24h TTL)     |
        |   Redis: vqms:vendor:<id> (1h TTL, on miss)    |
        |   EventBridge: AnalysisStarted event           |
        |   audit.action_log: context_loaded             |
        |                                              |
        | Output: PipelineState with vendor_profile,    |
        |   vendor_history, budget populated             |
        +=============================================+
               |
               v
```

---

## PART 4: QUERY ANALYSIS -- LLM CALL #1 (Step 8)

```
═══════════════════════════════════════════════════════════════
 STEP 8: Query Analysis Agent (LLM Call #1)
═══════════════════════════════════════════════════════════════

        +=============================================+
        | query_analysis_node(state)                  |
        | File: src/orchestration/nodes/              |
        |       query_analysis_node.py                |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input: PipelineState with payload,          |
        |   vendor_profile, vendor_history, budget    |
        |                                             |
        | What happens inside:                        |
        |  1. Create QueryAnalysisAgent instance       |
        |     File: src/agents/query_analysis.py       |
        |     Inherits: src/agents/abc_agent.py        |
        |                                              |
        |  2. Agent renders Jinja2 prompt template     |
        |     File: prompts/query_analysis/v1.jinja    |
        |     Context: query (subject, description,    |
        |       query_type, reference_number),          |
        |       vendor_profile, vendor_history          |
        |                                              |
        |  3. Agent calls LLM via factory (auto fallback)|
        |     File: src/llm/factory.py                 |
        |     → llm_complete(prompt, system_prompt,    |
        |         temperature=0.1, max_tokens=4096)    |
        |     Provider chain: Bedrock → OpenAI         |
        |       (configurable via LLM_PROVIDER env)    |
        |     Tenacity retry per provider              |
        |     Returns: {text, tokens_in, tokens_out,    |
        |       cost_usd, latency_ms, model, provider,  |
        |       was_fallback}                           |
        |                                              |
        |  4. Parse JSON response                      |
        |     BaseAgent.parse_json_response()           |
        |     Strips markdown fences (```json ... ```)  |
        |     On parse failure: retry once with         |
        |       "fix JSON" prompt                       |
        |     On second failure: return AnalysisResult  |
        |       with confidence_score=0.0               |
        |       (triggers Path C)                       |
        |                                              |
        |  5. Build AnalysisResult                     |
        |     File: src/models/workflow.py              |
        |     Fields: intent_classification,            |
        |       extracted_entities, urgency_level,      |
        |       sentiment, confidence_score,            |
        |       multi_issue_detected,                   |
        |       suggested_category, raw_llm_output,     |
        |       tokens_in, tokens_out, cost_usd,        |
        |       latency_ms                              |
        |                                              |
        |  6. Persist analysis result                   |
        |     PostgreSQL: UPDATE case_execution          |
        |       SET analysis_result = <JSONB>            |
        |     Redis: update workflow state               |
        |       → status = "analysis_complete"           |
        |     S3: upload prompt snapshot to              |
        |       vqms-audit-artifacts-prod                |
        |     EventBridge: AnalysisCompleted event       |
        |     audit.action_log: analysis_completed       |
        |                                              |
        | Storage writes:                               |
        |   PostgreSQL: case_execution.analysis_result   |
        |   Redis: vqms:workflow:<exec_id>               |
        |   S3: audit-artifacts/prompts/<exec_id>.json   |
        |   EventBridge: AnalysisCompleted               |
        |   audit.action_log: analysis_completed         |
        |                                              |
        | Output: PipelineState with analysis_result    |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP 8 DECISION: Confidence Check
═══════════════════════════════════════════════════════════════

        +=============================================+
        | check_confidence(state)                     |
        | File: src/orchestration/nodes/              |
        |       confidence_check.py                   |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Conditional edge function:                  |
        |   confidence >= 0.85 → returns "pass"       |
        |     → continues to Step 9                    |
        |   confidence <  0.85 → returns "fail"       |
        |     → routes to Path C stub                  |
        |                                              |
        | Threshold from: settings.agent_confidence_   |
        |   threshold (default 0.85)                   |
        +=============================================+
               |
          +----+----+
          |         |
     "pass"        "fail"
          |         |
          v         v
     [Step 9]   [Path C Stub]
```

---

## PART 5: ROUTING + KB SEARCH (Step 9)

```
═══════════════════════════════════════════════════════════════
 STEP 9: Routing + KB Search (Parallel)
═══════════════════════════════════════════════════════════════

        +=============================================+
        | routing_and_kb_search_node(state)           |
        | File: src/orchestration/nodes/              |
        |       routing_and_kb_search.py              |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Input: PipelineState with analysis_result,  |
        |   vendor_profile, payload                   |
        |                                             |
        | Runs TWO operations in parallel via         |
        | asyncio.gather():                           |
        |                                             |
        | 9A. Routing Service (deterministic rules)   |
        |   File: src/services/routing.py             |
        |   → route_query(analysis, vendor_profile,   |
        |       execution_id, correlation_id)          |
        |                                              |
        |   SLA Matrix (16 combinations):              |
        |     PLATINUM: CRITICAL=1h, HIGH=2h,          |
        |               MEDIUM=4h,  LOW=8h             |
        |     GOLD:     CRITICAL=2h, HIGH=4h,          |
        |               MEDIUM=8h,  LOW=16h            |
        |     SILVER:   CRITICAL=4h, HIGH=8h,          |
        |               MEDIUM=16h, LOW=24h            |
        |     STANDARD: CRITICAL=4h, HIGH=12h,         |
        |               MEDIUM=24h, LOW=48h            |
        |                                              |
        |   Team Assignment by category:               |
        |     invoice_payment → Finance Team            |
        |     purchase_order  → Procurement Team        |
        |     contract        → Contract Team           |
        |     general         → General Support         |
        |                                              |
        |   Checks BLOCK_AUTOMATION risk flag           |
        |   Writes to workflow.routing_decision table    |
        |   Returns: RoutingDecision                    |
        |                                              |
        | 9B. KB Search Service (embedding + pgvector)  |
        |   File: src/services/kb_search.py            |
        |   → search_kb(query_text, category,          |
        |       correlation_id)                         |
        |                                              |
        |   1. Embed query via llm_embed() factory       |
        |      (Bedrock Titan v2 or OpenAI, 1536 dims)  |
        |      Auto fallback if primary fails           |
        |   2. Format vector as pgvector string          |
        |      "[0.1,0.2,...]"                          |
        |   3. SQL cosine similarity search:             |
        |      SELECT record_id, source_document,        |
        |        chunk_text, metadata,                   |
        |        1-(embedding <=> :vec::vector)          |
        |        AS similarity                           |
        |      FROM memory.embedding_index               |
        |      WHERE metadata->>'category' = :cat        |
        |      ORDER BY embedding <=> :vec::vector       |
        |      LIMIT 5                                   |
        |   4. Filter by threshold (0.80)                |
        |   5. has_specific_facts heuristic:             |
        |      7 regex patterns for dollar amounts,      |
        |      dates, Net terms, steps, timeframes       |
        |   Returns: KBSearchResponse                    |
        |     (results, top_score, search_latency_ms)    |
        |                                              |
        | Storage writes:                               |
        |   PostgreSQL: workflow.routing_decision         |
        |                                              |
        | Output: PipelineState with routing_decision    |
        |   and kb_search_response                       |
        +=============================================+
               |
               v

═══════════════════════════════════════════════════════════════
 STEP 9 DECISION: Path A vs Path B
═══════════════════════════════════════════════════════════════

        +=============================================+
        | decide_path(state)                          |
        | File: src/orchestration/nodes/              |
        |       path_decision.py                      |
        | Status: [IMPLEMENTED]                       |
        +=============================================+
        |                                             |
        | Conditional edge function:                  |
        |                                             |
        |   Path A (AI-Resolved) requires ALL:        |
        |     - KB top_score >= threshold (0.80)       |
        |     - At least 1 result has_specific_facts   |
        |     - Automation NOT blocked                  |
        |       (no BLOCK_AUTOMATION risk flag)         |
        |                                              |
        |   Path B (Human-Team) if ANY fails           |
        |                                              |
        | Returns: "path_a" | "path_b"                 |
        +=============================================+
               |
          +----+----+
          |         |
     "path_a"   "path_b"
          |         |
          v         v
     [Path A]   [Path B]
       Stub       Stub
```

---

## PART 5B: PATH STUBS (A/B/C)

All three paths currently end at stubs that update status and
publish events. Phase 4 will replace Path A and B stubs with
real Resolution Agent and Communication Drafting Agent.

```
        +=============================================+
        | path_a_stub(state)                          |
        | path_b_stub(state)                          |
        | path_c_stub(state)                          |
        | File: src/orchestration/nodes/path_stubs.py |
        | Status: [IMPLEMENTED — stubs for Phase 4]   |
        +=============================================+
        |                                             |
        | Each stub does:                             |
        |  1. Update case_execution status             |
        |     Path A: "resolving_ai"                   |
        |     Path B: "awaiting_team_resolution"       |
        |     Path C: "awaiting_human_review"          |
        |  2. Update Redis workflow state               |
        |  3. Publish EventBridge event                 |
        |     PathASelected / PathBSelected /            |
        |     HumanReviewRequired                       |
        |  4. Write audit log                           |
        |  5. Set state["selected_path"] = "A"/"B"/"C"  |
        |                                              |
        | Storage writes:                               |
        |   PostgreSQL: case_execution (status)          |
        |   Redis: vqms:workflow:<exec_id>               |
        |   EventBridge: path event                      |
        |   audit.action_log: path_selected              |
        |                                              |
        | Output: PipelineState with selected_path      |
        |   → graph reaches END                          |
        +=============================================+
```

---

## LANGGRAPH PIPELINE DIAGRAM

```
  +==================+     +==================+     +=================+
  | context_loading  | --> | query_analysis   | --> | confidence_check|
  | (Step 7)         |     | (Step 8)         |     | (conditional)   |
  +==================+     +==================+     +=================+
                                                          |
                                              +-----------+-----------+
                                              |                       |
                                           "pass"                  "fail"
                                              |                       |
                                              v                       v
                                    +==================+    +================+
                                    | routing_and_kb   |    | path_c_stub    |
                                    | _search (Step 9) |    | (Path C)       |
                                    +==================+    +================+
                                              |                       |
                                              v                       v
                                    +=================+             END
                                    | path_decision   |
                                    | (conditional)   |
                                    +=================+
                                              |
                                    +---------+---------+
                                    |                   |
                                 "path_a"            "path_b"
                                    |                   |
                                    v                   v
                              +===========+      +===========+
                              | path_a    |      | path_b    |
                              | _stub     |      | _stub     |
                              +===========+      +===========+
                                    |                   |
                                    v                   v
                                   END                 END

  File: src/orchestration/graph.py -> build_pipeline_graph()
  State: src/orchestration/graph.py -> PipelineState (TypedDict, 12 fields)
```

---

## PART 6: PATH A -- AI-RESOLVED (Steps 10A - 12A)

```
  +=====================================================+
  | [NOT BUILT -- Phase 4]                              |
  |                                                     |
  | Step 10A: Resolution Agent (LLM Call #2)            |
  |   File: src/agents/resolution.py                    |
  |   Current state: src/agents/__init__.py is empty    |
  |   Pydantic models ready:                            |
  |     -> DraftResponse [IMPLEMENTED]                  |
  |     -> DraftEmailPackage [IMPLEMENTED]              |
  |                                                     |
  | Step 11A: Quality Gate (7 checks)                   |
  |   File: src/gates/quality_governance.py             |
  |   Current state: src/gates/__init__.py is empty     |
  |   Pydantic model ready:                             |
  |     -> ValidationReport [IMPLEMENTED]               |
  |                                                     |
  | Step 12A: Ticket Creation + Email Delivery          |
  |   Ticket: src/services/ticket_ops.py [NOT BUILT]    |
  |   Email send: src/adapters/graph_api.py             |
  |     -> send_email() [IMPLEMENTED]                   |
  |   ServiceNow: src/adapters/servicenow.py [NOT BUILT]|
  |   Pydantic models ready:                            |
  |     -> TicketRecord [IMPLEMENTED]                   |
  |     -> TicketLink [IMPLEMENTED]                     |
  +=====================================================+
```

---

## PART 7: PATH B -- HUMAN-TEAM-RESOLVED (Steps 10B - 15)

```
  +=====================================================+
  | [NOT BUILT -- Phase 4/6]                            |
  |                                                     |
  | Step 10B: Communication Drafting Agent              |
  |   File: src/agents/communication_drafting.py        |
  |   Current state: src/agents/__init__.py is empty    |
  |   Writes acknowledgment-only email (no answer)      |
  |                                                     |
  | Step 11B: Quality Gate (same 7 checks)              |
  |   File: src/gates/quality_governance.py [NOT BUILT] |
  |                                                     |
  | Step 12B: Ticket + Acknowledgment Email             |
  |   ServiceNow ticket (team INVESTIGATES)             |
  |   Acknowledgment email sent to vendor               |
  |                                                     |
  | Step 14-15: Human team resolves, AI drafts          |
  |   ServiceNow webhook triggers Communication Agent   |
  |   Agent drafts resolution from team's notes         |
  |   Quality Gate validates -> email sent              |
  +=====================================================+
```

---

## PART 8: PATH C -- LOW-CONFIDENCE REVIEW (Steps 8C)

```
  +=====================================================+
  | [NOT BUILT -- Phase 5]                              |
  |                                                     |
  | Step 8C.1: Create TriagePackage                     |
  |   Pydantic model ready: src/models/triage.py        |
  |     -> TriagePackage [IMPLEMENTED]                  |
  |   Step Functions callback token pattern             |
  |   File: src/orchestration/step_functions.py         |
  |   Current state: src/orchestration/__init__.py empty|
  |                                                     |
  | Step 8C.2: Human Reviewer Reviews                   |
  |   API: GET /triage/queue [NOT BUILT]                |
  |   API: POST /triage/{id}/review [NOT BUILT]         |
  |                                                     |
  | Step 8C.3: Workflow Resumes                          |
  |   Step Functions SendTaskSuccess                    |
  |   Corrected data re-enters pipeline at Step 9       |
  |   SLA clock starts AFTER review completes           |
  +=====================================================+
```

---

## PART 9: SLA MONITORING (Step 13)

```
  +=====================================================+
  | [NOT BUILT -- Phase 6]                              |
  |                                                     |
  | File: src/monitoring/sla_alerting.py                |
  | Current state: src/monitoring/__init__.py is empty  |
  |                                                     |
  | What will happen:                                   |
  |  - Watch ticket age via Step Functions wait states   |
  |  - 70% of SLA: warn resolver                        |
  |  - 85% of SLA: L1 manager escalation               |
  |  - 95% of SLA: L2 senior escalation                |
  |  - Path C: SLA starts AFTER review, not before      |
  |                                                     |
  | PostgreSQL schema ready:                            |
  |   reporting.sla_metrics [SCHEMA BUILT]              |
  | Redis key ready:                                    |
  |   vqms:sla:<ticket_id> (no auto-expire)             |
  +=====================================================+
```

---

## PART 10: CLOSURE AND REOPEN (Step 16)

```
  +=====================================================+
  | [NOT BUILT -- Phase 6]                              |
  |                                                     |
  | What will happen:                                   |
  |  - Vendor replies with confirmation -> close ticket |
  |  - 5 business day auto-close if no reply            |
  |  - Reopen: new email on closed ticket               |
  |    -> decide: reopen same ticket vs link new ticket  |
  |  - Save episodic memory for future context           |
  |                                                     |
  | PostgreSQL schema ready:                            |
  |   memory.episodic_memory [SCHEMA BUILT]             |
  +=====================================================+
```

---

## WHAT IS BUILT (working code)

### API Routes
| File | Function | What it does |
|------|----------|-------------|
| `src/api/routes/webhooks.py` | `handle_graph_notification()` | Receives Graph webhook, processes email |
| `src/api/routes/queries.py` | `create_query()` | Portal POST /queries submission |
| `src/api/routes/email_dashboard.py` | `list_email_chains()` | GET /emails — paginated email chain list with filters |
| `src/api/routes/email_dashboard.py` | `get_email_stats()` | GET /emails/stats — dashboard aggregate statistics |
| `src/api/routes/email_dashboard.py` | `get_email_chain()` | GET /emails/{query_id} — single email chain |
| `src/api/routes/email_dashboard.py` | `download_attachment()` | GET /emails/{query_id}/attachments/{id}/download — presigned S3 URL |
| `src/api/routes/dashboard.py` | `get_dashboard_kpis()` | GET /dashboard/kpis — portal vendor KPIs |
| `src/api/routes/dashboard.py` | `list_queries()` | GET /queries — vendor query list |
| `src/api/routes/dashboard.py` | `get_query_detail()` | GET /queries/{query_id} — single query detail |
| `src/api/routes/auth.py` | `login()` | POST /auth/login — real JWT auth against tbl_users |
| `src/api/routes/auth.py` | `logout()` | POST /auth/logout — blacklist token in Redis |
| `src/api/routes/vendors.py` | `list_vendors()` | GET /vendors — list active vendors from Salesforce Account |
| `src/api/routes/vendors.py` | `update_vendor()` | PUT /vendors/{vendor_id} — update vendor in Salesforce Account |
| `src/api/middleware/auth_middleware.py` | `AuthMiddleware` | JWT validation middleware on all protected routes |
| `main.py` | `health_check()` | GET /health with DB + Redis status |
| `main.py` | `lifespan()` | Startup/shutdown (SSH tunnel, DB, Redis) |

### Services
| File | Function | What it does |
|------|----------|-------------|
| `src/services/email_dashboard_service.py` | `fetch_mail_chains()` | Paginated email chains from PostgreSQL |
| `src/services/email_dashboard_service.py` | `fetch_single_mail_chain()` | Single chain by query_id |
| `src/services/email_dashboard_service.py` | `fetch_email_stats()` | Aggregate stats for dashboard |
| `src/services/email_dashboard_service.py` | `generate_attachment_download_url()` | Presigned S3 download URL |
| `src/services/email_intake.py` | `process_email_notification()` | Full 11-step email pipeline |
| `src/services/email_intake.py` | `_check_email_idempotency()` | Redis dedup for emails |
| `src/services/email_intake.py` | `_determine_thread_status()` | NEW vs EXISTING_OPEN |
| `src/services/email_intake.py` | `_serialize_email_for_storage()` | Detailed JSON for S3 |
| `src/services/email_intake.py` | `_extract_reference()` | Regex invoice/PO/contract extraction |
| `src/services/email_intake.py` | `_extract_amount()` | Regex currency amount extraction |
| `src/services/email_intake.py` | `_upload_attachments_to_s3()` | Upload attachment files to S3 |
| `src/services/email_intake.py` | `_store_email_record()` | Write to intake.email_messages + attachments |
| `src/services/email_intake.py` | `_store_case_execution()` | Write to workflow.case_execution |
| `src/services/portal_submission.py` | `submit_portal_query()` | Full 7-step portal pipeline |
| `src/services/portal_submission.py` | `_check_idempotency()` | Redis dedup for portal |
| `src/services/portal_submission.py` | `_store_case_execution()` | Write to workflow.case_execution |
| `src/services/memory_context.py` | `load_vendor_profile()` | Redis cache → Salesforce → cache result |
| `src/services/memory_context.py` | `load_vendor_history()` | SELECT from memory.episodic_memory LIMIT 10 |
| `src/services/routing.py` | `route_query()` | SLA matrix + team assignment + automation check |
| `src/services/routing.py` | `calculate_sla_hours()` | 16-cell SLA matrix lookup |
| `src/services/routing.py` | `assign_team()` | Category → team mapping |
| `src/services/routing.py` | `check_automation_blocked()` | BLOCK_AUTOMATION risk flag check |
| `src/services/kb_search.py` | `search_kb()` | Embed query → pgvector cosine similarity search |
| `src/services/auth.py` | `authenticate_user()` | Login: query tbl_users, verify password, query tbl_user_roles, create JWT |
| `src/services/auth.py` | `create_access_token()` | Create signed JWT with sub, role, tenant, exp, iat, jti claims |
| `src/services/auth.py` | `validate_token()` | Decode JWT, check Redis blacklist |
| `src/services/auth.py` | `blacklist_token()` | Store JTI in Redis with TTL for logout |
| `src/services/auth.py` | `refresh_token_if_expiring()` | Create new token if < 300s remaining, blacklist old |

### Agents
| File | Function | What it does |
|------|----------|-------------|
| `src/agents/abc_agent.py` | `BaseAgent` | Jinja2 template loading, LLM calls, JSON parsing, budget tracking |
| `src/agents/query_analysis.py` | `QueryAnalysisAgent.analyze_query()` | LLM Call #1: intent, entities, urgency, confidence |

### Adapters
| File | Function | What it does |
|------|----------|-------------|
| `src/adapters/graph_api.py` | `fetch_email_by_resource()` | Fetch email from Graph API |
| `src/adapters/graph_api.py` | `fetch_latest_email()` | Fetch most recent email |
| `src/adapters/graph_api.py` | `send_email()` | Send email via Graph /sendMail |
| `src/adapters/graph_api.py` | `_fetch_attachments_with_content()` | Download attachment bytes |
| `src/adapters/graph_api.py` | `_get_access_token()` | MSAL OAuth2 token |
| `src/adapters/graph_api.py` | `_detect_auto_reply()` | Check auto-reply headers |
| `src/adapters/graph_api.py` | `_extract_recipient_emails()` | Parse to/cc from Graph |
| `src/adapters/salesforce.py` | `SalesforceAdapter` | Real Salesforce SOQL queries (Vendor_Contact__c, Vendor_Account__c) |
| `src/adapters/salesforce.py` | `get_all_active_vendors()` | SOQL on standard Account WHERE Vendor_Status__c = 'Active' |
| `src/adapters/salesforce.py` | `update_vendor_account()` | Find Account by Vendor_ID__c, update allowed fields |
| `src/services/vendor_resolution.py` | `resolve_vendor()` | 3-step vendor match via real Salesforce custom objects |
| `src/adapters/bedrock.py` | `invoke_llm()` | Claude Sonnet 3.5 via Bedrock Messages API (with retry) |
| `src/adapters/bedrock.py` | `embed_text()` | Titan Embed v2 → 1536-dim vector |
| `src/adapters/bedrock.py` | `BedrockProvider` | Protocol-compatible wrapper for factory |
| `src/adapters/openai_provider.py` | `OpenAIProvider` | GPT-4o + text-embedding-3-small (fallback provider) |
| `src/llm/protocol.py` | `LLMProvider` | Protocol interface for all LLM providers |
| `src/llm/factory.py` | `llm_complete()` | LLM calls with automatic provider fallback |
| `src/llm/factory.py` | `llm_embed()` | Embedding calls with automatic provider fallback |

### Orchestration (Phase 3)
| File | Function | What it does |
|------|----------|-------------|
| `src/orchestration/graph.py` | `build_pipeline_graph()` | LangGraph StateGraph with conditional edges |
| `src/orchestration/sqs_consumer.py` | `start_consumer()` | SQS long-poll → LangGraph pipeline → delete on success |
| `src/orchestration/nodes/context_loading.py` | `context_loading_node()` | Step 7: status, Redis, vendor profile, history, budget |
| `src/orchestration/nodes/query_analysis_node.py` | `query_analysis_node()` | Step 8: wraps QueryAnalysisAgent, persists results |
| `src/orchestration/nodes/confidence_check.py` | `check_confidence()` | Conditional: >= 0.85 pass, < 0.85 fail |
| `src/orchestration/nodes/routing_and_kb_search.py` | `routing_and_kb_search_node()` | Step 9: parallel routing + KB search |
| `src/orchestration/nodes/path_decision.py` | `decide_path()` | Conditional: Path A (KB+facts) vs Path B |
| `src/orchestration/nodes/path_stubs.py` | `path_a_stub()` / `path_b_stub()` / `path_c_stub()` | Status update stubs for Phase 4 |

### Infrastructure
| File | Function | What it does |
|------|----------|-------------|
| `src/db/connection.py` | `start_ssh_tunnel()` | SSH tunnel to bastion -> RDS |
| `src/db/connection.py` | `init_db()` | Async SQLAlchemy engine |
| `src/db/connection.py` | `get_engine()` | Return engine singleton |
| `src/db/connection.py` | `close_db()` | Dispose engine |
| `src/db/connection.py` | `stop_ssh_tunnel()` | Close SSH tunnel |
| `src/db/connection.py` | `check_db_health()` | SELECT 1 health check |
| `src/cache/redis_client.py` | `init_redis()` | Async Redis connection |
| `src/cache/redis_client.py` | 8 key builders | idempotency, session, vendor, workflow, sla, dashboard, thread, auth_blacklist |
| `src/cache/redis_client.py` | `exists_key()` | Check if Redis key exists (used by token blacklist) |
| `src/cache/redis_client.py` | `set_with_ttl()` / `get_value()` | Redis read/write helpers |
| `src/storage/s3_client.py` | `upload_file()` / `download_file()` | S3 put/get via boto3 |
| `src/events/eventbridge.py` | `publish_event()` | EventBridge put_events |
| `src/queues/sqs.py` | `publish()` / `consume()` | SQS send/receive |
| `src/queues/sqs.py` | `get_queue_size()` | SQS queue depth |
| `src/utils/correlation.py` | 3 ID generators | correlation, execution, query IDs |
| `src/utils/logger.py` | `setup_logging()` | structlog + file handler |
| `src/utils/exceptions.py` | `DuplicateQueryError` | Idempotency violation |
| `src/utils/exceptions.py` | `VendorNotFoundError` | Vendor lookup failure |
| `src/utils/helpers.py` | `utc_now()` | UTC datetime helper |

### Database Migrations (all executed on RDS)
| File | What it creates |
|------|-----------------|
| `001_intake_schema.sql` | intake.email_messages, intake.email_attachments |
| `002_workflow_schema.sql` | workflow.case_execution, workflow.ticket_link, workflow.routing_decision |
| `003_memory_schema.sql` | memory.episodic_memory, memory.vendor_profile_cache, memory.embedding_index (pgvector) |
| `004_audit_schema.sql` | audit.action_log, audit.validation_results |
| `005_reporting_schema.sql` | reporting.sla_metrics |
| `006_intake_add_detail_columns.sql` | ALTER TABLE: 14 new columns on intake.email_messages |
| `007_auth_tables_documentation.sql` | Documents existing public.tbl_users + public.tbl_user_roles (CREATE IF NOT EXISTS) |

### Pydantic Models (all in src/models/)
| File | Models |
|------|--------|
| `email.py` | EmailAttachment, EmailMessage, ParsedEmailPayload |
| `query.py` | QuerySubmission, UnifiedQueryPayload |
| `vendor.py` | VendorTier (enum), VendorMatch, VendorProfile, VendorAccountData, VendorUpdateRequest, VendorUpdateResult |
| `auth.py` | UserRecord, UserRoleRecord, LoginRequest, LoginResponse, TokenPayload |
| `workflow.py` | Status, UrgencyLevel, Sentiment, QuerySource, QueryType, Priority (enums), AnalysisResult, WorkflowState, CaseExecution |
| `ticket.py` | TicketRecord, TicketLink, RoutingDecision |
| `communication.py` | DraftResponse, DraftEmailPackage, ValidationReport |
| `memory.py` | EpisodicMemory, VendorProfileCache, EmbeddingRecord |
| `budget.py` | Budget (with is_within_budget, remaining_* properties) |
| `triage.py` | ReviewStatus, TriagePackage |
| `messages.py` | ToolCall, AgentMessage |
| `kb.py` | KBSearchResult, KBSearchResponse |

### Prompt Templates
| File | What it does |
|------|-------------|
| `prompts/query_analysis/v1.jinja` | Query Analysis Agent prompt — intent, entities, urgency, confidence |

### KB Seed Data
| File | Category |
|------|----------|
| `data/knowledge_base/invoice_payment_process.md` | billing |
| `data/knowledge_base/overdue_invoice_policy.md` | billing |
| `data/knowledge_base/ap_processing_timeline.md` | billing |
| `data/knowledge_base/po_mismatch_resolution.md` | billing |
| `data/knowledge_base/general_vendor_inquiry.md` | general |
| `src/db/seeds/seed_kb_articles.py` | Reads .md, chunks, embeds via Titan, inserts into pgvector |

### Scripts
| File | What it does |
|------|-------------|
| `scripts/run_email_intake.py` | Run full email pipeline against real cloud services |
| `scripts/run_pipeline.py` | Run AI pipeline (--consumer-only / --server-only) |
| `scripts/run_migrations.py` | Execute SQL migrations on RDS via SSH tunnel |
| `scripts/check_db.py` | Diagnose PostgreSQL connectivity, list DBs/tables |
| `scripts/check_aws.py` | Check S3, SQS, EventBridge connectivity |
| `scripts/check_graph_api.py` | Check Graph API auth, mailbox, permissions |
| `tests/manual/test_salesforce_connection.py` | Test Salesforce connection, query Contacts/Accounts |
| `tests/manual/test_bedrock_connection.py` | Test Bedrock LLM + embedding calls |
| `tests/manual/test_kb_search.py` | Test KB search after seeding articles |
| `tests/manual/test_phase3_pipeline.py` | Full end-to-end Phase 3 pipeline test |

### Tests
| File | Tests | What they cover |
|------|-------|----------------|
| `tests/unit/test_models.py` | ~80 | All Pydantic models and enums |
| `tests/unit/test_adapters.py` | ~15 | S3, SQS, EventBridge (moto), Salesforce stub |
| `tests/unit/test_redis_keys.py` | ~15 | All 7 key families, TTLs, prefix |
| `tests/unit/test_correlation.py` | ~10 | UUID format, query ID format, uniqueness |
| `tests/unit/test_email_intake.py` | ~11 | Email pipeline + thread correlation |
| `tests/unit/test_portal_submission.py` | ~7 | Portal pipeline, dedup, graceful Redis |
| `tests/unit/test_db_connection.py` | ~16 | SSH tunnel, engine lifecycle, health |
| `tests/unit/test_auth_models.py` | 11 | Auth Pydantic models (UserRecord, LoginRequest, TokenPayload, etc.) |
| `tests/unit/test_auth_service.py` | 13 | JWT create/validate/blacklist/refresh, authenticate_user mocked |
| `tests/unit/test_auth_middleware.py` | 10 | _should_skip_auth for all skip/non-skip paths |
| `tests/unit/test_vendor_crud.py` | 8 | VendorAccountData, VendorUpdateRequest, VendorUpdateResult |
| `tests/integration/test_email_intake_e2e.py` | ~10 | Full E2E with moto AWS + webhook endpoint |

---

## WHAT IS STUBBED (mock data, not real integration)

No components are currently stubbed. All adapters connect to real services.

---

## WHAT IS NOT BUILT YET

These architecture doc components have zero code (only empty `__init__.py` files or no file at all):

| Component | Target File | Phase |
|-----------|-------------|-------|
| Orchestration Router | `src/orchestration/router.py` | Phase 4+ |
| Orchestration Manager | `src/orchestration/manager.py` | Phase 4+ |
| Step Functions Integration | `src/orchestration/step_functions.py` | Phase 5 |
| Resolution Agent | `src/agents/resolution.py` | Phase 4 |
| Communication Drafting Agent | `src/agents/communication_drafting.py` | Phase 4 |
| Orchestration Agent | `src/agents/orchestration.py` | Phase 4+ |
| Quality & Governance Gate | `src/gates/quality_governance.py` | Phase 4 |
| SLA Alerting Service | `src/monitoring/sla_alerting.py` | Phase 6 |
| Comprehend Adapter (PII) | `src/adapters/comprehend.py` | Phase 4 |
| ServiceNow Adapter | `src/adapters/servicenow.py` | Phase 4 |
| Ticket Ops Service | `src/services/ticket_ops.py` | Phase 4 |
| LLM Factory | `src/llm/factory.py` | **Built** — multi-provider fallback (Bedrock → OpenAI) |
| LLM Utils (RAG chunking) | `src/llm/utils.py` | Phase 4+ |
| LLM Security Helpers | `src/llm/security_helpers.py` | Phase 4+ |
| Short-term Memory (Redis) | `src/memory/short_term.py` | Phase 4+ |
| Long-term Memory (pgvector) | `src/memory/long_term.py` | Phase 4+ |
| Custom Agent Tools | `src/tools/custom_tools.py` | Phase 4+ |
| Evaluation Matrix | `src/evaluation/matrix.py` | Phase 8 |
| LLM-as-Judge Eval | `src/evaluation/eval.py` | Phase 8 |
| Triage Route | `src/api/routes/triage.py` | Phase 5 |
| Admin Route | `src/api/routes/admin.py` | Phase 7 |
| Resolution Prompt | `prompts/resolution/v1.jinja` | Phase 4 |
| Communication Prompts | `prompts/communication_drafting/` | Phase 4 |




