# VQMS -- Vendor Query Management System

An AI-powered platform that processes vendor support queries received via email or web portal. Built by Hexaware Technologies using Amazon Bedrock (Claude Sonnet 3.5), FastAPI, LangGraph, and AWS services (S3, SQS, EventBridge).

Vendors email vendor-support@company.com or submit through the VQMS portal. The system analyzes the query, searches the knowledge base, and either resolves it automatically (Path A), routes to a human team (Path B), or flags for human review if confidence is low (Path C).

---

## Current Status

**Phase 2 complete -- Intake Services (Email + Portal)**

Both entry points are built and tested end-to-end with real cloud services:

| Component | Status | Details |
|-----------|--------|---------|
| Pydantic models (22 models, 7 enums) | Built | All data contracts validated with 128 tests |
| PostgreSQL schema (5 schemas, 11+ tables) | Built | 6 SQL migrations, SSH tunnel to RDS working |
| Redis key schema (7 key families) | Built | Cloud Redis connected, idempotency working |
| Email intake (Graph API) | Built | Real MSAL OAuth2, attachment download + S3 upload, 30+ field storage |
| Portal intake (POST /queries) | Built | Pydantic validation, X-Vendor-ID header auth |
| S3 storage adapter | Built | boto3 direct, raw emails + attachments stored |
| SQS queue adapter | Built | boto3 direct, payloads enqueued and verified |
| EventBridge adapter | Built | boto3 direct, EmailIngested/QueryReceived events |
| Salesforce adapter | Built | Real Salesforce SOQL queries via simple-salesforce |
| Structured logging | Built | Console + rotating JSON file logs in data/logs/ |
| Diagnostic scripts | Built | AWS connectivity check, Graph API check, DB check |
| AI Pipeline (LangGraph orchestrator) | Phase 3 | Not yet built |
| Resolution/Communication agents | Phase 4 | Not yet built |
| Quality Gate | Phase 4 | Not yet built |
| Human Review (Path C) | Phase 5 | Not yet built |
| SLA Monitoring | Phase 6 | Not yet built |
| Frontend Portal (Angular) | Built | Full P1-P6 wizard flow: login, dashboard, 3-step query wizard, submit. Zero styling. |

**Test suite:** 128 tests passing (unit + integration). AWS services mocked with moto. Redis mocked with fakeredis.

---

## Tech Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI with Pydantic v2
- **Package manager:** uv (never pip)
- **Database:** PostgreSQL with pgvector on AWS RDS (via SSH tunnel through bastion host)
- **Cache:** Redis 7+ (cloud or local)
- **Storage:** AWS S3 (4 pre-provisioned buckets)
- **Queues:** AWS SQS (pre-provisioned queues)
- **Events:** AWS EventBridge (pre-provisioned event bus)
- **Email:** Microsoft Graph API with MSAL OAuth2 client_credentials flow
- **Vendor CRM:** Salesforce CRM (real connection via simple-salesforce, SOQL queries)
- **Ticketing:** ServiceNow ITSM (Phase 4+)
- **AI/LLM:** Amazon Bedrock -- Claude Sonnet 3.5 for inference, Titan Embed v2 for embeddings (Phase 3+)
- **Orchestration:** LangGraph (Phase 3+)
- **Logging:** structlog with JSON file logging (RotatingFileHandler)
- **Testing:** pytest, moto (AWS mocking), fakeredis

---

## Prerequisites

Before setting up, make sure you have:

1. **Python 3.12+** installed
2. **uv** package manager -- install from https://docs.astral.sh/uv/
3. **AWS credentials** with access to pre-provisioned S3 buckets, SQS queues, and EventBridge bus
4. **SSH private key** (.pem file) for bastion host access to RDS
5. **Microsoft Azure AD app registration** with Mail.Read and Mail.Send permissions for Graph API
5b. **Salesforce credentials** — username, password, and security token (see step 7 below)
6. **Redis** -- either local Redis 7+ or a cloud Redis instance
7. **Git** for version control

On Windows CMD, make sure `python` and `uv` are on your PATH.

---

## Setup (Step-by-Step)

### 1. Clone the repository

```bash
git clone <repo-url>
cd vqms
```

### 2. Install dependencies with uv

```bash
uv sync
```

This creates a virtual environment and installs all packages from pyproject.toml.

### 3. Create your .env file

```bash
cp .env.copy .env
```

On Windows CMD:
```cmd
copy .env.copy .env
```

Open `.env` in your editor and fill in real values. See the Environment Variables section below for what each variable does.

**Important:** If you are using permanent IAM keys (not temporary STS credentials), comment out the `AWS_SESSION_TOKEN` line entirely. Leaving the placeholder value will cause boto3 auth failures.

### 4. Configure AWS CLI (separate from .env)

The .env file provides credentials to the Python app via pydantic-settings and `load_dotenv()`. If you also want to use AWS CLI commands directly, configure the CLI separately:

```bash
aws configure
```

Enter your AWS Access Key ID, Secret Access Key, region (us-east-1), and output format (json).

### 5. Verify AWS resources exist

Run the diagnostic script to check all AWS connectivity:

```bash
uv run python scripts/check_aws.py
```

This checks: AWS credentials (STS), 4 S3 buckets (head + list + write test), SQS queues (get_queue_url + attributes), and EventBridge bus (describe + put_events test). Shows [PASS]/[FAIL]/[WARN] for each check with remediation steps on failure.

If resources are missing, ask your DevOps team to create them (this project does NOT create AWS resources from code).

### 6. Verify Graph API connectivity

```bash
uv run python scripts/check_graph_api.py
```

This checks: env config, MSAL OAuth2 auth, mailbox access, message listing, mail folders, attachment download, and webhook subscriptions. Shows Azure AD permission remediation steps on failure.

To also test send permission (sends a test email to the shared mailbox):
```bash
uv run python scripts/check_graph_api.py --send-test
```

### 7. Configure Salesforce CRM

The Salesforce adapter connects via the `simple-salesforce` library using username + password + security token authentication.

**Get your security token:**
1. Log into Salesforce
2. Go to Setup (gear icon) -> My Personal Information -> Reset My Security Token
3. Click "Reset Security Token" — a new token will be emailed to you

**Set these variables in `.env`:**
```
SALESFORCE_USERNAME=your-salesforce-username@company.com
SALESFORCE_PASSWORD=your-salesforce-password
SALESFORCE_SECURITY_TOKEN=the-token-from-email
SALESFORCE_LOGIN_URL=https://login.salesforce.com
```

Use `https://test.salesforce.com` for sandbox environments.

**Verify the connection:**
```bash
uv run python tests/manual/test_salesforce_connection.py
```

This connects to Salesforce, lists 5 Contacts and 5 Accounts, and confirms the connection works.

To test vendor resolution for a specific email:
```bash
uv run python tests/manual/test_salesforce_connection.py --email john@acme.com
```

### 8. Verify Redis connectivity

```bash
uv run python -c "import redis; r = redis.Redis(host='YOUR_REDIS_HOST', port=YOUR_PORT, password='YOUR_PASSWORD'); print(r.ping())"
```

### 9. Verify database connectivity (via SSH tunnel)

```bash
uv run python scripts/check_db.py
```

This opens an SSH tunnel to the bastion host, connects to RDS, runs a test query, and reports success or failure.

### 10. Run database migrations

You can run all 6 migrations through the bastion tunnel:

```bash
uv run python scripts/run_migrations.py
```

Or manually via psql on the bastion host:

```bash
psql -U postgres -d vqms -f src/db/migrations/001_intake_schema.sql
psql -U postgres -d vqms -f src/db/migrations/002_workflow_schema.sql
psql -U postgres -d vqms -f src/db/migrations/003_memory_schema.sql
psql -U postgres -d vqms -f src/db/migrations/004_audit_schema.sql
psql -U postgres -d vqms -f src/db/migrations/005_reporting_schema.sql
psql -U postgres -d vqms -f src/db/migrations/006_intake_add_detail_columns.sql
```

Note: Migration 003 requires the pgvector extension (`CREATE EXTENSION IF NOT EXISTS vector`). Migration 006 adds 14 detail columns to `intake.email_messages` (to_address, cc_addresses, body_preview, has_attachments, attachment_count, thread_id, is_reply, is_auto_reply, language, status, vendor_id, query_type, invoice_ref, po_ref, contract_ref, amount).

### 11. Start the application

```bash
uv run uvicorn main:app --reload --port 8000
```

### 12. Start the Angular frontend (optional)

The frontend has zero styling -- it exists only for testing the portal flow from a browser. No auth -- any email/password works. Browser default HTML only.

```bash
cd frontend
npm install
npx ng serve --port 4200
```

Open http://localhost:4200 in your browser. The full portal flow (Steps P1-P6):

1. **Login** (`/login`) -- Enter any email and password, click Login
2. **Portal Dashboard** (`/portal`) -- See KPIs (open/resolved queries), recent queries table
3. **Click "+ New Query"** (`/portal/new-query`) -- Select query type (radio buttons)
4. **Click "Next"** (`/portal/new-query/details`) -- Fill in subject, description, priority, reference
5. **Click "Next -- Review"** (`/portal/new-query/review`) -- Review all entered data
6. **Click "Submit Query"** -- POST to backend, see query_id returned
7. **Click "Back to Portal"** -- See the new query in the dashboard table

Other pages:
- **/status** -- Enter a query ID and GET its details from the database

**Note:** The backend must be running on port 8000 (CORS is configured for localhost:4200). No real authentication -- the fake login endpoint accepts any credentials.

### 13. Verify health check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "phase": 2,
  "app_name": "vqms",
  "app_env": "development",
  "version": "1.0.0",
  "database": "connected",
  "redis": "connected"
}
```

---

## Running Tests

Tests use moto for AWS mocking and fakeredis for Redis. No real cloud credentials needed.

```bash
# Run all 128 tests
uv run pytest

# Verbose output
uv run pytest -v

# With coverage report
uv run pytest --cov=src --cov-report=term-missing

# Run only unit tests
uv run pytest tests/unit/

# Run only integration tests
uv run pytest tests/integration/

# Run a specific test file
uv run pytest tests/unit/test_email_intake.py -v
```

### Linting

```bash
uv run ruff check .
```

---

## Running the Email Intake Pipeline

The `scripts/run_email_intake.py` script exercises the full email intake pipeline against real cloud services (Redis, S3, SQS, EventBridge, Graph API).

### Fetch the latest email from the shared mailbox

```bash
uv run python scripts/run_email_intake.py
```

This fetches the most recent email from the configured shared mailbox via Microsoft Graph API and runs it through the full 11-step pipeline:

1. Fetch email from Graph API (with to/cc addresses, body preview, auto-reply detection, attachment content download)
2. Check Redis idempotency (7-day TTL on message_id)
3. Resolve vendor via Salesforce adapter (stub: 3-step fallback)
4. Correlate email thread (in-reply-to / references / conversationId)
5. Upload attachments to S3 (`vqms-email-attachments-prod`)
6. Store raw email JSON to S3 (`vqms-email-raw-prod`) with 30+ fields
7. Store email record in PostgreSQL (`intake.email_messages`) with all detail columns
8. Build UnifiedQueryPayload
9. Publish EmailIngested event to EventBridge
10. Enqueue payload to SQS (`vqms-email-intake-queue`)
11. Print summary

Logs are written to both console and `data/logs/vqms_YYYY-MM-DD.log` (10 MB rotation, 5 backups).

---

## Diagnostic Scripts

| Script | What it checks |
|--------|---------------|
| `scripts/check_aws.py` | AWS credentials, 4 S3 buckets, SQS queues, EventBridge bus |
| `scripts/check_graph_api.py` | MSAL auth, mailbox access, message listing, attachments, send permission, webhooks |
| `scripts/check_db.py` | SSH tunnel to bastion, PostgreSQL connectivity |
| `scripts/run_migrations.py` | Runs all SQL migrations through the SSH tunnel |

---

For full API documentation, see [Doc/API.md](Doc/API.md).

## API Endpoints (Phase 2)

### POST /queries -- Portal submission

Submit a vendor query through the portal.

```bash
curl -X POST http://localhost:8000/queries ^
  -H "Content-Type: application/json" ^
  -H "X-Vendor-ID: SF-001" ^
  -H "X-Vendor-Name: Acme Corporation" ^
  -d "{\"query_type\": \"billing\", \"subject\": \"Invoice Payment Status\", \"description\": \"When will invoice #INV-2026-0451 be paid?\"}"
```

Response (201):
```json
{
  "query_id": "VQ-2026-XXXX",
  "execution_id": "550e8400-...",
  "correlation_id": "7c9e6679-...",
  "status": "accepted"
}
```

### POST /webhooks/ms-graph -- Email webhook

Receives change notifications from Microsoft Graph subscription.

```bash
curl -X POST http://localhost:8000/webhooks/ms-graph ^
  -H "Content-Type: application/json" ^
  -d "{\"value\": [{\"resource\": \"messages/AAMkAD...\"}]}"
```

Response (202):
```json
{
  "status": "accepted",
  "processed": 1,
  "results": [{"query_id": "VQ-2026-XXXX", "status": "accepted"}]
}
```

### GET /health -- Health check

```bash
curl http://localhost:8000/health
```

### Email Dashboard APIs

List email chains (paginated, filterable):
```bash
curl "http://localhost:8000/emails?page=1&page_size=5"
curl "http://localhost:8000/emails?status=New&priority=High&search=invoice"
```

Get email statistics:
```bash
curl http://localhost:8000/emails/stats
```

Get a single email chain:
```bash
curl http://localhost:8000/emails/VQ-2026-0001
```

Download an attachment (presigned S3 URL):
```bash
curl http://localhost:8000/emails/VQ-2026-0001/attachments/1/download
```

See [Doc/API.md](Doc/API.md) for full request/response documentation.

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| **Application** | | |
| `APP_ENV` | Yes | `development`, `staging`, or `production` |
| `APP_DEBUG` | No | `true` in dev, `false` in prod |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| **AWS** | | |
| `AWS_REGION` | Yes | AWS region (e.g., `us-east-1`) |
| `AWS_ACCESS_KEY_ID` | Yes | IAM access key |
| `AWS_SECRET_ACCESS_KEY` | Yes | IAM secret key |
| `AWS_SESSION_TOKEN` | No | Only for temporary STS credentials. Comment out if using permanent keys |
| **S3 Buckets** | | |
| `S3_BUCKET_EMAIL_RAW` | Yes | Bucket for raw emails (default: `vqms-email-raw-prod`) |
| `S3_BUCKET_ATTACHMENTS` | Yes | Bucket for attachments (default: `vqms-email-attachments-prod`) |
| `S3_BUCKET_AUDIT_ARTIFACTS` | Yes | Bucket for audit artifacts (default: `vqms-audit-artifacts-prod`) |
| `S3_BUCKET_KNOWLEDGE` | Yes | Bucket for KB articles (default: `vqms-knowledge-artifacts-prod`) |
| **SQS Queues** | | |
| `SQS_QUEUE_PREFIX` | No | Queue name prefix (default: `vqms-`) |
| **EventBridge** | | |
| `EVENTBRIDGE_BUS_NAME` | Yes | Event bus name (default: `vqms-event-bus`) |
| `EVENTBRIDGE_SOURCE` | No | Event source (default: `com.vqms`) |
| **PostgreSQL** | | |
| `POSTGRES_HOST` | Yes | Database host (localhost if using SSH tunnel) |
| `POSTGRES_PORT` | No | Default 5432 |
| `POSTGRES_DB` | Yes | Database name |
| `POSTGRES_USER` | Yes | Database user |
| `POSTGRES_PASSWORD` | Yes | Database password |
| **SSH Tunnel** | | |
| `SSH_HOST` | Yes* | Bastion host IP/DNS (*skip if using local PostgreSQL) |
| `SSH_PORT` | No | Default 22 |
| `SSH_USERNAME` | Yes* | SSH user (e.g., `ec2-user`) |
| `SSH_PRIVATE_KEY_PATH` | Yes* | Path to .pem file |
| `RDS_HOST` | Yes* | RDS endpoint (forwarded through tunnel) |
| `RDS_PORT` | No | Default 5432 |
| **Redis** | | |
| `REDIS_HOST` | Yes | Redis server host |
| `REDIS_PORT` | No | Default 6379 |
| `REDIS_PASSWORD` | No | Redis auth password |
| `REDIS_SSL` | No | `true` for cloud Redis, `false` for local |
| **Graph API** | | |
| `GRAPH_API_TENANT_ID` | Yes | Azure AD tenant ID |
| `GRAPH_API_CLIENT_ID` | Yes | Azure app client ID |
| `GRAPH_API_CLIENT_SECRET` | Yes | Azure app client secret |
| `GRAPH_API_MAILBOX` | Yes | Shared mailbox email address |

See `.env.copy` for the full list including Bedrock, Salesforce, ServiceNow, Cognito, SLA, and agent configuration variables.

---

## Project Structure

```
vqms/
  main.py                              FastAPI entry point, lifespan (SSH tunnel, DB, Redis)
  CLAUDE.md                            Full project instructions for AI assistant
  Flow.md                              End-to-end runtime walkthrough of what is built
  config/
    __init__.py
    settings.py                        Pydantic-settings (loads .env, 50+ config fields)
  src/
    models/                            22 Pydantic models, 7 enums
      email.py                         EmailMessage, EmailAttachment, ParsedEmailPayload
      query.py                         QuerySubmission, UnifiedQueryPayload
      vendor.py                        VendorProfile, VendorMatch, VendorTier
      ticket.py                        TicketRecord, TicketLink, RoutingDecision
      workflow.py                      WorkflowState, CaseExecution, AnalysisResult
      communication.py                 DraftEmailPackage, DraftResponse, ValidationReport
      memory.py                        EpisodicMemory, VendorProfileCache, EmbeddingRecord
      budget.py                        Budget dataclass
      triage.py                        TriagePackage (Path C)
      messages.py                      AgentMessage, ToolCall
    services/
      email_intake.py                  11-step email ingestion pipeline
      portal_submission.py             7-step portal submission pipeline
    api/routes/
      auth.py                          POST /auth/login (fake dev auth)
      dashboard.py                     GET /dashboard/kpis, GET /queries, GET /queries/{id}
      queries.py                       POST /queries (portal entry point)
      webhooks.py                      POST /webhooks/ms-graph (email entry point)
    adapters/
      graph_api.py                     Real MSAL OAuth2 + Graph API (fetch, send, attachments)
      salesforce.py                    Stub with mock vendor data (3-step fallback)
    storage/
      s3_client.py                     boto3 S3 adapter (upload/download)
    queues/
      sqs.py                           boto3 SQS adapter (publish/consume/queue_size)
    events/
      eventbridge.py                   boto3 EventBridge adapter (publish_event)
    db/
      connection.py                    SSH tunnel + async SQLAlchemy pool
      migrations/
        001_intake_schema.sql          email_messages + email_attachments tables
        002_workflow_schema.sql        case_execution + ticket_link + routing_decision
        003_memory_schema.sql          vendor_profile_cache + episodic_memory + embedding_index
        004_audit_schema.sql           action_log + validation_results
        005_reporting_schema.sql       sla_metrics
        006_intake_add_detail_columns.sql  14 detail columns on email_messages
    cache/
      redis_client.py                  7 key families + connection management + TTLs
    utils/
      logger.py                        structlog setup, console + rotating file handler
      correlation.py                   Correlation ID generation (UUID v4)
      helpers.py                       General utilities
      exceptions.py                    Domain exception classes
  tests/
    conftest.py                        Shared fixtures (moto, fakeredis, sample data)
    unit/                              7 test files (models, adapters, services, redis, correlation, db)
    integration/                       1 E2E test (full email intake pipeline with mocked AWS)
  scripts/
    run_email_intake.py                Full email pipeline runner against real services
    check_aws.py                       AWS connectivity diagnostic (S3, SQS, EventBridge)
    check_graph_api.py                 Graph API connectivity diagnostic (8 checks)
    check_db.py                        Database connectivity check via SSH tunnel
    run_migrations.py                  Run SQL migrations through SSH tunnel
```

See `CLAUDE.md` for the complete folder structure and architecture mapping.

---

## Troubleshooting

### "Unable to locate credentials" from boto3

pydantic-settings reads `.env` into its own model but does NOT export values to `os.environ`. boto3 reads credentials from `os.environ` or `~/.aws/credentials`. Fix: make sure your script calls `load_dotenv(override=True)` before any boto3 imports, or run `aws configure` for CLI usage.

### AWS_SESSION_TOKEN placeholder breaks boto3

If `.env` has `AWS_SESSION_TOKEN=<optional-session-token>`, boto3 sends the literal placeholder as a token and auth fails. Fix: comment out the line entirely if you are using permanent IAM keys.

### S3 bucket / SQS queue "not found"

The app does NOT create AWS resources. All buckets, queues, and event buses must be pre-provisioned. Run `uv run python scripts/check_aws.py` to see which resources are missing.

### SSH tunnel connection refused

Verify: (1) `SSH_HOST` is the bastion public IP, (2) `SSH_PRIVATE_KEY_PATH` points to a valid .pem file, (3) security group allows SSH from your IP, (4) `RDS_HOST` is the private RDS endpoint. Run `uv run python scripts/check_db.py` to diagnose.

### Graph API "invalid_grant" or "unauthorized_client"

Verify: (1) Azure AD app registration has Mail.Read and Mail.Send API permissions, (2) admin consent has been granted, (3) `GRAPH_API_TENANT_ID`, `GRAPH_API_CLIENT_ID`, and `GRAPH_API_CLIENT_SECRET` are correct, (4) the app is registered in the correct tenant. Run `uv run python scripts/check_graph_api.py` for step-by-step diagnosis.

### Tests fail with import errors

Run `uv sync` to ensure all dependencies are installed. Tests use moto and fakeredis which are dev-only dependencies.

### Logs not appearing in data/logs/

The application writes JSON logs to `data/logs/vqms_YYYY-MM-DD.log` with 10 MB rotation (5 backups). The log directory is created automatically on startup. If using the pipeline runner script, it calls `setup_logging()` which enables file logging. If running the FastAPI server via uvicorn, the `lifespan` function in `main.py` calls `setup_logging()`.

### Python LogRecord "filename" conflict

Do not use `"filename"` as a key in logger `extra={}` dicts. Python's LogRecord has a built-in `filename` attribute and will raise `KeyError: "Attempt to overwrite 'filename' in LogRecord"`. Use `"attachment_name"` or another key instead.

---

## Reference Documentation

| Document | Location | Purpose |
|----------|----------|---------|
| CLAUDE.md | Project root | Full AI assistant instructions, architecture mapping, build phases |
| Flow.md | Project root | End-to-end runtime walkthrough of what is built |
| Architecture doc | `docs/references/VQMS_Complete_Architecture_and_Flows.docx` | Single source of truth for system design |
| Solution flow doc | `docs/references/VQMS_Solution_Flow_Document.docx` | Step-by-step runtime flow for all 3 paths |
| Implementation plan | `docs/references/VQMS_Implementation_Plan.docx` | 8-phase build strategy |
| Coding standards | `docs/references/GenAI_AgenticAI_Coding_Standards_Full_transcription.md` | Naming, structure, patterns |
