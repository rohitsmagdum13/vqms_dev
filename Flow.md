```
================================================================================
     VQMS -- END-TO-END RUNTIME WALKTHROUGH
     Phase 2 Complete | 128 Tests Passing | All Cloud Services Connected
================================================================================
```

**Reference Scenario (traced through every step):**
Rajesh Mehta from TechNova Solutions (GOLD tier, SF-001) emails about Invoice #INV-2026-0451.

---

## TABLE OF CONTENTS

```
  PART 0:  Application Startup .......................... [BUILT]
  PART 1:  Email Entry Point (Steps E1-E2) .............. [BUILT]
  PART 2:  Portal Entry Point (Steps P1-P6) ............. [BUILT]
  PART 3:  Both Paths Converge (SQS -> AI Pipeline) ..... [BUILT]
  PART 4:  Query Analysis Agent (Step 8) ................ [Phase 3]
  PART 5:  Routing + KB Search (Step 9) ................. [Phase 3]
  PART 6:  Path A -- AI-Resolved (Steps 10A-12A) ........ [Phase 4]
  PART 7:  Path B -- Human-Team-Resolved (Steps 10B-15) . [Phase 4]
  PART 8:  Path C -- Low-Confidence Review (Steps 8C) ... [Phase 5]
  PART 9:  SLA Monitoring (Step 13) ..................... [Phase 6]
  PART 10: Closure and Reopen (Steps 14-16) ............. [Phase 6]
  ---      Adapters Summary
  ---      Data Models & Schemas
  ---      Test Coverage
  ---      Build Status
```

---

## PART 0: APPLICATION STARTUP

```
  File: main.py -> lifespan()

  +=====================================================================+
  |                        STARTUP SEQUENCE                              |
  +=====================================================================+
  |                                                                      |
  |  Step 1: Configure Logging                                           |
  |  +----------------------------------------------------------------+  |
  |  | src/utils/logger.py -> setup_logging()                         |  |
  |  | Structured JSON logging at configured level (DEBUG/INFO/etc)   |  |
  |  +----------------------------------------------------------------+  |
  |                           |                                          |
  |                           v                                          |
  |  Step 2: SSH Tunnel (if SSH_HOST is set in .env)                     |
  |  +----------------------------------------------------------------+  |
  |  | src/db/connection.py -> start_ssh_tunnel()                     |  |
  |  |                                                                |  |
  |  | INPUT:  SSH_HOST, SSH_PORT, SSH_USERNAME, SSH_PRIVATE_KEY_PATH  |  |
  |  |         RDS_HOST, RDS_PORT                                     |  |
  |  |                                                                |  |
  |  | DOES:   local machine ---SSH---> bastion host ---TCP---> RDS   |  |
  |  |         Opens a local port that forwards to RDS:5432           |  |
  |  |                                                                |  |
  |  | OUTPUT: (local_host, local_port) -- tunnel's bind address      |  |
  |  |         Rebuilds database_url -> localhost:{local_port}        |  |
  |  +----------------------------------------------------------------+  |
  |                           |                                          |
  |                           v                                          |
  |  Step 3: PostgreSQL Connection                                       |
  |  +----------------------------------------------------------------+  |
  |  | src/db/connection.py -> init_db()                              |  |
  |  |                                                                |  |
  |  | INPUT:  database_url, pool_min=5, pool_max=20                  |  |
  |  | DOES:   Creates async SQLAlchemy engine with asyncpg driver    |  |
  |  |         Connects through the SSH tunnel                        |  |
  |  | OUTPUT: Engine singleton stored in module-level _engine        |  |
  |  +----------------------------------------------------------------+  |
  |                           |                                          |
  |                           v                                          |
  |  Step 4: Redis Connection                                            |
  |  +----------------------------------------------------------------+  |
  |  | src/cache/redis_client.py -> init_redis()                      |  |
  |  |                                                                |  |
  |  | INPUT:  host, port, password, db, ssl                          |  |
  |  | DOES:   Creates async Redis client + PING to verify            |  |
  |  | OUTPUT: Client singleton stored in module-level _redis_client  |  |
  |  +----------------------------------------------------------------+  |
  |                                                                      |
  |  NOTE: Each step is try/except. If any fails, app still starts.      |
  |        Health check reports "disconnected" for failed services.      |
  +======================================================================+

  +=====================================================================+
  |                       SHUTDOWN SEQUENCE                              |
  +=====================================================================+
  |  1. close_db()        -- disposes SQLAlchemy engine                  |
  |  2. stop_ssh_tunnel() -- closes SSH tunnel                          |
  |  3. close_redis()     -- closes Redis connection                    |
  +=====================================================================+

  +=====================================================================+
  |                       ROUTES REGISTERED                              |
  +=====================================================================+
  |  GET  /health            -->  main.py (health check)                 |
  |  POST /queries           -->  src/api/routes/queries.py              |
  |  POST /webhooks/ms-graph -->  src/api/routes/webhooks.py             |
  +=====================================================================+
```

---

## PART 1: EMAIL ENTRY POINT (Steps E1-E2)

A vendor sends an email to the shared mailbox. Microsoft Graph detects it and sends a webhook notification to VQMS.

### STEP E2.1: WEBHOOK RECEIVES NOTIFICATION

```
  +---------------------+       +------------------------+       +---------------------------+
  |  Microsoft Graph     |       |  POST /webhooks/       |       |  process_email_           |
  |  (sends webhook      | ----> |       ms-graph         | ----> |       notification()      |
  |   notification)      |       |  webhooks.py           |       |  email_intake.py          |
  +---------------------+       +------------------------+       +---------------------------+
```

```
  File: src/api/routes/webhooks.py -> handle_graph_notification()

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  HTTP POST with JSON body:                                                 |
  |  {                                                                         |
  |    "value": [{                                                             |
  |      "resource": "Users/rohit@vqms13.onmicrosoft.com/Messages/AAMkAD...",  |
  |      "changeType": "created"                                               |
  |    }]                                                                      |
  |  }                                                                         |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |  1. If validationToken param exists:                                        |
  |     --> Return the token as plain text (Graph subscription validation)      |
  |                                                                            |
  |  2. If value[] array exists:                                                |
  |     --> Loop through each notification                                      |
  |     --> Call process_email_notification(resource=notification.resource)      |
  |     --> Catch DuplicateQueryError per item (log it, don't fail batch)       |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT                                                                    |
  +---------------------------------------------------------------------------+
  |  HTTP 202:  {"status": "accepted", "processed": N, "results": [...]}       |
  |  HTTP 409:  If ALL notifications are duplicates                             |
  |  HTTP 400:  If payload is missing or malformed                              |
  +---------------------------------------------------------------------------+
```

---

### STEPS E2.2 - E2.11: EMAIL INTAKE PIPELINE (11 Steps)

```
  File: src/services/email_intake.py -> process_email_notification(resource, correlation_id=None)
```

---

#### STEP 1: GENERATE CORRELATION ID

```
  +-----------------------------------------------------------------------+
  |  File: src/utils/correlation.py -> generate_correlation_id()           |
  +-----------------------------------------------------------------------+
  |  INPUT:   (none)                                                       |
  |  DOES:    Generates a UUID4 string                                     |
  |  OUTPUT:  "7c9e6679-7425-40de-944b-e07fc1f90ae7"                       |
  |                                                                        |
  |  This ID follows the query through EVERY service, log entry,           |
  |  database write, and API call for the rest of its lifecycle.           |
  +-----------------------------------------------------------------------+
```

---

#### STEP 2: FETCH EMAIL FROM EXCHANGE ONLINE

```
  +----------------------------+       +----------------------------+
  |  fetch_email_by_resource() |       |  Microsoft Graph API       |
  |  graph_api.py              | ----> |  GET /users/{mailbox}/     |
  |                            |       |      messages/{id}         |
  +----------------------------+       +----------------------------+
```

```
  File: src/adapters/graph_api.py -> fetch_email_by_resource(resource, correlation_id=...)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  resource = "Users/rohit@vqms13.onmicrosoft.com/Messages/AAMkAD..."        |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  1. ACQUIRE TOKEN                                                          |
  |     +------------------------------------------------------------------+   |
  |     | MSAL ConfidentialClientApplication                               |   |
  |     | Authority: https://login.microsoftonline.com/{TENANT_ID}         |   |
  |     | Scope:     https://graph.microsoft.com/.default                  |   |
  |     | Creds:     GRAPH_API_CLIENT_ID + GRAPH_API_CLIENT_SECRET         |   |
  |     | Caching:   Token cached with 5-minute expiry buffer              |   |
  |     +------------------------------------------------------------------+   |
  |                                                                            |
  |  2. BUILD URL                                                              |
  |     https://graph.microsoft.com/v1.0/{resource}                            |
  |                                                                            |
  |  3. HTTP GET via httpx (30-second timeout)                                 |
  |                                                                            |
  |  4. PARSE RESPONSE into EmailMessage Pydantic model:                       |
  |     +------------------------------------------------------------------+   |
  |     | Field           | Source in Graph API Response                   |   |
  |     +-----------------+------------------------------------------------+   |
  |     | message_id      | internetMessageId (fallback: id)               |   |
  |     | conversation_id | conversationId                                 |   |
  |     | in_reply_to     | internetMessageHeaders -> In-Reply-To          |   |
  |     | references      | internetMessageHeaders -> References (split)   |   |
  |     | sender_email    | from.emailAddress.address                      |   |
  |     | sender_name     | from.emailAddress.name                         |   |
  |     | body_text       | body.content (HTML stripped if html type)       |   |
  |     | received_at     | receivedDateTime (ISO parsed)                  |   |
  |     +------------------------------------------------------------------+   |
  |                                                                            |
  |  5. If hasAttachments=true, fetch attachment metadata (not content)         |
  |                                                                            |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT (for Rajesh scenario)                                              |
  +---------------------------------------------------------------------------+
  |  EmailMessage:                                                             |
  |    message_id:    "<AAMkAD...@technova.com>"                               |
  |    sender_email:  "rajesh.mehta@technova.com"                              |
  |    sender_name:   "Rajesh Mehta"                                           |
  |    subject:       "Invoice #INV-2026-0451 -- Payment Status Query"         |
  |    body_text:     "Dear Support Team, I am writing to inquire about..."    |
  |    attachments:   [{"filename": "INV-2026-0451.pdf", "size": 245760}]      |
  +---------------------------------------------------------------------------+
```

---

#### STEP 3: IDEMPOTENCY CHECK (REDIS)

```
  +----------------------------+       +----------------------------+
  |  _check_email_idempotency()|       |  Redis                     |
  |  email_intake.py           | ----> |  GET/SET vqms:idempotency: |
  |                            |       |      email:<message_id>    |
  +----------------------------+       +----------------------------+
```

```
  File: src/services/email_intake.py -> _check_email_idempotency(message_id)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  message_id = "<AAMkAD...@technova.com>"                                   |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  1. Build key:  idempotency_key(f"email:{message_id}")                     |
  |     Returns:    ("vqms:idempotency:email:<AAMkAD...>", 604800)             |
  |                  ^--- key                                ^--- 7-day TTL    |
  |                                                                            |
  |  2. GET key from Redis:                                                    |
  |     +------------------------------------------------------------------+   |
  |     |  Key EXISTS?   --> DuplicateQueryError (email already processed)  |   |
  |     |  Key MISSING?  --> SET key="1" with 7-day TTL (mark processed)   |   |
  |     |  Redis DOWN?   --> Log warning, continue (don't block intake)    |   |
  |     +------------------------------------------------------------------+   |
  |                                                                            |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT (for Rajesh scenario)                                              |
  +---------------------------------------------------------------------------+
  |  Key did not exist. Set "vqms:idempotency:email:<AAMkAD...>" = "1"         |
  |  TTL = 604800 seconds (7 days). Continues to next step.                    |
  +---------------------------------------------------------------------------+
```

---

#### STEP 4: VENDOR RESOLUTION (SALESFORCE STUB)

```
  +----------------------------+       +----------------------------+
  |  resolve_vendor()          |       |  Salesforce CRM (STUB)     |
  |  salesforce.py             | ----> |  3-step fallback match     |
  +----------------------------+       +----------------------------+
```

```
  File: src/adapters/salesforce.py -> resolve_vendor(sender_email, sender_name, body_text)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  sender_email = "rajesh.mehta@technova.com"                                |
  |  sender_name  = "Rajesh Mehta"                                             |
  |  body_text    = "Dear Support Team... Vendor ID: SF-001..."                |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES (3-step fallback chain)                                      |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  STEP 1: EMAIL_EXACT (confidence: 0.95)                                    |
  |  +------------------------------------------------------------------+      |
  |  | Check sender_email against known Salesforce contact emails       |      |
  |  | "rajesh.mehta@technova.com" matches TechNova's contact list      |      |
  |  | --> MATCH FOUND. Return immediately.                             |      |
  |  +------------------------------------------------------------------+      |
  |                                                                            |
  |  STEP 2: VENDOR_ID_BODY (confidence: 0.90) -- only if Step 1 fails        |
  |  +------------------------------------------------------------------+      |
  |  | Regex search for "SF-001" or "VN-30892" patterns in body text    |      |
  |  +------------------------------------------------------------------+      |
  |                                                                            |
  |  STEP 3: NAME_SIMILARITY (confidence: 0.60) -- only if Step 2 fails       |
  |  +------------------------------------------------------------------+      |
  |  | Case-insensitive substring match of sender name vs vendor names  |      |
  |  +------------------------------------------------------------------+      |
  |                                                                            |
  |  ALL FAIL --> return None (vendor is UNRESOLVED)                            |
  |                                                                            |
  |  MOCK VENDOR DATA:                                                         |
  |  +--------+------------------------+-----------+------------------------+  |
  |  | ID     | Name                   | Tier      | Contact Emails         |  |
  |  +--------+------------------------+-----------+------------------------+  |
  |  | SF-001 | TechNova Solutions     | GOLD      | rajesh.mehta@technova, |  |
  |  |        |                        |           | support@technova       |  |
  |  | SF-002 | Acme Corporation       | STANDARD  | john@acme-corp,        |  |
  |  |        |                        |           | billing@acme-corp      |  |
  |  | SF-003 | Platinum Partner Inc   | PLATINUM  | admin@platinumpartner  |  |
  |  +--------+------------------------+-----------+------------------------+  |
  |                                                                            |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT (for Rajesh scenario)                                              |
  +---------------------------------------------------------------------------+
  |  VendorMatch:                                                              |
  |    vendor_id:        "SF-001"                                              |
  |    vendor_name:      "TechNova Solutions"                                  |
  |    vendor_tier:      GOLD                                                  |
  |    match_method:     "EMAIL_EXACT"                                         |
  |    match_confidence: 0.95                                                  |
  |    risk_flags:       []                                                    |
  +---------------------------------------------------------------------------+
```

---

#### STEP 5: THREAD CORRELATION

```
  File: src/services/email_intake.py -> _determine_thread_status(email)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  email.in_reply_to     = None                                              |
  |  email.references      = []                                                |
  |  email.conversation_id = "conv-technova-inv-0451"                          |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES (decision tree)                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  in_reply_to OR references present?                                        |
  |     YES --> "EXISTING_OPEN" (reply to ongoing conversation)                |
  |     NO  --> conversation_id present but no reply headers?                  |
  |               YES --> "NEW" (Exchange grouped it, but first message)        |
  |               NO  --> "NEW" (brand new query)                               |
  |                                                                            |
  |  NOTE: REPLY_TO_CLOSED detection requires ServiceNow lookup.               |
  |        Deferred to Phase 6.                                                 |
  |                                                                            |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT (for Rajesh scenario)                                              |
  +---------------------------------------------------------------------------+
  |  thread_status = "NEW"                                                     |
  +---------------------------------------------------------------------------+
```

---

#### STEP 6: STORE RAW EMAIL IN S3

```
  +----------------------------+       +----------------------------+
  |  upload_file()             |       |  AWS S3                    |
  |  s3_client.py              | ----> |  PUT to bucket             |
  +----------------------------+       +----------------------------+
```

```
  File: src/storage/s3_client.py -> upload_file(bucket, key, content)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  bucket  = "vqms-email-raw-prod"                                           |
  |  key     = "emails/<AAMkAD...>.json"                                       |
  |  content = JSON bytes (~800 bytes) of full email data:                     |
  |            message_id, conversation_id, in_reply_to, references,           |
  |            sender, subject, body, attachments                              |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |  1. _serialize_email_for_storage(email) --> JSON dict --> UTF-8 bytes       |
  |  2. boto3 client.put_object(Bucket, Key, Body) -- lazy-init client         |
  |  3. Returns S3 URI string                                                  |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT                                                                    |
  +---------------------------------------------------------------------------+
  |  "s3://vqms-email-raw-prod/emails/<AAMkAD...>.json"                        |
  +---------------------------------------------------------------------------+
```

---

#### STEP 7: GENERATE TRACKING IDS

```
  File: src/utils/correlation.py

  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  +-----------------+----------------------------+------------------------+ |
  |  | ID              | Function                   | Format / Example       | |
  |  +-----------------+----------------------------+------------------------+ |
  |  | execution_id    | generate_execution_id()    | UUID4                  | |
  |  |                 |                            | "550e8400-e29b-..."    | |
  |  +-----------------+----------------------------+------------------------+ |
  |  | query_id        | generate_query_id()        | VQ-YYYY-NNNN           | |
  |  |                 |                            | "VQ-2026-0451"         | |
  |  +-----------------+----------------------------+------------------------+ |
  |  | correlation_id  | (already from Step 1)      | UUID4                  | |
  |  |                 |                            | "7c9e6679-7425-..."    | |
  |  +-----------------+----------------------------+------------------------+ |
  |                                                                            |
  |  NOTE: In production, query_id sequence comes from DB.                     |
  |        In dev, uses random.randint(0, 9999).                               |
  +---------------------------------------------------------------------------+
```

---

#### STEP 8: BUILD UNIFIED QUERY PAYLOAD

```
  File: src/models/query.py -> UnifiedQueryPayload

  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |  Builds the CONVERGED PAYLOAD that both email and portal paths produce.    |
  |  The AI pipeline consumes this identical structure regardless of entry.    |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT (for Rajesh scenario)                                              |
  +---------------------------------------------------------------------------+
  |  UnifiedQueryPayload:                                                      |
  |    query_id         = "VQ-2026-0451"                                       |
  |    execution_id     = "550e8400-..."                                       |
  |    correlation_id   = "7c9e6679-..."                                       |
  |    source           = EMAIL                                                |
  |    vendor_id        = "SF-001"                                             |
  |    vendor_name      = "TechNova Solutions"                                 |
  |    subject          = "Invoice #INV-2026-0451 -- Payment Status Query"     |
  |    description      = "Dear Support Team, I am writing to inquire..."      |
  |    query_type       = None           <-- Phase 3 agent extracts this       |
  |    priority         = None           <-- Routing service sets this         |
  |    reference_number = None           <-- Phase 3 agent extracts this       |
  |    thread_status    = "NEW"                                                |
  |    message_id       = "<AAMkAD...@technova.com>"                           |
  |    received_at      = "2026-04-06T10:30:00+00:00"                          |
  +---------------------------------------------------------------------------+
```

---

#### STEP 9: SAVE CASE EXECUTION TO POSTGRESQL (via SSH Tunnel to RDS)

```
  +----------------------------+       +----------------------------+
  |  _store_case_execution()   |       |  PostgreSQL (RDS)          |
  |  email_intake.py           | ----> |  workflow.case_execution   |
  +----------------------------+       |  (via SSH tunnel)          |
                                       +----------------------------+
```

```
  File: src/services/email_intake.py -> _store_case_execution(...)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  execution_id   = "550e8400-..."                                           |
  |  query_id       = "VQ-2026-0451"                                           |
  |  correlation_id = "7c9e6679-..."                                           |
  |  status         = NEW                                                      |
  |  source         = EMAIL                                                    |
  |  vendor_id      = "SF-001"                                                 |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  1. Validate: Build CaseExecution Pydantic model (catches bad data early)  |
  |                                                                            |
  |  2. Get engine: src/db/connection.py -> get_engine()                       |
  |     If engine is None (DB unavailable) -> log warning, skip, continue.     |
  |     Pipeline is NOT blocked by DB failure.                                  |
  |                                                                            |
  |  3. INSERT into workflow.case_execution:                                   |
  |     +------------------------------------------------------------------+   |
  |     | INSERT INTO workflow.case_execution                              |   |
  |     |   (execution_id, query_id, correlation_id, status,              |   |
  |     |    source, vendor_id, created_at, updated_at)                    |   |
  |     | VALUES (...)                                                     |   |
  |     | ON CONFLICT (execution_id) DO NOTHING   <-- idempotent           |   |
  |     +------------------------------------------------------------------+   |
  |                                                                            |
  |     Connection path:                                                       |
  |       app --> SSH tunnel (local port) --> bastion host --> RDS:5432         |
  |                                                                            |
  |  4. On failure: Log warning, continue. Query still gets queued to SQS.     |
  |                                                                            |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT                                                                    |
  +---------------------------------------------------------------------------+
  |  Row inserted into workflow.case_execution:                                |
  |    execution_id   = "550e8400-..."                                         |
  |    query_id       = "VQ-2026-0451"                                         |
  |    correlation_id = "7c9e6679-..."                                         |
  |    status         = "new"                                                  |
  |    source         = "email"                                                |
  |    vendor_id      = "SF-001"                                               |
  |    created_at     = 2026-04-06T10:30:00+00:00                              |
  |                                                                            |
  |  If DB is unavailable: No row inserted, but pipeline continues.            |
  +---------------------------------------------------------------------------+
```

---

#### STEP 10: PUBLISH EMAIL-INGESTED EVENT (EVENTBRIDGE)

```
  +----------------------------+       +----------------------------+
  |  publish_event()           |       |  AWS EventBridge           |
  |  eventbridge.py            | ----> |  vqms-event-bus            |
  +----------------------------+       +----------------------------+
```

```
  File: src/events/eventbridge.py -> publish_event(detail_type, detail, correlation_id)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  detail_type = "EmailIngested"                                             |
  |  detail = {query_id, execution_id, source, vendor_id, message_id, ...}     |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |  1. Enriches detail with correlation_id and timestamp                      |
  |  2. Calls put_events() with:                                               |
  |     - Source:       "com.vqms"                                             |
  |     - DetailType:   "EmailIngested"                                        |
  |     - EventBusName: "vqms-event-bus"                                       |
  |  3. Checks FailedEntryCount for partial failures                           |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT                                                                    |
  +---------------------------------------------------------------------------+
  |  Event payload published:                                                  |
  |  {                                                                         |
  |    "query_id":       "VQ-2026-0451",                                       |
  |    "execution_id":   "550e8400-...",                                       |
  |    "source":         "EMAIL",                                              |
  |    "vendor_id":      "SF-001",                                             |
  |    "message_id":     "<AAMkAD...>",                                        |
  |    "subject":        "Invoice #INV-2026-0451 -- Payment Status Query",     |
  |    "thread_status":  "NEW",                                                |
  |    "sender_email":   "rajesh.mehta@technova.com",                          |
  |    "correlation_id": "7c9e6679-...",                                       |
  |    "time":           "2026-04-06T10:30:01.123456+00:00"                    |
  |  }                                                                         |
  |                                                                            |
  |  Returns: EventBridge event ID                                             |
  +---------------------------------------------------------------------------+
```

---

#### STEP 11: ENQUEUE TO SQS

```
  +----------------------------+       +----------------------------+
  |  publish()                 |       |  AWS SQS                   |
  |  sqs.py                    | ----> |  vqms-email-intake-queue   |
  +----------------------------+       +----------------------------+
```

```
  File: src/queues/sqs.py -> publish(queue_name, message, correlation_id)

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  queue_name     = "vqms-email-intake-queue"                                |
  |  message        = UnifiedQueryPayload dict (~500 chars JSON)               |
  |  correlation_id = "7c9e6679-..."                                           |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES                                                              |
  +---------------------------------------------------------------------------+
  |  1. Resolves queue name to URL via get_queue_url() (cached)                |
  |  2. Serializes payload dict to JSON string                                 |
  |  3. Sends message with correlation_id as SQS MessageAttribute              |
  |  4. Returns SQS MessageId                                                  |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT                                                                    |
  +---------------------------------------------------------------------------+
  |  SQS MessageId (UUID)                                                      |
  |  Message is now sitting in vqms-email-intake-queue waiting for Phase 3     |
  +---------------------------------------------------------------------------+
```

---

### EMAIL PIPELINE -- FINAL RESULT

```
  +---------------------------------------------------------------------------+
  |  RETURN VALUE from process_email_notification()                            |
  +---------------------------------------------------------------------------+
  |  {                                                                         |
  |    "query_id":       "VQ-2026-0451",                                       |
  |    "execution_id":   "550e8400-...",                                       |
  |    "correlation_id": "7c9e6679-...",                                       |
  |    "vendor_id":      "SF-001",                                             |
  |    "thread_status":  "NEW",                                                |
  |    "status":         "accepted"                                            |
  |  }                                                                         |
  +---------------------------------------------------------------------------+

  +---------------------------------------------------------------------------+
  |  WHERE DATA LANDED                                                         |
  +---------------------------------------------------------------------------+
  |  Redis:        vqms:idempotency:email:<AAMkAD...> = "1" (7-day TTL)        |
  |  S3:           s3://vqms-email-raw-prod/emails/<AAMkAD...>.json            |
  |  PostgreSQL:   workflow.case_execution row (via SSH tunnel to RDS)          |
  |  EventBridge:  "EmailIngested" event on vqms-event-bus                     |
  |  SQS:          UnifiedQueryPayload on vqms-email-intake-queue              |
  +---------------------------------------------------------------------------+
```

---

## PART 2: PORTAL ENTRY POINT (Steps P1-P6)

A vendor logs into the VQMS portal, fills out a query form, and clicks Submit.

```
  +-------------------+       +-------------------+       +------------------------+
  |  Vendor Portal    |       |  POST /queries    |       |  submit_portal_query() |
  |  (React, Phase 7) | ----> |  queries.py       | ----> |  portal_submission.py  |
  +-------------------+       +-------------------+       +------------------------+
```

### STEP P6: POST /queries

```
  File: src/api/routes/queries.py -> create_query()

  +---------------------------------------------------------------------------+
  |  INPUT                                                                     |
  +---------------------------------------------------------------------------+
  |  Headers:                                                                  |
  |    X-Vendor-ID:   SF-001           <-- REQUIRED (JWT in prod, header dev)  |
  |    X-Vendor-Name: TechNova Solutions    <-- optional                       |
  |    X-Correlation-ID: <optional>                                            |
  |                                                                            |
  |  Body (validated as QuerySubmission):                                      |
  |  {                                                                         |
  |    "query_type": "billing",                                                |
  |    "subject": "Invoice Payment Status",                                    |
  |    "description": "When will Invoice #INV-2026-0451 be paid?",             |
  |    "priority": "high",                                                     |
  |    "reference_number": "INV-2026-0451"                                     |
  |  }                                                                         |
  |                                                                            |
  |  SECURITY: vendor_id ALWAYS from header/JWT. NEVER from request body.      |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  WHAT IT DOES (7-step pipeline)                                            |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  Step 1: Generate IDs                                                      |
  |    correlation_id = UUID4, execution_id = UUID4, query_id = VQ-YYYY-NNNN   |
  |                                                                            |
  |  Step 2: Idempotency check (Redis)                                         |
  |    Key: vqms:idempotency:portal:{vendor_id}:{subject} (7-day TTL)          |
  |    Prevents double-click submissions.                                      |
  |                                                                            |
  |  Step 3: Build UnifiedQueryPayload                                         |
  |    source=PORTAL, query_type from form, priority from form,                |
  |    thread_status="NEW" (portal queries are always NEW)                     |
  |                                                                            |
  |  Step 4: Save CaseExecution to PostgreSQL (via SSH tunnel to RDS)          |
  |    INSERT INTO workflow.case_execution (...) ON CONFLICT DO NOTHING        |
  |    Graceful: if DB unavailable, query still gets queued to SQS.            |
  |                                                                            |
  |  Step 5: Publish "QueryReceived" event (EventBridge)                       |
  |                                                                            |
  |  Step 6: Enqueue to vqms-query-intake-queue (SQS)                          |
  |                                                                            |
  |  Step 7: Return response                                                   |
  |                                                                            |
  +---------------------------------------------------------------------------+
                                    |
                                    v
  +---------------------------------------------------------------------------+
  |  OUTPUT                                                                    |
  +---------------------------------------------------------------------------+
  |  HTTP 201:                                                                 |
  |  {                                                                         |
  |    "query_id":       "VQ-2026-0452",                                       |
  |    "execution_id":   "...",                                                |
  |    "correlation_id": "...",                                                |
  |    "status":         "accepted"                                            |
  |  }                                                                         |
  |                                                                            |
  |  HTTP 401:  Missing X-Vendor-ID header                                     |
  |  HTTP 409:  Duplicate query detected                                       |
  |  HTTP 422:  Pydantic validation error                                      |
  +---------------------------------------------------------------------------+
```

### EMAIL vs PORTAL -- KEY DIFFERENCES

```
  +-----------------------+-----------------------------+------------------------+
  | Aspect                | EMAIL PATH                  | PORTAL PATH            |
  +-----------------------+-----------------------------+------------------------+
  | Source field           | QuerySource.EMAIL           | QuerySource.PORTAL     |
  | query_type            | None (agent extracts)       | From form ("billing")  |
  | priority              | None (routing sets)         | From form ("high")     |
  | reference_number      | None (agent extracts)       | From form ("INV-...")  |
  | message_id            | Graph API message ID        | None                   |
  | Thread status          | NEW or EXISTING_OPEN       | Always NEW             |
  | Vendor resolution      | Salesforce 3-step fallback | Already known (JWT)    |
  | SQS queue              | vqms-email-intake-queue    | vqms-query-intake-queue|
  | EventBridge event      | EmailIngested              | QueryReceived          |
  | Raw S3 storage         | Yes (compliance)           | No                     |
  +-----------------------+-----------------------------+------------------------+
```

---

## PART 3: BOTH PATHS CONVERGE -- SQS TO AI PIPELINE

```
  +-----------------------------+
  | vqms-email-intake-queue     |----+
  +-----------------------------+    |    +-------------------------------+
                                     +--> | UnifiedQueryPayload           |
  +-----------------------------+    |    | (same Pydantic model,         |
  | vqms-query-intake-queue     |----+    |  different "source" field)    |
  +-----------------------------+         +-------------------------------+
                                                       |
                                                       | Phase 3: SQS consumer
                                                       |          picks up message
                                                       v
                                          +-------------------------------+
                                          | LangGraph Orchestrator        |
                                          | src/orchestration/graph.py    |
                                          | [NOT YET BUILT]               |
                                          +-------------------------------+
```

Both queues contain `UnifiedQueryPayload` messages with **identical structure**.
The AI pipeline (Phase 3+) will consume from both and process through the same LangGraph graph.

---

## PART 4: QUERY ANALYSIS AGENT (Step 8) -- [NOT YET BUILT, Phase 3]

```
  +----------------------------+       +----------------------------+
  |  LangGraph Orchestrator    |       |  Query Analysis Agent      |
  |  Step 7: Load context      | ----> |  src/agents/query_analysis |
  |  (vendor profile, memory)  |       |  LLM Call #1 (Bedrock)     |
  +----------------------------+       +----------------------------+
                                                  |
                                         +--------+--------+
                                         |                 |
                                  confidence >= 0.85  confidence < 0.85
                                         |                 |
                                         v                 v
                                   +-----------+    +-------------+
                                   |  Step 9   |    |   Path C    |
                                   |  Routing  |    |   Human     |
                                   |  + KB     |    |   Review    |
                                   +-----------+    +-------------+
```

```
  +---------------------------------------------------------------------------+
  |  PLANNED (Phase 3)                                                         |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  INPUT:  UnifiedQueryPayload + vendor context + episodic memory            |
  |                                                                            |
  |  DOES:   Amazon Bedrock (Claude Sonnet 3.5, temperature 0.1)               |
  |          - Classify intent (billing, technical, account, etc.)              |
  |          - Extract entities (invoice numbers, dates, amounts, PO#)         |
  |          - Determine urgency level and sentiment                            |
  |          - Produce confidence score (0.0-1.0)                              |
  |                                                                            |
  |  OUTPUT: AnalysisResult (Pydantic model)                                   |
  |                                                                            |
  |  DECISION: confidence >= 0.85 --> Step 9 (Routing + KB)                    |
  |            confidence <  0.85 --> Path C (human review)                     |
  |                                                                            |
  +---------------------------------------------------------------------------+
```

---

## PART 5: ROUTING + KB SEARCH (Step 9) -- [NOT YET BUILT, Phase 3]

```
  +----------------------------+       +----------------------------+
  |  Routing Service           |       |  KB Search Service         |
  |  src/services/routing.py   |       |  src/services/kb_search.py |
  |  Deterministic rules       |       |  Titan Embed v2 -> cosine  |
  +----------------------------+       +----------------------------+
          |                                       |
          v                                       v
    team assignment                      KB match >= 80% ?
    SLA target                           specific facts ?
                                                  |
                                         +--------+--------+
                                         |                 |
                                    YES: Path A       NO: Path B
                                   (AI resolves)  (human team resolves)
```

```
  +---------------------------------------------------------------------------+
  |  PLANNED (Phase 3) -- runs in parallel                                     |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  ROUTING: Deterministic rules based on confidence, urgency,                |
  |           vendor tier, existing tickets.                                    |
  |                                                                            |
  |  KB SEARCH: Embeds query via Titan Embed v2 (1536 dimensions),             |
  |             cosine similarity against KB articles in S3.                    |
  |                                                                            |
  |  DECISION: KB match >= 80% + specific facts                                |
  |            + Resolution Agent confidence >= 0.85                            |
  |            --> Path A (AI drafts full resolution)                           |
  |            OTHERWISE --> Path B (AI drafts acknowledgment only)             |
  |                                                                            |
  +---------------------------------------------------------------------------+
```

---

## PART 6: PATH A -- AI-RESOLVED (Steps 10A-12A) -- [NOT YET BUILT, Phase 4]

```
  +---------------------+       +---------------------+       +---------------------+
  |  Resolution Agent   |       |  Quality Gate       |       |  Ticket + Email     |
  |  LLM Call #2        | ----> |  7-check validation | ----> |  ServiceNow +       |
  |  Full answer from KB|       |  PII scan           |       |  Graph API send     |
  +---------------------+       +---------------------+       +---------------------+
```

```
  +---------------------------------------------------------------------------+
  |  PLANNED FLOW (for Rajesh scenario)                                        |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  Step 1: Resolution Agent drafts email with KB-sourced facts               |
  |          (specific payment dates, amounts, procedures)                     |
  |                                                                            |
  |  Step 2: Quality Gate runs 7 checks:                                       |
  |          [1] Ticket # format   [2] SLA wording   [3] Required sections     |
  |          [4] Restricted terms  [5] Length 50-500w [6] Source citations      |
  |          [7] PII scan (Comprehend)                                         |
  |                                                                            |
  |  Step 3: ServiceNow ticket created (team MONITORS, not investigates)       |
  |                                                                            |
  |  Step 4: Resolution email sent to rajesh.mehta@technova.com                |
  |          via Graph API /sendMail                                            |
  |                                                                            |
  |  EXPECTED: ~11 seconds total, ~$0.033 cost, 2 LLM calls, 0 humans         |
  |                                                                            |
  +---------------------------------------------------------------------------+
```

---

## PART 7: PATH B -- HUMAN-TEAM-RESOLVED (Steps 10B-12B, 14-15) -- [NOT YET BUILT, Phase 4]

```
  PHASE 1: ACKNOWLEDGMENT
  +---------------------+       +---------------------+       +---------------------+
  |  Communication      |       |  Quality Gate       |       |  Ticket + Email     |
  |  Agent              | ----> |  7-check validation | ----> |  ServiceNow +       |
  |  Acknowledgment ONLY|       |                     |       |  Graph API send     |
  +---------------------+       +---------------------+       +---------------------+

                     [Human team investigates via ServiceNow]

  PHASE 2: RESOLUTION (after team findings)
  +---------------------+       +---------------------+       +---------------------+
  |  Communication      |       |  Quality Gate       |       |  Resolution email   |
  |  Agent              | ----> |  validation         | ----> |  to vendor          |
  |  From team notes    |       |                     |       |                     |
  +---------------------+       +---------------------+       +---------------------+
```

```
  +---------------------------------------------------------------------------+
  |  PLANNED FLOW                                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  PHASE 1 (immediate):                                                      |
  |    1. Communication Agent drafts acknowledgment                             |
  |       (NOT resolution -- just "we received it, ticket INC-XXX")            |
  |    2. Quality Gate validates                                                |
  |    3. ServiceNow ticket created (team MUST investigate)                     |
  |    4. Acknowledgment email sent to vendor                                   |
  |                                                                            |
  |  PHASE 2 (after team investigation):                                       |
  |    5. Team marks ticket RESOLVED with resolution notes                      |
  |    6. ResolutionPrepared event triggers Communication Agent                 |
  |    7. Agent drafts resolution email from team's notes                       |
  |    8. Quality Gate validates again                                          |
  |    9. Resolution email sent to vendor                                       |
  |                                                                            |
  +---------------------------------------------------------------------------+
```

---

## PART 8: PATH C -- LOW-CONFIDENCE HUMAN REVIEW (Steps 8C.1-8C.3) -- [NOT YET BUILT, Phase 5]

```
  +---------------------+       +---------------------+       +---------------------+
  |  TriagePackage      |       |  Step Functions     |       |  Human Reviewer     |
  |  created:           | ----> |  PAUSE              | ----> |  Triage Portal      |
  |  - original query   |       |  (callback token)   |       |                     |
  |  - AI analysis      |       |                     |       |  Corrects/approves  |
  |  - confidence       |       |  NOTHING happens    |       +---------------------+
  |    breakdown        |       |  until reviewer acts |               |
  +---------------------+       +---------------------+               v
                                                          +---------------------+
                                                          |  Workflow RESUMES   |
                                                          |  with corrected     |
                                                          |  data --> Step 9    |
                                                          +---------------------+
```

```
  +---------------------------------------------------------------------------+
  |  PLANNED FLOW                                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  1. TriagePackage created (original query + AI analysis + confidence)       |
  |  2. Package queued to vqms-human-review-queue                               |
  |  3. Step Functions pauses via callback token pattern                        |
  |  4. Human reviewer logs in, reviews, corrects classification/vendor         |
  |  5. Reviewer submits --> SendTaskSuccess --> workflow resumes                |
  |  6. Corrected data flows to Step 9 --> Path A or Path B                     |
  |                                                                            |
  |  CRITICAL: SLA clock starts AFTER review completes.                        |
  |            Review time does NOT count against SLA.                          |
  |                                                                            |
  +---------------------------------------------------------------------------+
```

---

## PART 9: SLA MONITORING (Step 13) -- [NOT YET BUILT, Phase 6]

```
  +---------------------------------------------------------------------------+
  |  PLANNED ESCALATION THRESHOLDS                                             |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  +----------+--------------------------+-----------------------------+      |
  |  | SLA %    | Event                    | Action                     |      |
  |  +----------+--------------------------+-----------------------------+      |
  |  |  70%     | SLAWarning70             | Warn the resolver          |      |
  |  |  85%     | SLAEscalation85          | L1 manager escalation      |      |
  |  |  95%     | SLAEscalation95          | L2 senior escalation       |      |
  |  +----------+--------------------------+-----------------------------+      |
  |                                                                            |
  |  SLA TARGETS (vendor tier + urgency):                                      |
  |  +-----------+----------+--------+----------+                              |
  |  | Tier      | CRITICAL | HIGH   | MEDIUM   |                              |
  |  +-----------+----------+--------+----------+                              |
  |  | PLATINUM  | 2 hours  | 4 hrs  | 8 hrs    |                              |
  |  | GOLD      | 4 hours  | 8 hrs  | 16 hrs   |                              |
  |  | STANDARD  | 8 hours  | 16 hrs | 24 hrs   |                              |
  |  +-----------+----------+--------+----------+                              |
  |                                                                            |
  +---------------------------------------------------------------------------+
```

---

## PART 10: CLOSURE AND REOPEN (Steps 14-16) -- [NOT YET BUILT, Phase 6]

```
  +---------------------------------------------------------------------------+
  |  PLANNED FLOW                                                              |
  +---------------------------------------------------------------------------+
  |                                                                            |
  |  +-------+-------------------------------------------+------------------+  |
  |  | #     | Scenario                                  | Action           |  |
  |  +-------+-------------------------------------------+------------------+  |
  |  | 1     | Vendor replies with confirmation           | AI detects       |  |
  |  |       |                                           | closure intent   |  |
  |  |       |                                           | --> ticket closed |  |
  |  +-------+-------------------------------------------+------------------+  |
  |  | 2     | No reply within 5 business days            | Auto-close       |  |
  |  +-------+-------------------------------------------+------------------+  |
  |  | 3     | Vendor reopens                             | Reopen ticket    |  |
  |  |       |                                           | OR create new    |  |
  |  |       |                                           | linked ticket    |  |
  |  +-------+-------------------------------------------+------------------+  |
  |  | 4     | On closure                                 | Save episodic    |  |
  |  |       |                                           | memory for       |  |
  |  |       |                                           | future context   |  |
  |  +-------+-------------------------------------------+------------------+  |
  |                                                                            |
  +---------------------------------------------------------------------------+
```

---

## ADAPTERS SUMMARY

### BUILT AND WORKING (Phase 2)

```
  +---------------+------------------------------+------------------------+---------------------+
  | Adapter       | File                         | Connects To            | Auth                |
  +---------------+------------------------------+------------------------+---------------------+
  | S3            | src/storage/s3_client.py      | AWS S3 (boto3)         | IAM keys from env   |
  | SQS           | src/queues/sqs.py             | AWS SQS (boto3)        | IAM keys from env   |
  | EventBridge   | src/events/eventbridge.py     | AWS EventBridge (boto3)| IAM keys from env   |
  | Graph API     | src/adapters/graph_api.py     | Microsoft Graph (httpx)| MSAL OAuth2         |
  | Salesforce    | src/adapters/salesforce.py    | STUB (mock data)       | N/A                 |
  | PostgreSQL    | src/db/connection.py          | AWS RDS (asyncpg+SSH)  | SSH key + DB creds  |
  | Redis         | src/cache/redis_client.py     | Redis Cloud            | Password from env   |
  +---------------+------------------------------+------------------------+---------------------+
```

### NOT YET BUILT

```
  +---------------+------------------------------+------------------------+-------+
  | Adapter       | File                         | Purpose                | Phase |
  +---------------+------------------------------+------------------------+-------+
  | Bedrock       | src/adapters/bedrock.py       | LLM inference + embed  |   3   |
  | ServiceNow    | src/adapters/servicenow.py    | Ticket CRUD            |   4   |
  | Comprehend    | src/adapters/comprehend.py    | PII detection          |   4   |
  | Salesforce    | src/adapters/salesforce.py    | Replace stub with real |   8   |
  +---------------+------------------------------+------------------------+-------+
```

---

## DATA MODELS (Phase 1 -- All Built)

All Pydantic models in `src/models/`:

```
  +--------------------+-------------------------------------------------------------------+-------+
  | File               | Models                                                            | Count |
  +--------------------+-------------------------------------------------------------------+-------+
  | workflow.py        | Status, UrgencyLevel, Sentiment, QuerySource, QueryType,          |   9   |
  |                    | Priority, AnalysisResult, WorkflowState, CaseExecution            |       |
  | vendor.py          | VendorTier, VendorMatch, VendorProfile                            |   3   |
  | email.py           | EmailAttachment, EmailMessage, ParsedEmailPayload                 |   3   |
  | query.py           | QuerySubmission, UnifiedQueryPayload                              |   2   |
  | ticket.py          | TicketRecord, TicketLink, RoutingDecision                         |   3   |
  | communication.py   | DraftResponse, DraftEmailPackage, ValidationReport                |   3   |
  | memory.py          | EpisodicMemory, VendorProfileCache, EmbeddingRecord               |   3   |
  | budget.py          | Budget                                                            |   1   |
  | messages.py        | ToolCall, AgentMessage                                            |   2   |
  | triage.py          | TriagePackage                                                     |   1   |
  +--------------------+-------------------------------------------------------------------+-------+
  | TOTAL              |                                                                   |  30   |
  +--------------------+-------------------------------------------------------------------+-------+
```

---

## DATABASE SCHEMA (Phase 1 -- SQL Written, Migrations Ready)

5 schemas, 11 tables in `src/db/migrations/`:

```
  +-----------+-----------+---------------------------------------------+----------------------------+
  | Migration | Schema    | Tables                                      | Purpose                    |
  +-----------+-----------+---------------------------------------------+----------------------------+
  | 001       | intake    | email_messages, email_attachments            | Raw email metadata + S3    |
  | 002       | workflow  | case_execution, ticket_link, routing_decision| Central state, routing     |
  | 003       | memory    | episodic_memory, vendor_profile_cache,       | Context memory + pgvector  |
  |           |           | embedding_index                              |                            |
  | 004       | audit     | action_log, validation_results               | Compliance and debugging   |
  | 005       | reporting | sla_metrics                                  | SLA and performance        |
  +-----------+-----------+---------------------------------------------+----------------------------+
```

---

## REDIS KEY FAMILIES (Phase 1 -- All Built)

```
  +-------------------------------+-----------+-------------------------------------------+
  | Key Pattern                   | TTL       | Purpose                                   |
  +-------------------------------+-----------+-------------------------------------------+
  | vqms:idempotency:<id>         | 7 days    | Prevent duplicate email/query processing  |
  | vqms:session:<token>          | 8 hours   | Portal JWT session cache                  |
  | vqms:vendor:<id>              | 1 hour    | Salesforce vendor profile cache           |
  | vqms:workflow:<id>            | 24 hours  | Active workflow state                     |
  | vqms:sla:<id>                 | No expiry | SLA timer state (managed by SLA service)  |
  | vqms:dashboard:<id>           | 5 minutes | Portal KPI cache                          |
  | vqms:thread:<id>              | 24 hours  | Email thread correlation                  |
  +-------------------------------+-----------+-------------------------------------------+
```

---

## TEST COVERAGE

128 tests across 8 test files -- all passing:

```
  +-------------------------------------------+--------+-------------------------------------------+
  | File                                      | Tests  | What It Covers                            |
  +-------------------------------------------+--------+-------------------------------------------+
  | tests/unit/test_models.py                 | ~50    | All 22 Pydantic models: validation,       |
  |                                           |        | defaults, edge cases                      |
  | tests/unit/test_redis_keys.py             | ~15    | All 7 key families: format, TTL, prefix   |
  | tests/unit/test_correlation.py            | ~10    | UUID4 generation, VQ-YYYY-NNNN format     |
  | tests/unit/test_adapters.py               | ~20    | S3, SQS, EventBridge, Salesforce (moto)   |
  | tests/unit/test_portal_submission.py      | ~10    | Full portal flow with mocked services     |
  | tests/unit/test_email_intake.py           | ~10    | Full email flow with mocked adapters      |
  | tests/unit/test_db_connection.py          |  17    | SSH tunnel, DB init, health, lifecycle    |
  | tests/integration/test_email_intake_e2e.py|  10    | End-to-end: webhook -> S3 -> SQS          |
  +-------------------------------------------+--------+-------------------------------------------+
```

---

## WHAT IS BUILT (Phase 1 + Phase 2)

```
  +--+-----------------------------------------------------------------------+
  |OK| 22 Pydantic models + 7 enums for all data contracts                   |
  |OK| 5 SQL migration files (11 tables across 5 schemas)                    |
  |OK| 7 Redis key families with TTL constants                               |
  |OK| FastAPI app with health check, lifespan management                    |
  |OK| SSH tunnel to bastion host for RDS access                             |
  |OK| Async PostgreSQL connection with SQLAlchemy + asyncpg                 |
  |OK| Async Redis connection with 7 key families                            |
  |OK| S3 adapter (boto3): upload_file(), download_file()                    |
  |OK| SQS adapter (boto3): publish(), consume(), get_queue_size()           |
  |OK| EventBridge adapter (boto3): publish_event()                          |
  |OK| Graph API (real MSAL): fetch_email_by_resource(), fetch_latest_email()|
  |OK| Salesforce adapter (stub): resolve_vendor() with 3-step fallback      |
  |OK| Email intake: 11-step pipeline from webhook to SQS                    |
  |OK| Portal submission: 7-step pipeline from POST /queries to SQS          |
  |OK| POST /queries route with X-Vendor-ID header auth                      |
  |OK| POST /webhooks/ms-graph with validation + notification handling       |
  |OK| Correlation ID (UUID4) and query ID (VQ-YYYY-NNNN) generation         |
  |OK| Idempotency via Redis keys with 7-day TTL                             |
  |OK| Thread correlation (NEW vs EXISTING_OPEN)                             |
  |OK| Pipeline runner script (scripts/run_email_intake.py) 4 modes          |
  |OK| 128 tests passing                                                     |
  +--+-----------------------------------------------------------------------+
```

## WHAT IS STUBBED

```
  +------+-----------------------------------+-------------------------------------------+
  | STUB | Component                         | Detail                                    |
  +------+-----------------------------------+-------------------------------------------+
  | STUB | src/adapters/salesforce.py         | Returns mock vendor data.                 |
  |      |                                   | Real Salesforce API in Phase 8.           |
  +------+-----------------------------------+-------------------------------------------+
```

## WHAT IS NOT BUILT YET

```
  +----+----------------------------------------+-------------------------------------+-------+
  | #  | Component                              | File                                | Phase |
  +----+----------------------------------------+-------------------------------------+-------+
  |  1 | LangGraph Orchestrator                 | src/orchestration/graph.py           |   3   |
  |  2 | Query Analysis Agent                   | src/agents/query_analysis.py         |   3   |
  |  3 | Routing Service                        | src/services/routing.py              |   3   |
  |  4 | KB Search Service                      | src/services/kb_search.py            |   3   |
  |  5 | Bedrock adapter                        | src/adapters/bedrock.py              |   3   |
  +----+----------------------------------------+-------------------------------------+-------+
  |  6 | Resolution Agent (Path A)              | src/agents/resolution.py             |   4   |
  |  7 | Communication Agent (Path B)           | src/agents/communication_drafting.py |   4   |
  |  8 | Quality Gate                           | src/gates/quality_governance.py      |   4   |
  |  9 | Ticket Operations                      | src/services/ticket_ops.py           |   4   |
  | 10 | ServiceNow adapter                     | src/adapters/servicenow.py           |   4   |
  | 11 | Comprehend adapter                     | src/adapters/comprehend.py           |   4   |
  | 12 | Email Delivery                         | (uses graph_api.send_email())        |   4   |
  +----+----------------------------------------+-------------------------------------+-------+
  | 13 | Path C Triage                          | src/api/routes/triage.py             |   5   |
  | 14 | Step Functions integration             | src/orchestration/step_functions.py  |   5   |
  +----+----------------------------------------+-------------------------------------+-------+
  | 15 | SLA Monitoring                         | src/monitoring/sla_alerting.py       |   6   |
  | 16 | Closure/Reopen                         | src/services/ (new module)           |   6   |
  +----+----------------------------------------+-------------------------------------+-------+
  | 17 | Vendor Portal (React)                  | frontend/src/                        |   7   |
  +----+----------------------------------------+-------------------------------------+-------+
  | 18 | Real Salesforce integration            | src/adapters/salesforce.py           |   8   |
  +----+----------------------------------------+-------------------------------------+-------+
```
