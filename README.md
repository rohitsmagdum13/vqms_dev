# VQMS -- Vendor Query Management System

An AI-powered platform that automatically processes vendor support queries received via email or web portal. Built by Hexaware Technologies using Amazon Bedrock (Claude Sonnet 3.5), FastAPI, LangGraph, and a suite of AWS services.

Vendors email vendor-support@company.com or submit through the VQMS portal. The system analyzes the query, searches the knowledge base, and either resolves it automatically (Path A), routes to a human team (Path B), or flags for human review if confidence is low (Path C).

**Reference scenario:** Rajesh Mehta from TechNova Solutions emails about Invoice #INV-2026-0451. The system fetches the email via Microsoft Graph API, identifies Rajesh as a GOLD-tier vendor from Salesforce, searches the knowledge base, drafts a resolution email with specific payment details, validates it through the Quality Gate, creates a ServiceNow ticket, and sends the response -- all in ~11 seconds at ~$0.033 cost.

---

## Current Status

**Phase 2 complete -- Intake Services (Email + Portal)**

Both entry points are built and tested end-to-end with real cloud services:

| Component | Status | Details |
|-----------|--------|---------|
| Pydantic models (22 models, 7 enums) | Built | All data contracts validated with 128 tests |
| PostgreSQL schema (5 schemas, 11 tables) | Built | SQL migrations ready, SSH tunnel to RDS working |
| Redis key schema (7 key families) | Built | Cloud Redis connected, idempotency working |
| Email intake (Graph API webhook) | Built | Real MSAL OAuth2, fetches from Exchange Online |
| Portal intake (POST /queries) | Built | Pydantic validation, X-Vendor-ID header auth |
| S3 storage adapter | Built | boto3 direct, raw emails stored in S3 |
| SQS queue adapter | Built | boto3 direct, payloads enqueued and verified |
| EventBridge adapter | Built | boto3 direct, EmailIngested/QueryReceived events |
| Salesforce adapter | Stub | 3-step vendor resolution with mock data |
| AI Pipeline (LangGraph orchestrator) | Phase 3 | Not yet built |
| Resolution/Communication agents | Phase 4 | Not yet built |
| Quality Gate | Phase 4 | Not yet built |
| Human Review (Path C) | Phase 5 | Not yet built |
| SLA Monitoring | Phase 6 | Not yet built |
| Frontend Portal (React) | Phase 7 | Not yet built |

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
- **Vendor CRM:** Salesforce (stub in Phase 2, real in Phase 8)
- **Ticketing:** ServiceNow ITSM (Phase 4+)
- **AI/LLM:** Amazon Bedrock -- Claude Sonnet 3.5 for inference, Titan Embed v2 for embeddings (Phase 3+)
- **Orchestration:** LangGraph (Phase 3+)
- **Testing:** pytest, moto (AWS mocking), fakeredis

---

## Prerequisites

Before setting up, make sure you have:

1. **Python 3.12+** installed
2. **uv** package manager -- install from https://docs.astral.sh/uv/
3. **AWS credentials** with access to pre-provisioned S3 buckets, SQS queues, and EventBridge bus
4. **SSH private key** (.pem file) for bastion host access to RDS
5. **Microsoft Azure AD app registration** with Mail.Read and Mail.Send permissions for Graph API
6. **Redis** -- either local Redis 7+ or a cloud Redis instance
7. **Git** for version control

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

Open `.env` in your editor and fill in real values. See the Environment Variables section below for what each variable does.

### 4. Configure AWS CLI (separate from .env)

The .env file provides credentials to the Python app via pydantic-settings and `load_dotenv()`. But if you want to use AWS CLI commands (e.g., to create buckets), you need to configure AWS CLI separately:

```bash
aws configure
```

Enter your AWS Access Key ID, Secret Access Key, region (us-east-1), and output format (json).

### 5. Verify AWS resources exist

The app connects to pre-provisioned AWS resources. Verify they exist:

```bash
aws s3 ls s3://vqms-email-raw-prod
aws sqs get-queue-url --queue-name vqms-email-intake-queue
aws events describe-event-bus --name vqms-event-bus
```

If any are missing, create them:

```bash
aws s3 mb s3://vqms-email-raw-prod
aws s3 mb s3://vqms-email-attachments-prod
aws s3 mb s3://vqms-audit-artifacts-prod
aws s3 mb s3://vqms-knowledge-artifacts-prod
aws sqs create-queue --queue-name vqms-email-intake-queue
aws sqs create-queue --queue-name vqms-query-intake-queue
aws events create-event-bus --name vqms-event-bus
```

### 6. Verify Redis connectivity

```bash
uv run python -c "import redis; r = redis.Redis(host='YOUR_REDIS_HOST', port=YOUR_PORT, password='YOUR_PASSWORD'); print(r.ping())"
```

### 7. Run database migrations (via SSH tunnel)

Connect to your bastion host and run the SQL migrations in order:

```bash
psql -U postgres -d vqms -f src/db/migrations/001_intake_schema.sql
psql -U postgres -d vqms -f src/db/migrations/002_workflow_schema.sql
psql -U postgres -d vqms -f src/db/migrations/003_memory_schema.sql
psql -U postgres -d vqms -f src/db/migrations/004_audit_schema.sql
psql -U postgres -d vqms -f src/db/migrations/005_reporting_schema.sql
```

Note: Migration 003 requires the pgvector extension (`CREATE EXTENSION IF NOT EXISTS vector`).

### 8. Start the application

```bash
uv run uvicorn main:app --reload --port 8000
```

### 9. Verify health check

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

## Running the Real Pipeline

The `scripts/run_email_intake.py` script exercises the full email intake pipeline against real cloud services (Redis, S3, SQS, EventBridge, Graph API).

### Simulated mode (default -- no Graph API needed)

```bash
uv run python scripts/run_email_intake.py --sim
```

Uses a simulated TechNova email from Rajesh Mehta. Hits real Redis, S3, SQS, and EventBridge.

### Latest email from mailbox (real Graph API)

```bash
uv run python scripts/run_email_intake.py --latest
```

Fetches the most recent email from your configured shared mailbox via Microsoft Graph API and processes it through the full pipeline.

### Specific email by resource (real Graph API)

```bash
uv run python scripts/run_email_intake.py --real --resource "messages/AAMk..."
```

### Dry run (no AWS services)

```bash
uv run python scripts/run_email_intake.py --dry-run
```

Shows what the pipeline would do without making any real AWS calls.

---

## API Endpoints (Phase 2)

### POST /queries -- Portal submission

Submit a vendor query through the portal.

```bash
curl -X POST http://localhost:8000/queries \
  -H "Content-Type: application/json" \
  -H "X-Vendor-ID: SF-001" \
  -H "X-Vendor-Name: TechNova Solutions" \
  -d '{
    "query_type": "billing",
    "subject": "Invoice Payment Status",
    "description": "When will Invoice #INV-2026-0451 be paid?"
  }'
```

Response (201):
```json
{
  "query_id": "VQ-2026-0451",
  "execution_id": "550e8400-...",
  "correlation_id": "7c9e6679-...",
  "status": "accepted"
}
```

### POST /webhooks/ms-graph -- Email webhook

Receives change notifications from Microsoft Graph subscription.

```bash
curl -X POST http://localhost:8000/webhooks/ms-graph \
  -H "Content-Type: application/json" \
  -d '{"value": [{"resource": "messages/AAMkAD..."}]}'
```

Response (202):
```json
{
  "status": "accepted",
  "processed": 1,
  "results": [{"query_id": "VQ-2026-0452", "status": "accepted"}]
}
```

### GET /health -- Health check

```bash
curl http://localhost:8000/health
```

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
| `AWS_SESSION_TOKEN` | No | Only for temporary STS credentials. Leave commented out if using permanent keys |
| **S3 Buckets** | | |
| `S3_BUCKET_EMAIL_RAW` | Yes | Bucket for raw emails (default: `vqms-email-raw-prod`) |
| `S3_BUCKET_ATTACHMENTS` | Yes | Bucket for attachments (default: `vqms-email-attachments-prod`) |
| **SQS Queues** | | |
| `SQS_QUEUE_PREFIX` | No | Queue name prefix (default: `vqms-`) |
| **EventBridge** | | |
| `EVENTBRIDGE_BUS_NAME` | Yes | Event bus name (default: `vqms-event-bus`) |
| `EVENTBRIDGE_SOURCE` | No | Event source (default: `com.vqms`) |
| **PostgreSQL** | | |
| `POSTGRES_HOST` | Yes | RDS endpoint |
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

---

## Project Structure (Key Directories)

```
vqms/
  main.py                          FastAPI entry point, lifespan management
  CLAUDE.md                        Full project instructions for AI assistant
  Flow.md                          End-to-end runtime walkthrough
  config/settings.py               Pydantic-settings (loads .env)
  src/
    models/                        22 Pydantic models, 7 enums (all built)
    services/
      email_intake.py              11-step email ingestion pipeline
      portal_submission.py         7-step portal submission pipeline
    api/routes/
      queries.py                   POST /queries (portal)
      webhooks.py                  POST /webhooks/ms-graph (email)
    adapters/
      graph_api.py                 Real MSAL OAuth2 + Graph API
      salesforce.py                Stub with mock vendor data
    storage/s3_client.py           boto3 S3 adapter
    queues/sqs.py                  boto3 SQS adapter
    events/eventbridge.py          boto3 EventBridge adapter
    db/
      connection.py                SSH tunnel + async SQLAlchemy
      migrations/                  5 SQL migration files
    cache/redis_client.py          7 key families + connection management
    utils/                         Correlation IDs, logging, helpers
  tests/
    unit/                          7 test files
    integration/                   1 E2E test file
  scripts/
    run_email_intake.py            Real pipeline runner (sim/real/latest/dry-run)
```

See `CLAUDE.md` for the complete folder structure and architecture mapping.

---

## Troubleshooting

### "Unable to locate credentials" from boto3

pydantic-settings reads `.env` into its own model but does NOT export values to `os.environ`. boto3 reads credentials from `os.environ` or `~/.aws/credentials`. Fix: make sure your script calls `load_dotenv(override=True)` before any boto3 imports, or run `aws configure` for CLI usage.

### AWS_SESSION_TOKEN placeholder breaks boto3

If `.env` has `AWS_SESSION_TOKEN=<optional-session-token>`, boto3 sends the literal placeholder as a token and auth fails. Fix: comment out the line entirely if you are using permanent IAM keys.

### S3 bucket / SQS queue "not found"

The app does NOT create AWS resources. All buckets, queues, and event buses must be pre-provisioned. See Setup step 5.

### SSH tunnel connection refused

Verify: (1) `SSH_HOST` is the bastion public IP, (2) `SSH_PRIVATE_KEY_PATH` points to a valid .pem file, (3) security group allows SSH from your IP, (4) `RDS_HOST` is the private RDS endpoint.

### Graph API "invalid_grant" or "unauthorized_client"

Verify: (1) Azure AD app registration has Mail.Read and Mail.Send API permissions, (2) admin consent has been granted, (3) `GRAPH_API_TENANT_ID`, `GRAPH_API_CLIENT_ID`, and `GRAPH_API_CLIENT_SECRET` are correct, (4) the app is registered in the correct tenant.

### Tests fail with import errors

Run `uv sync` to ensure all dependencies are installed. Tests use moto and fakeredis which are test-only dependencies.

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
