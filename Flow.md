```
================================================================================
     VQMS -- END-TO-END RUNTIME WALKTHROUGH
     Phase 2 Complete | 128 Tests Passing | All Cloud Services Connected
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
  PART 1:  Email Entry Point (Steps E1 - E2) ........... [IMPLEMENTED]
  PART 2:  Portal Entry Point (Steps P1 - P6) .......... [IMPLEMENTED]
  PART 3:  Both Paths Converge (SQS -> AI Pipeline) .... [IMPLEMENTED up to SQS enqueue]
  PART 4:  Query Analysis -- LLM Call #1 (Step 8) ...... [NOT BUILT -- Phase 3]
  PART 5:  Routing + KB Search (Step 9) ................ [NOT BUILT -- Phase 3]
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
  |                       ROUTES REGISTERED                              |
  +=====================================================================+
  |  POST /queries               src/api/routes/queries.py              |
  |  POST /webhooks/ms-graph     src/api/routes/webhooks.py             |
  |  GET  /health                main.py -> health_check()              |
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

## PART 3: BOTH PATHS CONVERGE

Both email and portal paths produce a `UnifiedQueryPayload` on SQS.
The message format is identical regardless of entry point:

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
        | SQS consumer reads this message
        | (NOT YET BUILT — Phase 3)
        v
  [Phase 3: LangGraph Orchestrator consumes from SQS]
```

---

## PART 4: QUERY ANALYSIS -- LLM CALL #1 (Step 8)

```
  +=====================================================+
  | [NOT BUILT -- Phase 3]                              |
  |                                                     |
  | File: src/agents/query_analysis.py                  |
  | Current state: src/agents/__init__.py is empty      |
  |                                                     |
  | What will happen:                                   |
  |  1. LangGraph orchestrator consumes SQS message     |
  |  2. Loads context: vendor profile, episodic memory  |
  |  3. Query Analysis Agent calls Bedrock Claude 3.5   |
  |  4. Produces AnalysisResult:                        |
  |     intent_classification, extracted_entities,       |
  |     urgency_level, sentiment, confidence_score,     |
  |     multi_issue_detected, suggested_category        |
  |  5. Decision: confidence >= 0.85 -> Step 9          |
  |               confidence <  0.85 -> Path C          |
  |                                                     |
  | Pydantic model ready: src/models/workflow.py        |
  |   -> AnalysisResult [IMPLEMENTED]                   |
  | Bedrock adapter: src/adapters/bedrock.py            |
  |   -> [NOT BUILT]                                    |
  | Prompt template: prompts/query_analysis/v1.jinja    |
  |   -> [NOT BUILT]                                    |
  +=====================================================+
```

---

## PART 5: ROUTING + KB SEARCH (Step 9)

```
  +=====================================================+
  | [NOT BUILT -- Phase 3]                              |
  |                                                     |
  | Routing Service:                                    |
  |   File: src/services/routing.py                     |
  |   Current state: file does not exist                |
  |   Pydantic model ready: src/models/ticket.py        |
  |     -> RoutingDecision [IMPLEMENTED]                |
  |                                                     |
  | KB Search Service:                                  |
  |   File: src/services/kb_search.py                   |
  |   Current state: file does not exist                |
  |   pgvector schema ready: migration 003              |
  |     -> memory.embedding_index [SCHEMA BUILT]        |
  |                                                     |
  | What will happen (parallel execution):              |
  |  A. Routing: deterministic rules engine             |
  |     Input: AnalysisResult + VendorMatch             |
  |     Output: RoutingDecision (team, SLA, path)       |
  |  B. KB Search: embed query -> cosine similarity     |
  |     Input: query text                               |
  |     Output: ranked KB article matches               |
  |                                                     |
  | Decision: KB match >= 80% + facts -> Path A         |
  |           Otherwise                -> Path B        |
  +=====================================================+
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
| `main.py` | `health_check()` | GET /health with DB + Redis status |
| `main.py` | `lifespan()` | Startup/shutdown (SSH tunnel, DB, Redis) |

### Services
| File | Function | What it does |
|------|----------|-------------|
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
| `src/services/vendor_resolution.py` | `resolve_vendor()` | 3-step vendor match via real Salesforce custom objects |

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
| `src/cache/redis_client.py` | 7 key builders | idempotency, session, vendor, workflow, sla, dashboard, thread |
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

### Pydantic Models (all in src/models/)
| File | Models |
|------|--------|
| `email.py` | EmailAttachment, EmailMessage, ParsedEmailPayload |
| `query.py` | QuerySubmission, UnifiedQueryPayload |
| `vendor.py` | VendorTier (enum), VendorMatch, VendorProfile |
| `workflow.py` | Status, UrgencyLevel, Sentiment, QuerySource, QueryType, Priority (enums), AnalysisResult, WorkflowState, CaseExecution |
| `ticket.py` | TicketRecord, TicketLink, RoutingDecision |
| `communication.py` | DraftResponse, DraftEmailPackage, ValidationReport |
| `memory.py` | EpisodicMemory, VendorProfileCache, EmbeddingRecord |
| `budget.py` | Budget (with is_within_budget, remaining_* properties) |
| `triage.py` | ReviewStatus, TriagePackage |
| `messages.py` | ToolCall, AgentMessage |

### Scripts
| File | What it does |
|------|-------------|
| `scripts/run_email_intake.py` | Run full email pipeline against real cloud services |
| `scripts/run_migrations.py` | Execute SQL migrations on RDS via SSH tunnel |
| `scripts/check_db.py` | Diagnose PostgreSQL connectivity, list DBs/tables |
| `scripts/check_aws.py` | Check S3, SQS, EventBridge connectivity |
| `scripts/check_graph_api.py` | Check Graph API auth, mailbox, permissions |
| `tests/manual/test_salesforce_connection.py` | Test Salesforce connection, query Contacts/Accounts |

### Tests (128 passing)
| File | Tests | What they cover |
|------|-------|----------------|
| `tests/unit/test_models.py` | ~80 | All Pydantic models and enums |
| `tests/unit/test_adapters.py` | ~15 | S3, SQS, EventBridge (moto), Salesforce stub |
| `tests/unit/test_redis_keys.py` | ~15 | All 7 key families, TTLs, prefix |
| `tests/unit/test_correlation.py` | ~10 | UUID format, query ID format, uniqueness |
| `tests/unit/test_email_intake.py` | ~11 | Email pipeline + thread correlation |
| `tests/unit/test_portal_submission.py` | ~7 | Portal pipeline, dedup, graceful Redis |
| `tests/unit/test_db_connection.py` | ~16 | SSH tunnel, engine lifecycle, health |
| `tests/integration/test_email_intake_e2e.py` | ~10 | Full E2E with moto AWS + webhook endpoint |

---

## WHAT IS STUBBED (mock data, not real integration)

No components are currently stubbed. All adapters connect to real services.

---

## WHAT IS NOT BUILT YET

These architecture doc components have zero code (only empty `__init__.py` files or no file at all):

| Component | Target File | Phase |
|-----------|-------------|-------|
| LangGraph Orchestrator | `src/orchestration/graph.py` | Phase 3 |
| Orchestration Router | `src/orchestration/router.py` | Phase 3 |
| Orchestration Manager | `src/orchestration/manager.py` | Phase 3 |
| Step Functions Integration | `src/orchestration/step_functions.py` | Phase 5 |
| Query Analysis Agent | `src/agents/query_analysis.py` | Phase 3 |
| Resolution Agent | `src/agents/resolution.py` | Phase 4 |
| Communication Drafting Agent | `src/agents/communication_drafting.py` | Phase 4 |
| Orchestration Agent | `src/agents/orchestration.py` | Phase 3 |
| Base Agent Class | `src/agents/abc_agent.py` | Phase 3 |
| Quality & Governance Gate | `src/gates/quality_governance.py` | Phase 4 |
| SLA Alerting Service | `src/monitoring/sla_alerting.py` | Phase 6 |
| Bedrock Adapter (LLM) | `src/adapters/bedrock.py` | Phase 3 |
| Comprehend Adapter (PII) | `src/adapters/comprehend.py` | Phase 4 |
| ServiceNow Adapter | `src/adapters/servicenow.py` | Phase 4 |
| Vendor Resolution Service | `src/services/vendor_resolution.py` | Phase 2 (IMPLEMENTED — real Salesforce) |
| Ticket Ops Service | `src/services/ticket_ops.py` | Phase 4 |
| Routing Service | `src/services/routing.py` | Phase 3 |
| KB Search Service | `src/services/kb_search.py` | Phase 3 |
| Memory Context Service | `src/services/memory_context.py` | Phase 3 |
| LLM Factory | `src/llm/factory.py` | Phase 3 |
| LLM Utils (RAG chunking) | `src/llm/utils.py` | Phase 3 |
| LLM Security Helpers | `src/llm/security_helpers.py` | Phase 3 |
| Short-term Memory (Redis) | `src/memory/short_term.py` | Phase 3 |
| Long-term Memory (pgvector) | `src/memory/long_term.py` | Phase 3 |
| Custom Agent Tools | `src/tools/custom_tools.py` | Phase 3 |
| Evaluation Matrix | `src/evaluation/matrix.py` | Phase 8 |
| LLM-as-Judge Eval | `src/evaluation/eval.py` | Phase 8 |
| Dashboard Route | `src/api/routes/dashboard.py` | IMPLEMENTED — GET /dashboard/kpis, GET /queries, GET /queries/{id} |
| Auth Route | `src/api/routes/auth.py` | IMPLEMENTED — fake POST /auth/login for dev |
| Triage Route | `src/api/routes/triage.py` | Phase 5 |
| Admin Route | `src/api/routes/admin.py` | Phase 7 |
| Prompt Templates | `prompts/` directory | Phase 3 |
| Frontend Portal (Angular) | `frontend/` directory | IMPLEMENTED — full P1-P6 wizard flow, zero styling |
