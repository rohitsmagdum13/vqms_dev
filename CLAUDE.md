# CLAUDE.md — VQMS Agentic AI Platform

## Project Identity
- **Project:** VQMS (Vendor Query Management System) Agentic AI Platform
- **Owner:** Hexaware Technologies
- **Stack:** Python 3.12+, FastAPI, LangGraph, Amazon Bedrock (Claude Sonnet 3.5 for inference, Titan Embed v2 for embeddings), AWS (Step Functions, SQS, EventBridge, S3, API Gateway, CloudWatch, X-Ray, Cognito, Comprehend, Secrets Manager), PostgreSQL (pgvector), Redis, Microsoft Graph API, Salesforce CRM, ServiceNow ITSM, React (portal frontend)
- **Package Manager:** uv — all dependency management, virtual env creation, and script running via `uv` only. Never use pip directly.
- **Entry Points:** Two — Email (vendor-support@company.com via Graph API) and Portal (VQMS web portal via API Gateway + Cognito). Both converge into the same AI pipeline after ingestion.
- **Processing Paths:** Three — Path A (AI-Resolved: KB has the answer), Path B (Human-Team-Resolved: KB lacks specific facts, human team investigates), Path C (Low-Confidence: AI unsure, human reviewer validates before proceeding to A or B)
- **Architecture:** Multi-agent orchestration with AWS Step Functions + LangGraph, 8-phase bottom-up build plan, 6 business flow variants + 3 processing paths, four-tier memory (Redis hot cache / PostgreSQL persistent / pgvector semantic / in-graph agent state)

---

## Claude Code Instructions

This file is read automatically by Claude Code at the start of every session. Follow every rule in this file strictly.

### How to Use Reference Files
- Before writing ANY code, read the three reference files listed below using the `cat` or file read command
- The coding standards file is a `.md` file — read it directly
- The architecture doc and solution flow doc are `.docx` files — use `cat` to read them (the text content is accessible)
- If you cannot read the `.docx` files, ask the user to provide them in a readable format

### Session Start Checklist
1. Read this `CLAUDE.md` file (you're doing this now)
2. Read `tasks/lessons.md` to review past mistakes and avoid repeating them
3. Read `tasks/todo.md` to see current progress and what's next
4. Read `Flow.md` to understand the current state of the pipeline
5. Before writing code, read the relevant section of the architecture doc AND the solution flow doc for the current phase

### File Creation Rules
- Always create files from the project root directory
- Use the exact folder structure defined in this file — do not create folders that are not listed here
- Every Python file must have a module-level docstring as its first line
- Every `__init__.py` can be empty but must exist for Python imports to work
- Run `uv run ruff check .` and `uv run pytest` after creating files to verify

### What Claude Code Must NEVER Do
- Never delete or modify the reference files in `docs/references/`
- Never commit `.env` — only `.env.copy` gets committed
- Never create deployment files (Dockerfile, CDK, Terraform) without explicit user approval
- Never skip writing docstrings or type hints to save time
- Never use `print()` — always use `logging` with structured fields
- Never hardcode secrets, API keys, or credentials anywhere in code
- Never install packages with `pip` — always use `uv add`
- Never write `boto3` calls that create, delete, or modify AWS resources (create_bucket, create_queue, etc.) — we have limited office IAM privileges
- Never write CDK, SAM, CloudFormation, or Terraform code unless the user explicitly requests it

---

## Development Mode — READ THIS FIRST

**This project is in active DEVELOPMENT mode.** We are NOT writing production-grade code yet. The current focus is:

- **Clarity over cleverness.** Write code that a junior developer can read and understand in one pass. No clever one-liners, no premature abstractions.
- **Simple implementations.** Functions should do one thing, in the most straightforward way possible. If there is a simple approach and a sophisticated approach, pick the simple one.
- **Descriptive names everywhere.** Variable names, function names, class names, and file names should tell you exactly what they do. A good name removes the need for a comment.
- **Comments that explain WHY, not WHAT.** Every non-obvious decision gets a comment explaining the reasoning. Do not write comments that repeat what the code already says.
- **Working skeletons first, polish later.** Get the data flowing end-to-end with basic implementations before optimizing. Stubs and simple implementations are perfectly acceptable at this stage.
- **No over-engineering.** Do not add abstraction layers, design patterns, or infrastructure that is not needed right now. Add complexity only when a real problem forces it.

### What This Means in Practice

- Functions can use simple `if/else` instead of strategy patterns
- Error handling can use basic `try/except` with clear logging — no need for circuit breaker wrappers yet
- Configuration can use plain `.env` loading — no need for hierarchical YAML config merging yet
- Database queries can use straightforward SQL — no need for query builders or complex ORM patterns
- Tests should be simple and readable — basic `assert` statements, not complex test frameworks

**When we move to production**, we will layer on:
- Full circuit breaker and retry patterns
- Comprehensive OpenTelemetry tracing
- AWS-specific hardening (IAM roles, VPC, KMS encryption)
- Performance optimization and load testing
- Blue/green deployment and rollback procedures

---

## Enterprise / Office Project Constraints — READ THIS CAREFULLY

**This is a Hexaware office project.** We are working within a corporate AWS environment. We have **direct access** to pre-provisioned AWS services (S3, SQS, EventBridge, Bedrock) and PostgreSQL on RDS (via SSH tunnel through a bastion host). Claude Code must write all code with these constraints in mind.

### What This Means for Code

1. **No AWS resource creation from code.** We do NOT have permissions to create S3 buckets, SQS queues, EventBridge buses, Step Functions state machines, Cognito user pools, or any other AWS resource programmatically. All AWS resources are **pre-provisioned by the infra/DevOps team**. Our code only **reads from and writes to** resources that already exist. Never write `boto3` calls that create, delete, or modify AWS resources (e.g., `create_bucket`, `create_queue`, `create_state_machine`, `put_rule`).

2. **Use existing resource ARNs/names from environment variables.** Every AWS resource (bucket name, queue URL, state machine ARN, event bus name) comes from `.env` or environment variables — never hardcoded, never created at runtime. If a resource doesn't exist yet, log an error and fail gracefully — do NOT attempt to create it.

3. **We HAVE access to these AWS services — code directly against them:**
   - **S3:** Read/write to pre-provisioned buckets. All adapters talk directly to real S3.
   - **SQS:** Read/write to pre-provisioned queues. All adapters talk directly to real SQS.
   - **EventBridge:** Publish events to the pre-provisioned event bus. All adapters talk directly to real EventBridge.
   - **Bedrock:** Invoke Claude Sonnet 3.5 and Titan Embed v2 models.
   - **PostgreSQL on RDS:** Access via SSH tunnel through a bastion host (see SSH tunnel section below).
   - **Redis:** Connect directly (local or cloud Redis).
   - We do NOT have permissions for: CloudFormation, CDK, Terraform, IAM policy changes, VPC modifications, KMS key creation.
   - Always wrap AWS calls in `try/except` with specific `botocore.exceptions.ClientError` handling. Check for `AccessDeniedException` and `UnauthorizedAccess` errors and log them clearly so we know it's a permissions issue, not a bug.

4. **No infrastructure-as-code unless explicitly requested.** Do not generate CDK, SAM, CloudFormation, Terraform, or Serverless Framework files. If the architecture doc mentions Step Functions ASL definitions or similar, write them as **reference documentation** in `Doc/`, not as deployable code.

5. **Secrets come from environment variables, not Secrets Manager directly.** While the architecture doc references AWS Secrets Manager, in our dev environment we load secrets from `.env` files. The code should read from `os.environ` or `pydantic-settings`. Add a `# NOTE: In production, this will come from AWS Secrets Manager` comment where relevant, but do NOT write code that calls `secretsmanager:GetSecretValue` unless the user explicitly confirms we have that permission.

6. **Cloud-only adapters — NO local fallback mode.**
   - All adapters connect directly to real cloud services. There is NO "local" vs "aws" branching.
   - **S3:** `src/storage/s3_client.py` uses boto3 directly. No local filesystem fallback.
   - **SQS:** `src/queues/sqs.py` uses boto3 directly. No in-memory queue fallback.
   - **EventBridge:** `src/events/eventbridge.py` uses boto3 directly. No local event list fallback.
   - **Microsoft Graph API:** `src/adapters/graph_api.py` uses real MSAL auth + Graph API calls. No stub/mock.
   - **Redis:** Use real Redis (local or cloud).
   - **PostgreSQL:** Use real PostgreSQL on RDS via SSH tunnel.
   - For **testing**, use `moto` to mock AWS services and `fakeredis` to mock Redis. Tests do NOT require real AWS credentials.

7. **Adapter pattern — cloud-only, clean abstraction.** Every AWS service interaction MUST go through an adapter in `src/adapters/` or `src/storage/`, `src/queues/`, `src/events/`. The adapter provides:
   - A clean async interface that the rest of the codebase imports
   - Proper error handling with `botocore.exceptions.ClientError`
   - Structured logging with correlation_id
   - No branching between local/cloud — only the cloud implementation exists

8. **PostgreSQL via SSH Tunnel.** The RDS instance is NOT directly accessible from local machines. All database connections go through an SSH tunnel to a bastion host:
   - Use the `sshtunnel` library to establish the tunnel
   - SSH config comes from env vars: `SSH_HOST`, `SSH_PORT`, `SSH_USERNAME`, `SSH_PRIVATE_KEY_PATH`, `RDS_HOST`, `RDS_PORT`
   - The tunnel must stay alive for the app lifetime and close on shutdown
   - Connection flow: local machine → SSH tunnel to bastion → bastion forwards to RDS

9. **Microsoft Graph API — real connection.** Email ingestion uses the real Microsoft Graph API:
   - MSAL library for OAuth2 client_credentials flow
   - Fetch emails via GET /users/{mailbox}/messages/{id}
   - Send emails via POST /users/{mailbox}/sendMail
   - Webhook subscription for real-time email detection
   - Polling fallback every 60 seconds
   - Auth credentials from env: `GRAPH_API_TENANT_ID`, `GRAPH_API_CLIENT_ID`, `GRAPH_API_CLIENT_SECRET`, `GRAPH_API_MAILBOX`

### Rules Summary for Claude Code

| Situation | Do This | Do NOT Do This |
|-----------|---------|----------------|
| Need an S3 bucket | Read bucket name from env var, use boto3 adapter | Call `create_bucket()` |
| Need an SQS queue | Read queue URL from env var, use boto3 adapter | Call `create_queue()` |
| Need a secret | Read from `os.environ` | Call `secretsmanager:GetSecretValue` without permission |
| AWS call fails with AccessDenied | Log clearly, raise with context | Silently retry or swallow the error |
| Testing | Use `moto` mocks for AWS, `fakeredis` for Redis | Write "if local" / "if aws" branching |
| Infra setup needed | Document it in `Doc/infra_requirements.md` | Write CDK/Terraform/CloudFormation code |
| Need database connection | Use SSH tunnel to bastion → RDS | Connect directly to RDS endpoint |
| Need to send/fetch email | Use MSAL + Graph API | Use stub/mock Graph client |

---

## Mandatory Reference Files

**IMPORTANT FOR CLAUDE CODE:** You must read these files before writing any code. Use `cat` to read them. Do not assume you know what's in them — actually read them.

### 1. Coding Standards (FOLLOW FOR NAMING AND STRUCTURE)
**File:** `docs/references/GenAI_AgenticAI_Coding_Standards_Full_transcription.md`
**Read command:** `cat docs/references/GenAI_AgenticAI_Coding_Standards_Full_transcription.md`

This document defines the naming conventions, project structure, and patterns we follow. In development mode, we follow these rules:

**Always enforced (even in development):**
- Naming conventions: `snake_case` for variables/functions, `UPPER_CASE` for constants, `PascalCase` for classes
- Type hints on all function signatures
- Docstrings on all public functions and classes
- Domain-specific exception classes (not bare `Exception`)
- Pydantic models for data contracts between modules
- Structured logging (not `print()`)
- Correlation IDs passed through the pipeline
- No secrets in code — always use `.env` or environment variables
- Prompt management: versioned prompts under `prompts/` with metadata
- LLM client abstraction: wrap provider SDKs behind an interface
- JSON-only tool I/O with Pydantic models — do not parse free-form text without validation
- Prefer `asyncio` for concurrency, use semaphores to bound concurrency
- Define clear agent termination conditions and timeout/iteration limits
- Memory interfaces: every memory store must implement read, write, search, delete
- Idempotency and reentrancy: actions must be idempotent, maintain state snapshots for resumption

**Relaxed for development (will enforce for production):**
- Full `mypy --strict` type checking (we still use type hints, but allow some flexibility)
- OpenTelemetry span instrumentation on every function
- Circuit breaker wrappers on all external calls
- Comprehensive retry policies with backoff configuration
- Full policy-as-code YAML for tool access
- Cost/token budget enforcement at orchestration layer
- Production-grade rate limiting with token buckets
- Multi-dimensional rate limits (per-provider, per-tenant, per-user, per-tool)
- Full RBAC per-tool and per-agent scopes

**Key sections to reference:**
- Section 1: Python practices (naming, formatting, error handling basics)
- Section 1.2: GenAI patterns (prompt storage, LLM client abstraction, pydantic contracts)
- Section 2: Multi-layer architecture (layering, message envelopes)
- Section 3: Memory management (memory types, RAG chunking basics)
- Section 4: Agentic framework best practices (agent design, planning, safety)
- Section 8: Testing & evaluation (unit, integration, contract, LLM-specific)
- Section 10: Security, compliance & responsible AI
- Section 12: Directory structure (the canonical folder layout)
- Section 21: Evaluation metrics (RAGAS, LLM-as-a-judge)

### 2. Architecture Document (SINGLE SOURCE OF TRUTH)
**File:** `docs/references/VQMS_Complete_Architecture_and_Flows.docx`
**Read command:** `cat docs/references/VQMS_Complete_Architecture_and_Flows.docx`

This document defines the **entire system** — all agents, services, data flows, storage schemas, queues, events, and business flow variants. Every design decision must align with this document.

**Never invent agents, services, flows, queues, events, or integrations that are not in this document without explicitly flagging it as a proposed addition.**

### 3. Solution Flow Document (END-TO-END RUNTIME REFERENCE)
**File:** `docs/references/VQMS_Solution_Flow_Document.docx`
**Read command:** `cat docs/references/VQMS_Solution_Flow_Document.docx`

This document provides the **complete step-by-step runtime flow** for all three processing paths (A, B, C) and both entry points (Email, Portal). It includes:

- **Entry Point 1 (Email):** Steps E1–E2 (9 sub-steps for email ingestion including thread correlation, vendor identification from sender)
- **Entry Point 2 (Portal):** Steps P1–P6 (login, dashboard, wizard form, submission via POST /queries with JWT auth)
- **Unified AI Pipeline:** Steps 7–12 (context loading, query analysis, routing + KB search, drafting, quality gate, ticket + email send)
- **Path A (AI-Resolved):** KB has specific facts → Resolution Agent generates full answer → vendor gets resolution email
- **Path B (Human-Team-Resolved):** KB lacks specifics → Acknowledgment email sent → human team investigates → AI drafts resolution from team's notes
- **Path C (Low-Confidence):** Confidence < 0.85 → workflow pauses → human reviewer validates → resumes into Path A or B
- **SLA Monitoring, Closure, and Reopen** flows
- **Per-step metrics:** Time, cost, LLM usage, and services involved at every step
- **Reference example:** Rajesh Mehta / TechNova Solutions (VN-30892), Invoice #INV-2026-0451, Path A, ~11 seconds, ~$0.033

**This document supplements the Architecture Doc with concrete runtime behavior and must be consulted for any step-by-step implementation decisions.**

### 4. Implementation Plan (PHASE EXECUTION GUIDE)
**File:** `docs/references/VQMS_Implementation_Plan.docx`
**Read command:** `cat docs/references/VQMS_Implementation_Plan.docx`

This document provides the **8-phase build strategy** with detailed gate criteria, module breakdown, architecture-to-code mapping, API design, integration strategy, error handling, validation, security, testing, and deployment readiness. It is the primary guide for what to build and in what order.

---

## Workflow Orchestration

### 1. Plan Before You Build
- For any non-trivial task (3+ steps), write a plan to `tasks/todo.md` first
- If something goes wrong, stop and re-plan — do not push forward blindly
- Before writing code, confirm: "Does this align with the architecture doc?"

### 2. Keep It Simple
- Start with the simplest working implementation
- Add complexity only when a real problem requires it
- If a function is getting long or confusing, split it into smaller named functions
- Prefer readability over performance at this stage

### 3. Self-Improvement Loop
- After any correction from the user, update `tasks/lessons.md` with the pattern
- Write a note for yourself that prevents the same mistake
- Review lessons at the start of each session

### 4. Verification Before Done
- Run `uv run ruff check .` for linting — fix any errors before moving on
- Run `uv run pytest` for tests — all tests must pass
- If either command fails, fix the issues immediately — do not ask the user what to do
- Check that requirements.txt includes all third-party packages used in the code
- Update `Flow.md` if any pipeline function was added, changed, or wired up
- Update `README.md` if any setup step, env var, or dependency was added
- Ask yourself: "Would a developer reading this for the first time understand it immediately?"

### 5. Autonomous Bug Fixing
- When given a bug report, investigate and fix it — do not ask for hand-holding
- Look at logs, errors, and failing tests — then resolve them
- Zero context switching required from the user

---

## Task Management

### Before Starting Any Task
1. Read `tasks/todo.md` — check what's already done and what's next
2. Read `tasks/lessons.md` — avoid repeating past mistakes
3. Identify which Phase (1-8) the task belongs to — never skip phases

### During a Task
1. **Plan First:** Write plan to `tasks/todo.md` with checkable items using `- [ ]` syntax
2. **Verify Plan:** Check in with the user before starting implementation
3. **Track Progress:** Mark items complete with `- [x]` as you go
4. **Explain Changes:** Give a high-level summary at each step
5. **Test:** Run `uv run pytest` and `uv run ruff check .` after creating/modifying files

### After a Task
1. Update `tasks/todo.md` with what was completed
2. If the user corrected you, add the lesson to `tasks/lessons.md` with this format:
   ```
   ## [Date] — Lesson Title
   **Mistake:** What I did wrong
   **Correction:** What the right approach is
   **Rule:** One-line rule to prevent this in the future
   ```

---

## Living Documentation Rules (ALWAYS ENFORCED)

Two files must stay current with the codebase at all times: `Flow.md` and `README.md`. Treat them like code — if the code changes, these files change in the same session.

### Flow.md — End-to-end runtime walkthrough

**Location:** `Flow.md` (project root)

**Purpose:** Trace exactly how a vendor query moves through the codebase, function by function. Must cover BOTH entry points (email and portal) and all three processing paths (A, B, C). A developer should read this file and know which file to open, which function to call, and what data goes in and out at every step.

**What goes in Flow.md:**
- Only document steps that have working code (or at least a function stub with `NotImplementedError`). Do not describe functions that do not exist in the codebase.
- For every step, include:
  - What triggers this step
  - Which exact file and function gets called (full path like `src/services/email_intake.py` -> `fetch_and_parse_email()`)
  - What input it receives (which Pydantic model or raw type)
  - What it does internally (plain English, step by step)
  - What output it produces (which Pydantic model or raw type)
  - Where data gets stored (PostgreSQL table, Redis key pattern, S3 bucket, or local file)
  - What happens next and why
- If a step is a stub (`NotImplementedError` or `TODO`), include it but mark it clearly: `[STUB — not yet implemented]`
- At the bottom, keep a "What is not built yet" section listing architecture doc steps that have no code at all

**Format:** Numbered walkthrough. Plain English. No marketing language. Write like you're explaining the codebase to a new team member on their first day.

**When to update Flow.md:**
- After completing any phase (1 through 8)
- After adding or changing any function that appears in the query processing pipeline (email or portal path)
- After wiring up a new service, agent, adapter, or gate
- After connecting any two components that were previously disconnected
- After implementing a new processing path branch (Path A, B, or C)

### README.md — Project overview and setup

**Location:** `README.md` (project root)

**Purpose:** A developer clones the repo, reads README.md, and knows: what this project does, how to set it up, how to run it, what the current state of development is, and where to find things.

**What goes in README.md:**
- Project name and one-paragraph description (what VQMS does, who it's for)
- Current development phase and what works right now
- Tech stack summary (not a wall of badges — just a plain list)
- Setup instructions: prerequisites, clone, install deps, configure .env, run migrations, start the app
- How to run tests
- Project structure overview (brief — point to CLAUDE.md for the full tree)
- Links to reference docs (architecture doc, coding standards, Flow.md)
- Enterprise constraints note (limited AWS access, local dev mode)
- What is built vs. what is planned (keep this honest and current)

**When to update README.md:**
- After completing any phase
- After adding new setup steps (new dependency, new env var, new migration)
- After changing how to run the project
- After any change that would confuse a developer who last read the README a week ago

### Rules for Claude Code

1. **After every phase completion:** Update both `Flow.md` and `README.md` before reporting the phase as done. This is not optional.
2. **After any pipeline change:** If you add, rename, or rewire any function in the query processing pipeline (email or portal path), update `Flow.md` in the same session.
3. **After any setup change:** If you add a new package, env var, migration, or config file, update `README.md` in the same session.
4. **Never let docs drift from code.** If `Flow.md` describes a function that no longer exists, or `README.md` says "run X" but X has changed, that is a bug. Fix it immediately.
5. **Use real function names and file paths.** No placeholders like "the analysis module" — write `src/agents/query_analysis.py` -> `classify_query_intent()`.
6. **Write like a person, not a brochure.** No "leveraging", no "comprehensive suite of", no "seamlessly integrates". Say what the code does. Period.

---

## Coding Standards for Development Mode

### Naming Convention Rules (ALWAYS ENFORCED)

```python
# VARIABLES: snake_case — descriptive, reads like English
email_message = fetch_email(message_id)       # Good: clear what it holds
vendor_match_result = find_vendor(sender)      # Good: says exactly what it is
em = fetch(mid)                                # Bad: abbreviations are unclear
data = get_data()                              # Bad: "data" tells you nothing

# FUNCTIONS: snake_case — starts with a verb, says what it does
def parse_email_body(raw_html: str) -> str:    # Good: verb + what it acts on
def find_vendor_by_email(email: str):          # Good: specific about the lookup
def process(x):                                # Bad: vague verb, unclear input
def do_stuff():                                # Bad: tells you nothing

# CLASSES: PascalCase — noun, represents a thing or concept
class EmailMessage:                            # Good: clear domain object
class VendorResolutionService:                 # Good: says what the service does
class Helper:                                  # Bad: too vague
class Mgr:                                     # Bad: abbreviation

# CONSTANTS: UPPER_SNAKE_CASE — configuration values and fixed settings
MAX_RETRY_ATTEMPTS = 3                         # Good: clear setting name
DEFAULT_SLA_HOURS = 24                         # Good: includes the unit
CONFIDENCE_THRESHOLD = 0.85                    # Good: domain-specific constant
x = 3                                          # Bad: magic number, no name

# BOOLEANS: should read like a yes/no question
is_duplicate = check_idempotency(message_id)   # Good: reads as "is it a duplicate?"
has_attachments = len(attachments) > 0         # Good: reads as "does it have attachments?"
vendor_found = vendor_match is not None        # Good: reads as "was the vendor found?"
flag = True                                    # Bad: "flag" tells you nothing
```

### Comment Rules (ALWAYS ENFORCED)

```python
# GOOD COMMENTS: Explain WHY, not WHAT

# Check for duplicates before processing to prevent
# the same email from creating multiple tickets
if await is_duplicate_email(message_id, redis_client):
    logger.info("Skipping duplicate email", message_id=message_id)
    return None

# Salesforce sometimes returns inactive vendor records,
# so we filter them out before matching
active_vendors = [v for v in vendors if v.is_active]

# Using a 7-day TTL because Exchange Online can redeliver
# emails up to 5 days after the original send in recovery mode
IDEMPOTENCY_TTL_SECONDS = 604800  # 7 days

# BAD COMMENTS: Just repeat what the code says

# Set x to 5
x = 5

# Loop through the list
for item in items:

# Check if vendor is not None
if vendor is not None:

# Return the result
return result
```

### Function Structure (Development Mode)

Every function should follow this simple pattern. Note that this is intentionally simpler than the production skeleton — we prioritize readability and quick understanding.

```python
"""Module: email_intake.py

Email Ingestion Service for VQMS.

This module handles fetching emails from Exchange Online via
Microsoft Graph API, parsing email content, identifying the vendor,
performing thread correlation, and storing the parsed data in
PostgreSQL and S3.

Corresponds to Steps E1-E2 in the VQMS Solution Flow Document
and Steps 2-3 in the VQMS Architecture Document.
"""

from __future__ import annotations

import logging
from datetime import datetime

# Project imports grouped and commented
from src.models.email import EmailMessage, ParsedEmailPayload

# Set up structured logger for this module
logger = logging.getLogger(__name__)


# --- Domain Exception ---
# Each module defines its own exception so callers can
# handle failures from this specific service separately
class EmailIntakeError(Exception):
    """Raised when email ingestion fails.

    Examples: Graph API unreachable, MIME parsing failure,
    S3 upload timeout, PostgreSQL write failure.
    """


# --- Main Service Functions ---

async def fetch_and_parse_email(
    message_id: str,
    *,
    correlation_id: str | None = None,
) -> ParsedEmailPayload | None:
    """Fetch a single email from Exchange Online and parse it.

    This is the main entry point for email ingestion. It handles
    the full pipeline: fetch from Graph API, check for duplicates,
    parse MIME content, and return a normalized payload.

    Args:
        message_id: The Exchange Online message ID to fetch.
        correlation_id: Tracing ID that follows this email through
            the entire VQMS pipeline. If not provided, one will
            be generated.

    Returns:
        ParsedEmailPayload with all extracted fields, or None
        if the email was a duplicate (already processed).

    Raises:
        EmailIntakeError: If the email cannot be fetched or parsed.
            Includes the correlation_id for log tracing.
    """
    # TODO: Implement in Phase 2
    # Steps:
    # 1. Check Redis idempotency key
    # 2. Fetch from Graph API
    # 3. Parse MIME headers and body
    # 4. Store raw email in S3
    # 5. Write metadata to PostgreSQL
    # 6. Publish EmailParsed event
    raise NotImplementedError("Phase 2 implementation pending")
```

### What Makes This Development-Friendly

Compared to the production skeleton, this approach:

1. **Uses plain `TODO` comments** instead of empty implementations — makes it obvious what needs building
2. **Lists the steps in comments** — any developer can see the implementation plan
3. **Keeps the docstring focused** — explains what, why, and edge cases without being overwhelming
4. **Avoids premature abstraction** — no Protocol classes or factory patterns until we need them
5. **Uses simple return types** — `ParsedEmailPayload | None` instead of wrapping in Result objects

---

## Project Folder Structure

This structure follows **Section 12** of the coding standards, adapted with VQMS-specific modules from **Section 0.4** of the architecture document.

```
vqms/
├── pyproject.toml                              # uv project config, all deps here
├── uv.lock                                     # uv lockfile (auto-generated)
├── .python-version                             # 3.12
├── .env                                        # Environment variables (NEVER committed)
├── .env.copy                                   # Template for .env — copy and fill in values
├── .gitignore                                  # Git ignore rules
├── .ruff.toml                                  # Linting config (ruff)
├── main.py                                     # Entry point
├── README.md                                   # Project overview
├── CLAUDE.md                                   # This file — AI assistant instructions
├── Flow.md                                     # End-to-end runtime walkthrough (update after every phase)
│
├── tasks/
│   ├── todo.md                                 # Active task tracking
│   └── lessons.md                              # Learnings from corrections
│
├── Doc/                                        # Project documentation
│   ├── System_Architecture.md                  # System architecture diagrams
│   ├── Application_Workflow.md                 # Workflow of the application
│   └── Agents.md                               # Detailed descriptions of agents
│
├── docs/
│   └── references/                             # Uploaded reference files (DO NOT edit)
│       ├── GenAI_AgenticAI_Coding_Standards_Full_transcription.md
│       ├── VQMS_Complete_Architecture_and_Flows.docx
│       ├── VQMS_Solution_Flow_Document.docx
│       └── VQMS_Implementation_Plan.docx
│
├── security/                                   # Security and compliance configs
│   ├── guardrails_config.yaml
│   ├── data_privacy_policy.md
│   ├── access_control.yaml
│   ├── encryption_config.yaml
│   ├── audit_logging_config.yaml
│   └── gdpr_compliance_checklist.md
│
├── config/                                     # Configuration files
│   ├── __init__.py
│   ├── agents_config.yaml                      # Agent personas, goals, backstories
│   ├── tools_config.yaml                       # API keys and tool settings
│   ├── model_config.yaml                       # LLM settings (Bedrock Claude config)
│   ├── logging_config.yaml                     # Structured logging format
│   ├── database_config.yaml                    # PostgreSQL + Redis connection settings
│   ├── dev_config.yaml                         # Overrides for local development
│   ├── test_config.yaml                        # Overrides for test environment
│   └── prod_config.yaml                        # Overrides for production
│
├── prompts/                                    # Versioned AI prompt templates (Jinja2)
│   ├── query_analysis/
│   │   └── v1.jinja                            # Prompt for Query Analysis Agent
│   ├── resolution/
│   │   └── v1.jinja                            # Prompt for Resolution Agent (Path A — full answer from KB)
│   ├── communication_drafting/
│   │   ├── acknowledgment_v1.jinja             # Prompt for acknowledgment email (Path B — no answer)
│   │   └── resolution_from_notes_v1.jinja      # Prompt for resolution email from human team's notes (Path B)
│   └── orchestration/
│       └── v1.jinja                            # Prompt for Orchestration decisions
│
├── src/
│   ├── __init__.py
│   │
│   ├── models/                                 # Pydantic data models
│   │   ├── __init__.py                         # (the "shape" of every data object)
│   │   ├── email.py                            # EmailMessage, EmailAttachment, ParsedEmailPayload
│   │   ├── query.py                            # QuerySubmission (portal), UnifiedQueryPayload (shared)
│   │   ├── vendor.py                           # VendorProfile, VendorMatch, VendorTier
│   │   ├── ticket.py                           # TicketRecord, TicketLink, RoutingDecision
│   │   ├── workflow.py                         # WorkflowState, CaseExecution, AnalysisResult
│   │   ├── communication.py                    # DraftEmailPackage, DraftResponse, ValidationReport
│   │   ├── memory.py                           # EpisodicMemory, VendorProfileCache, EmbeddingRecord
│   │   ├── budget.py                           # Budget dataclass (token and cost limits)
│   │   ├── triage.py                           # TriagePackage (Path C human review)
│   │   └── messages.py                         # AgentMessage, ToolCall (inter-agent communication)
│   │
│   ├── agents/                                 # AI agent definitions (the "brains")
│   │   ├── __init__.py
│   │   ├── abc_agent.py                        # Base class all agents inherit from
│   │   ├── query_analysis.py                   # Analyzes queries (email OR portal), extracts intent/urgency/entities
│   │   ├── resolution.py                       # Generates full resolution emails when KB has the answer (Path A)
│   │   ├── communication_drafting.py           # Writes acknowledgment emails (Path B) and resolution emails from team notes
│   │   └── orchestration.py                    # Decides what happens next (routing logic)
│   │
│   ├── services/                               # Deterministic business logic (no AI, just rules)
│   │   ├── __init__.py
│   │   ├── email_intake.py                     # Fetches emails from Graph API, parses, stores, identifies vendor, correlates threads
│   │   ├── portal_submission.py                # Handles POST /queries from portal, validates, generates IDs, queues
│   │   ├── vendor_resolution.py                # Looks up vendor in Salesforce by email or vendor_id
│   │   ├── ticket_ops.py                       # Creates/updates tickets in ServiceNow
│   │   ├── routing.py                          # Deterministic rules engine for team assignment and SLA
│   │   ├── kb_search.py                        # Embeds query via Titan Embed v2, cosine similarity search against KB in S3
│   │   └── memory_context.py                   # Loads past context for the current query thread
│   │
│   ├── gates/                                  # Quality checkpoints
│   │   ├── __init__.py
│   │   └── quality_governance.py               # Validates drafts: ticket#, SLA wording, PII scan
│   │
│   ├── monitoring/                             # Background watchers
│   │   ├── __init__.py
│   │   └── sla_alerting.py                     # Watches SLA clocks, triggers escalations
│   │
│   ├── adapters/                               # External system connectors (API wrappers)
│   │   ├── __init__.py
│   │   ├── graph_api.py                        # Microsoft Graph API (Exchange Online emails)
│   │   ├── salesforce.py                       # Salesforce CRM REST API
│   │   ├── servicenow.py                       # ServiceNow REST API
│   │   ├── bedrock.py                          # Amazon Bedrock (Claude) — ALL LLM calls go here
│   │   └── comprehend.py                       # Amazon Comprehend (PII detection for Quality Gate)
│   │
│   ├── tools/                                  # Custom tools agents can call
│   │   ├── __init__.py
│   │   └── custom_tools.py                     # Tool registry with pydantic input/output contracts
│   │
│   ├── memory/                                 # State management layers
│   │   ├── __init__.py
│   │   ├── short_term.py                       # Redis — fast, temporary cache
│   │   └── long_term.py                        # pgvector — permanent semantic memory (RAG)
│   │
│   ├── orchestration/                          # Workflow engine
│   │   ├── __init__.py
│   │   ├── graph.py                            # LangGraph state machine (the main pipeline)
│   │   ├── router.py                           # Routing logic (which flow variant to use)
│   │   ├── manager.py                          # Hierarchical agent manager
│   │   └── step_functions.py                   # AWS Step Functions integration
│   │
│   ├── api/                                    # FastAPI routes
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── queries.py                      # POST /queries, GET /queries/{id}
│   │       ├── dashboard.py                    # GET /dashboard/kpis
│   │       ├── triage.py                       # GET /triage/queue, POST /triage/{id}/review
│   │       ├── webhooks.py                     # POST /webhooks/ms-graph, POST /webhooks/servicenow
│   │       └── admin.py                        # GET /admin/metrics
│   │
│   ├── db/                                     # Database layer
│   │   ├── __init__.py
│   │   ├── connection.py                       # PostgreSQL async connection pool
│   │   └── migrations/                         # SQL files that create the database tables
│   │       ├── 001_intake_schema.sql            # email_messages + email_attachments
│   │       ├── 002_workflow_schema.sql          # case_execution + ticket_link + routing_decision
│   │       ├── 003_memory_schema.sql            # vendor_profile_cache + episodic_memory + embedding_index
│   │       ├── 004_audit_schema.sql             # action_log + validation_results
│   │       └── 005_reporting_schema.sql         # sla_metrics
│   │
│   ├── cache/                                  # Redis wrapper
│   │   ├── __init__.py
│   │   └── redis_client.py                     # Connection + key builders for 7 key families
│   │
│   ├── storage/                                # S3 file storage
│   │   ├── __init__.py
│   │   └── s3_client.py                        # Upload/download for all 4 S3 buckets
│   │
│   ├── events/                                 # Event publishing
│   │   ├── __init__.py
│   │   └── eventbridge.py                      # Publishes all 20 EventBridge event types
│   │
│   ├── queues/                                 # Message queues
│   │   ├── __init__.py
│   │   └── sqs.py                              # Producer/consumer for all 11 SQS queues + DLQ
│   │
│   ├── llm/                                    # LLM utilities
│   │   ├── __init__.py
│   │   ├── factory.py                          # Creates the right model instance
│   │   ├── utils.py                            # RAG chunking, indexing helpers
│   │   └── security_helpers.py                 # PII redaction, encryption helpers
│   │
│   ├── utils/                                  # Shared helper functions
│   │   ├── __init__.py
│   │   ├── logger.py                           # Structured JSON logging setup
│   │   ├── helpers.py                          # General utility functions
│   │   ├── correlation.py                      # Correlation ID generation
│   │   ├── retry.py                            # Simple retry with backoff
│   │   └── validation.py                       # Input validation helpers
│   │
│   └── evaluation/                             # Testing AI quality
│       ├── __init__.py
│       ├── matrix.py                           # Metrics collection
│       ├── eval.py                             # LLM-as-a-judge evaluation
│       └── result_folder/                      # Where eval results get saved
│
├── tests/                                      # All test files
│   ├── __init__.py
│   ├── conftest.py                             # Shared fixtures (mock Bedrock, sample emails, etc.)
│   ├── unit/                                   # Unit tests — one test file per source module
│   │   ├── __init__.py
│   │   ├── test_models.py                      # Schema validation tests
│   │   ├── test_email_intake.py                # Email ingestion tests
│   │   └── ...                                 # (mirrors every module in src/)
│   └── evals/                                  # AI quality evaluations
│       ├── __init__.py
│       ├── test_faithfulness.py                # RAGAS faithfulness metric
│       ├── test_answer_relevance.py            # Answer relevance scoring
│       └── golden_sets/                        # Curated test input/expected output pairs
│
├── data/                                       # Local data storage
│   ├── knowledge_base/                         # RAG source documents
│   ├── vector_store/                           # Local vector DB files
│   ├── storage/                                # Local data files (test artifacts, temp files)
│   ├── logs/                                   # Execution logs
│   └── artifacts/                              # Generated output files
│
└── notebooks/                                  # Jupyter notebooks for experimentation
    ├── tool_testing.ipynb                      # Test individual tools/adapters
    └── agent_simulation.ipynb                  # Simulate agent conversations
```

### Quick Reference — "Where Do I Put This?"

| I want to...                              | Put it in...                          |
|-------------------------------------------|---------------------------------------|
| Add a new AI agent                        | `src/agents/` (inherit from `abc_agent.py`) |
| Add a new data model                      | `src/models/` (pydantic model)        |
| Add a new external API connector          | `src/adapters/` (wrap the REST API)   |
| Add a deterministic business service      | `src/services/`                       |
| Add a new quality/validation check        | `src/gates/`                          |
| Add a new prompt template                 | `prompts/<agent_name>/v<N>.jinja`     |
| Add a new database table                  | `src/db/migrations/` (new SQL file)   |
| Add a utility/helper function             | `src/utils/`                          |
| Add a custom tool for agents              | `src/tools/custom_tools.py`           |
| Add/update environment variable           | `.env` AND `.env.copy`                |
| Add a YAML config                         | `config/`                             |
| Add a security policy                     | `security/`                           |
| Add a FastAPI route                       | `src/api/routes/`                     |
| Add a portal API endpoint                 | FastAPI router (served via API Gateway + Cognito auth) |
| Add a KB article for vector search        | `data/knowledge_base/`                |
| Write a unit test                         | `tests/unit/test_<module_name>.py`    |
| Write an LLM eval test                    | `tests/evals/`                        |
| Add a golden test set                     | `tests/evals/golden_sets/`            |
| Add RAG source documents                  | `data/knowledge_base/`                |
| Store files locally (S3 fallback)         | `data/storage/<bucket>/<key>` (auto-created by adapter) |
| Experiment in a notebook                  | `notebooks/`                          |
| Track a new task                          | `tasks/todo.md`                       |
| Log a lesson learned                      | `tasks/lessons.md`                    |
| Write high-level docs                     | `Doc/`                                |
| Update runtime walkthrough                | `Flow.md` (project root)              |
| Update project overview/setup             | `README.md` (project root)            |

---

## VQMS System Components Reference

### Entry Points (Two Paths Into the System)
1. **Email Path** — Vendor sends email to vendor-support@company.com. Email Ingestion Service fetches via Graph API webhook + reconciliation polling. Includes: MIME parsing, thread correlation (in-reply-to/references/conversationId), vendor identification from sender email, raw S3 storage. Output: ParsedEmailPayload on vqms-email-intake-queue.
2. **Portal Path** — Vendor logs into VQMS portal (Cognito + optional SSO), fills wizard form (type, details, review), submits via POST /queries with JWT auth. Backend validates via Pydantic, generates query_id (VQ-2026-XXXX format), returns query_id instantly. Output: query payload on vqms-query-intake-queue. No thread correlation (portal queries are always NEW). No raw email storage. Vendor ID from JWT, not sender email matching.

### Agents (AI-powered, use Bedrock Claude)
1. **Query Analysis Agent** (formerly Email Analysis Agent) — Analyzes incoming queries from EITHER entry point. Extracts: intent classification, entities (invoice numbers, dates, amounts, PO numbers), urgency level, sentiment, confidence score (0.0–1.0), multi-issue detection, suggested_category. Uses Claude Sonnet 3.5 via Bedrock Integration Service (temperature 0.1, ~1500 tokens in, ~500 tokens out). Confidence >= 0.85 continues to routing; < 0.85 routes to Path C (human review).
2. **Resolution Agent** — Generates full resolution emails when KB has specific factual answers (Path A). Takes: AnalysisResult + KB articles + VendorProfile + SLA + vendor history. Uses Claude Sonnet 3.5 (temperature 0.3, ~3000 tokens in). Produces DraftResponse with concrete facts (dates, amounts, procedures) sourced from KB articles, plus confidence score and source citations.
3. **Communication Drafting Agent** — Writes ACKNOWLEDGMENT-ONLY emails when KB lacks specific facts (Path B). Also drafts resolution emails in Path B after human team provides findings. Uses Claude Sonnet 3.5 via Bedrock Integration Service. Produces DraftEmailPackage with ticket number, SLA statement, next steps — but NO answer content in Path B acknowledgments.
4. **Workflow Orchestration Agent** — The "brain" that decides what happens next: full automation (Path A), human-team resolution (Path B), human review (Path C), update existing ticket, reopen closed ticket, or escalate.

### Deterministic Services (no AI, just business rules)
5. **Email Ingestion Service** — Fetches emails from Exchange Online via Graph API (webhook + polling), parses MIME, stores raw copies in S3, identifies vendor from sender email via Salesforce, performs thread correlation, generates query_id and execution_id, publishes events, queues for orchestration.
6. **Portal Submission Service** — Receives POST /queries from portal frontend, validates via Pydantic (QuerySubmission model), extracts vendor_id from JWT, generates identifiers (query_id, execution_id, correlation_id), stores case_execution, publishes QueryReceived event, queues for orchestration.
7. **Vendor Resolution Service** — Looks up who sent the query by matching against Salesforce CRM records. For email path: three-step fallback (exact email → vendor ID in body → fuzzy name match). For portal path: vendor_id already known from JWT.
8. **Ticket Operations Service** — Creates, updates, or reopens tickets in ServiceNow.
9. **Memory & Context Service** — Loads historical context (past queries, vendor history, episodic memory) to help agents make better decisions.
10. **Routing Service** — Deterministic rules engine that evaluates: confidence >= 0.85, urgency == CRITICAL, existing ticket, BLOCK_AUTOMATION flag. Determines team assignment and SLA target based on vendor tier + urgency.
11. **KB Search Service** — Embeds query text using Amazon Bedrock Titan Embed v2 → vector(1536), performs cosine similarity search against knowledge base articles stored in Amazon S3 vector storage, filtered by category. Returns ranked article matches with similarity scores.

### Gates and Monitors
12. **Quality & Governance Gate** — Validates every outgoing email in two phases. Phase 1 (deterministic, always runs): ticket # format correctness, SLA wording matches vendor tier policy, required sections present, restricted terms scan, response length check (50–500 words), source citations check. Phase 2 (conditional, for HIGH+ priority): PII scan via Amazon Comprehend, tone check (may use LLM). Max 2 re-drafts before routing to human review.
13. **Monitoring & SLA Alerting Service** — Watches ticket age and triggers alerts at 70% (warn resolver), 85% (L1 manager escalation), and 95% (L2 senior escalation) of the SLA deadline. Uses Step Functions wait states. For Path C: SLA clock starts AFTER human review completes — review time does NOT count against SLA.

### Cross-Cutting Services
14. **LLM Factory (`src/llm/factory.py`)** — The ONLY entry point for all LLM and embedding calls. Supports multiple providers with automatic fallback: Bedrock (Claude Sonnet 3.5 + Titan Embed v2) as primary, OpenAI (GPT-4o + text-embedding-3-small) as fallback. Provider mode is configurable via `LLM_PROVIDER` and `EMBEDDING_PROVIDER` env vars. Both embedding providers return 1536-dimensional vectors for pgvector compatibility. Nobody imports from bedrock or openai adapters directly — all calls go through `llm_complete()` and `llm_embed()`.
15. **Audit Trail** — Every action in the system gets logged to `audit.action_log` for compliance and debugging.
16. **Observability** — Structured logging on every service with correlation IDs to trace a query through the entire pipeline.

### Data Infrastructure
- **4 S3 Buckets:** vqms-email-raw-prod, vqms-email-attachments-prod, vqms-audit-artifacts-prod, vqms-knowledge-artifacts-prod (also stores vector embeddings for KB search)
- **5 PostgreSQL Schemas (11 tables):** intake (2), workflow (3), memory (3), audit (2), reporting (1)
- **7 Redis Key Families:** idempotency (7-day TTL), thread, ticket, workflow (24h TTL), vendor (1h TTL), sla, session (8h TTL for portal JWT cache)
- **11 SQS Queues + DLQ:** email-intake, query-intake (portal), analysis, vendor-resolution, ticket-ops, routing, communication, escalation, human-review, audit, dlq
- **20 EventBridge Events:** EmailReceived, EmailParsed, QueryReceived, AnalysisCompleted, VendorResolved, TicketCreated, TicketUpdated, DraftPrepared, ValidationPassed, ValidationFailed, EmailSent, SLAWarning70, SLAEscalation85, SLAEscalation95, VendorReplyReceived, ResolutionPrepared, TicketClosed, TicketReopened, HumanReviewRequired, HumanReviewCompleted

### Three Processing Paths (Critical Decision Points)

**Decision Point 1 — Confidence (at Step 8):**
- Confidence >= 0.85 → continue to Step 9 (Routing + KB Search)
- Confidence < 0.85 → Path C (Low-Confidence Human Review — workflow PAUSES until reviewer acts)

**Decision Point 2 — KB Match Quality (at Step 9, only reached if confidence >= 0.85):**
- KB match >= 80% AND answer has specific facts AND Resolution Agent confidence >= 0.85 → **Path A** (AI drafts resolution email with full answer)
- Otherwise → **Path B** (AI drafts acknowledgment only, human team investigates, AI drafts resolution from team's notes later)

---

## Processing Paths — Runtime Summary (from Solution Flow Document)

This section summarizes the three processing paths for quick reference. For full step-by-step detail, read `docs/references/VQMS_Solution_Flow_Document.docx`.

### Path A: AI-Resolved (Happy Path)
1. Query arrives (email or portal) → ingestion → SQS queue
2. LangGraph Orchestrator loads context (vendor profile from Salesforce, episodic memory, workflow state)
3. Query Analysis Agent (LLM Call #1): intent, entities, urgency, sentiment, confidence
4. Confidence >= 0.85 → continue
5. Parallel: Routing Service (deterministic rules) + KB Search Service (Titan Embed v2 → S3 vector cosine similarity)
6. KB match >= 80% with specific facts → **Path A**
7. Resolution Agent (LLM Call #2): generates full answer email using KB articles as source
8. Quality & Governance Gate: 7 checks (ticket #, SLA wording, sections, restricted terms, length, citations, PII)
9. Ticket created in ServiceNow (team MONITORS, not investigates)
10. Resolution email sent to vendor via Graph API
11. SLA monitor starts (but Path A typically resolves in ~11 seconds)
12. Closure: vendor confirms or auto-close after 5 business days

**Metrics (reference example):** ~11 seconds total, ~$0.033 cost, 2 LLM calls, zero human involvement.

### Path B: Human-Team-Resolved
1–5. Same as Path A through KB Search
6. KB does NOT have specific facts → **Path B**
7. Communication Drafting Agent: generates ACKNOWLEDGMENT email only (no answer, just "we received it, ticket is INC..., team is reviewing")
8. Quality & Governance Gate: same 7 checks
9. Ticket created in ServiceNow (team MUST investigate)
10. Acknowledgment email sent to vendor
11. SLA monitor starts — more critical here because human team has real investigation time
12. Human team investigates (opens ServiceNow ticket, uses internal systems to find answer)
13. Team marks ticket RESOLVED with resolution notes
14. ResolutionPrepared event triggers Communication Drafting Agent → generates resolution email from team's notes (LLM Call #2)
15. Quality gate validates again → resolution email sent to vendor
16. Closure: same as Path A

**Metrics:** ~10 seconds for acknowledgment, minutes to hours for resolution (depends on team), ~$0.05 total cost.

### Path C: Low-Confidence Human Review
1–3. Same as Path A through Query Analysis Agent
4. Confidence < 0.85 → **Path C** (workflow PAUSES entirely)
5. TriagePackage created: original query + AI's analysis + confidence breakdown + suggested routing + suggested draft
6. Package pushed to vqms-human-review-queue
7. Step Functions pauses via callback token pattern — NOTHING happens until human acts
8. Human reviewer logs in (Cognito auth), reviews TriagePackage, corrects classification/vendor/routing
9. Reviewer submits → Step Functions SendTaskSuccess → workflow RESUMES with corrected data
10. Corrected data now has HIGH confidence (human-validated) → continues to Step 5 (Routing + KB Search)
11. From here, follows Path A or Path B depending on KB match quality
12. **SLA clock starts AFTER human review completes** — review time does NOT count against SLA

**Metrics:** Review adds minutes to hours (reviewer availability), then ~$0.03–$0.05 depending on Path A or B.

### Key Path Differences for Implementation

| Aspect | Path A | Path B | Path C |
|--------|--------|--------|--------|
| LLM calls | 2 (analysis + resolution) | 2–3 (analysis + ack + resolution from notes) | Same as A or B after review |
| Ticket purpose | Team monitors | Team investigates | Depends on resumed path |
| Email type | Resolution (full answer) | Acknowledgment, then resolution later | Depends on resumed path |
| SLA starts | At ticket creation | At ticket creation | AFTER human review completes |
| Human involvement | None | Investigation team | Reviewer first, then possibly team |
| KB used | Yes (source of facts) | No (lacks specifics) | Depends on resumed path |

---

## API Endpoints (from Implementation Plan)

All endpoints are served by FastAPI behind API Gateway with Cognito JWT authorization.

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/queries` | POST | Portal query submission (Step P6) | Vendor JWT |
| `/queries/{id}` | GET | Query status + detail for vendor dashboard | Vendor JWT |
| `/dashboard/kpis` | GET | Portal dashboard KPIs (Step P2) | Vendor JWT |
| `/triage/{id}/review` | POST | Human reviewer submits corrections (Step 8C.2) | Reviewer JWT |
| `/triage/queue` | GET | List pending triage packages for review portal | Reviewer JWT |
| `/webhooks/ms-graph` | POST | MS Graph email notification webhook (Step E2.1) | HMAC/Token |
| `/webhooks/servicenow` | POST | ServiceNow resolution-prepared callback (Step 15) | HMAC/Token |
| `/admin/metrics` | GET | SLA, path, cost reporting metrics | Admin JWT |

**Security rule:** `vendor_id` is always extracted from JWT claims, NEVER from request payload.

---

## Architecture-to-Code Mapping (from Implementation Plan)

| Document Component | Code Module | Phase |
|---|---|---|
| Email Ingestion (Steps E1-E2) | `src/services/email_intake.py` | Phase 2 |
| Portal Submission (Steps P1-P6) | `src/api/routes/queries.py` + `src/services/portal_submission.py` | Phase 2 |
| LangGraph Orchestrator (Step 7) | `src/orchestration/graph.py` | Phase 3 |
| Query Analysis Agent (Step 8) | `src/agents/query_analysis.py` | Phase 3 |
| Routing + KB Search (Step 9) | `src/services/routing.py` + `src/services/kb_search.py` | Phase 3 |
| Resolution Agent (Step 10A) | `src/agents/resolution.py` | Phase 4 |
| Communication Agent (Step 10B) | `src/agents/communication_drafting.py` | Phase 4 |
| Quality Gate (Step 11) | `src/gates/quality_governance.py` | Phase 4 |
| Ticket + Email Delivery (Step 12) | `src/services/ticket_ops.py` + `src/adapters/graph_api.py` | Phase 4 |
| Path C Triage (Steps 8C.1-8C.3) | `src/api/routes/triage.py` + `src/orchestration/step_functions.py` | Phase 5 |
| SLA Monitor (Step 13) | `src/monitoring/sla_alerting.py` | Phase 6 |
| Closure/Reopen (Step 16) | `src/services/` (closure module) | Phase 6 |
| Vendor Portal (React) | `frontend/src/` | Phase 7 |

---

## Module Breakdown with Dependencies (from Implementation Plan)

| Module | Responsibility | Key Dependencies |
|--------|---------------|------------------|
| email_intake | MS Graph webhook/polling, MIME parsing, vendor identification, thread correlation, idempotency, SQS publishing | MS Graph API, Salesforce CRM, Redis, PostgreSQL, SQS, S3 |
| portal_intake | JWT-based query submission, Pydantic validation, ID generation, idempotency, SQS publishing | API Gateway, Cognito, Redis, PostgreSQL, SQS |
| orchestrator | LangGraph workflow graph: context loading, agent routing, parallel KB+routing, confidence branching, Path A/B/C dispatch | LangGraph, Redis, PostgreSQL, Salesforce CRM, SQS consumer |
| query_analysis | LLM Call #1: intent classification, entity extraction, confidence scoring, sentiment analysis | Bedrock (Claude Sonnet 3.5), S3 (prompt templates), PostgreSQL |
| routing | Deterministic rules engine: confidence, urgency, team assignment, SLA calculation | PostgreSQL (routing_decision table) |
| kb_search | Embedding + cosine similarity search over S3 vector store, category-filtered | Bedrock (Titan Embed v2), S3 vector storage |
| resolution | LLM Call #2: draft resolution email from KB facts + vendor context | Bedrock (Claude Sonnet 3.5), S3 (templates) |
| communication | LLM Call: draft acknowledgment email (Path B) or resolution email from human notes (Step 15) | Bedrock (Claude Sonnet 3.5), S3 (templates) |
| quality_gate | 7-check validation: ticket format, SLA wording, required sections, restricted terms, length, source citations, PII scan | Amazon Comprehend, rule engine |
| ticket | ServiceNow ticket creation and status management | ServiceNow ITSM API |
| email_delivery | Send validated emails via MS Graph /sendMail | MS Graph API |
| triage | Path C: create TriagePackage, Step Functions callback pattern, human review portal backend | SQS, Step Functions, PostgreSQL |
| sla_monitor | Background SLA tracking: 70/85/95% escalation thresholds, Step Functions timer | Step Functions, Redis, EventBridge, SQS (escalation queue) |
| closure | Closure/reopen logic: confirmation detection, 5-day auto-close, reopen vs new-ticket decision | Bedrock (intent classification), ServiceNow, Step Functions |
| vendor_profile | Salesforce CRM adapter: load vendor tier, risk flags, account manager, payment terms with Redis caching | Salesforce CRM API, Redis |
| episodic_memory | Load/save vendor query history from memory.episodic_memory for context enrichment | PostgreSQL |

---

## Database Design Strategy (from Implementation Plan)

### PostgreSQL Schema Namespaces
- **intake:** `email_messages`, `email_attachments` (email path metadata and S3 keys)
- **workflow:** `case_execution` (central state table: status, analysis_result, routing), `ticket_link`, `routing_decision`
- **audit:** `action_log` (every state transition with correlation_id, timestamp, actor, action), `validation_results`
- **memory:** `episodic_memory` (vendor query history indexed by vendor_id), `vendor_profile_cache`, `embedding_index`
- **reporting:** `sla_metrics`, path_metrics, cost_metrics

### Redis Key Families
- `vqms:idempotency:<id>` — 7-day TTL, prevents duplicate processing
- `vqms:session:<token>` — 8h TTL, portal JWT session cache
- `vqms:vendor:<id>` — 1h TTL, Salesforce vendor profile cache
- `vqms:workflow:<execution_id>` — 24h TTL, current workflow state
- `vqms:sla:<ticket_id>` — SLA state tracking
- `vqms:dashboard:<vendor_id>` — 5-min TTL, portal KPI cache
- `vqms:thread:<message_id>` — Thread correlation lookup

### S3 Buckets
- `vqms-email-raw-prod` — raw .eml files (compliance)
- `vqms-email-attachments-prod` — attachment files
- `vqms-knowledge-artifacts-prod` — prompt templates, KB articles, prompt audit snapshots, vector embeddings
- `vqms-audit-artifacts-prod` — audit artifacts

---

## Integration Strategy (from Implementation Plan)

All external integrations must be built behind Protocol/ABC interfaces so they can be stubbed during development and testing. Concrete adapters implement these protocols:

1. **Salesforce CRM Adapter** — Vendor lookup by vendor_id, contact matching by email, fuzzy name match. Used in Steps E2.5 and 7.3.
2. **ServiceNow ITSM Adapter** — Ticket creation (POST /api/now/table/incident), status updates, work note reads. Used in Steps 12A, 12B, 14, 15.
3. **Microsoft Graph API Adapter** — Webhook subscription for email detection, message fetch (GET /messages/{id}), email sending (/sendMail). Used in Steps E2.1, 12A, 12B, 15, and closure detection.
4. **Amazon Bedrock Adapter** — LLM inference (Claude Sonnet 3.5) and embedding (Titan Embed v2). Used in Steps 8, 9B, 10A, 10B, 15.
5. **Amazon Comprehend Adapter** — PII detection for the Quality Gate. Used in Steps 11A and 11B.

**Build stubs first.** Each adapter should have a corresponding mock/stub that returns realistic test data, allowing the full pipeline to be exercised end-to-end locally before connecting real services.

---

## Error Handling Strategy (from Implementation Plan)

- Use domain-specific exception classes (e.g., `VendorNotFoundError`, `KBSearchTimeoutError`, `QualityGateFailedError`, `SLABreachedError`)
- All SQS consumers must implement DLQ handling with 3 retries (vqms-dlq)
- Idempotency guards on both entry points (Redis key with 7-day TTL) prevent duplicate processing
- Quality Gate failures trigger DRAFT_REJECTED status and route to human review — never silently fail
- LLM parsing failures (Pydantic validation of AnalysisResult or DraftResponse) retry once, then route to Path C (low confidence)
- External API failures (Salesforce, ServiceNow, MS Graph) use exponential backoff with circuit breaker pattern (simple retry in dev mode)

---

## Validation Strategy (from Implementation Plan)

Pydantic models enforce validation at every boundary:
- **QuerySubmission:** validates portal intake payload (type, subject, description, priority, reference)
- **ParsedEmailPayload:** validates parsed MIME data (message-id, sender, recipients, subject, body)
- **AnalysisResult:** validates LLM output (intent_classification, extracted_entities, urgency_level, sentiment, confidence_score, multi_issue_detected, suggested_category)
- **DraftResponse:** validates generated email drafts (subject, body, confidence, sources)
- **TriagePackage:** validates Path C triage data including AI analysis, vendor match, suggested routing, and confidence breakdown
- **Quality Gate** performs 7 deterministic checks on every outbound draft before delivery

---

## Security Considerations (from Implementation Plan + Coding Standards)

- AWS Cognito (vqms-agent-portal-users) handles all authentication. JWTs include vendor_id, role (VENDOR/REVIEWER/ADMIN), and scopes (queries.own, kb.read, prefs.own)
- **vendor_id is extracted from JWT claims, NEVER from request payload** (Step P6 explicitly notes this)
- API Gateway with Cognito Authorizer validates every request before it reaches FastAPI
- PII detection via Amazon Comprehend in Quality Gate ensures personal data is stripped from outbound emails
- All raw emails and attachments stored in S3 for compliance. Prompt snapshots stored for LLM audit trail
- Redis keys use TTLs to prevent stale data accumulation
- Secrets: env vars or vault; rotate keys; least privilege; never commit secrets in code
- Encrypt at rest/in transit; redact PII before LLM; honor data residency
- Prompt injection defense: do not execute instructions from user documents; enforce policy for tools
- Content moderation: filter inputs/outputs; route risky content to human-in-the-loop

---

## Logging and Monitoring Strategy (from Implementation Plan)

- **Correlation ID** (UUID v4) must be generated at intake and propagated through every service call, database write, and external API request
- JSON structured logging with fields: `correlation_id`, `agent_role`, `tool`, `latency_ms`, `tokens_in/out`, `cost`, `model`, `prompt_id`, `policy_decisions`, `safety_flags`
- Never log PII or secrets
- EventBridge events (20 event types) provide the event-driven audit trail
- `audit.action_log` table records every state transition with correlation_id, timestamp, actor, and action
- SLA metrics tracked in `reporting.sla_metrics` for dashboard and reporting
- LLM cost tracking: token counts and cost per call stored per execution (~$0.012 for analysis, ~$0.021 for resolution)

---

## Testing Strategy (from Implementation Plan + Coding Standards)

- **Unit Tests:** Every Pydantic model, every agent, every service function. Mock all external dependencies.
- **Integration Tests:** Full pipeline execution with stubbed adapters: submit query, verify it flows through Path A, B, and C correctly.
- **Contract Tests:** Verify Salesforce, ServiceNow, and MS Graph adapter contracts match real API schemas. Strict Pydantic models for tool I/O.
- **End-to-End Tests:** Submit via portal and email, verify ticket creation, email delivery, SLA tracking, and closure.
- **Quality Gate Tests:** Test all 7 checks with passing and failing drafts. Verify PII detection blocks sensitive data.
- **SLA Timer Tests:** Verify 70/85/95% escalation thresholds fire correctly. Test Path C SLA clock behavior (starts after review, not before).
- **Load Tests:** Concurrent query submission via both entry points. Verify idempotency, Redis caching, and SQS throughput.
- **LLM-specific Evaluation:**
  - Golden sets: curated inputs with expected constraints (faithfulness, completeness, style, safety)
  - RAG eval: retrieval precision@k, source diversity, citation accuracy
  - Agent eval: steps ≤ max hops, cost ≤ budget, policy adherence
  - Use RAGAS and LangChain evaluators for LLM-as-a-judge scoring

---

## Prerequisite Files (Create If Missing)

Before starting any phase, make sure these files exist. If they don't, create them:

```
tasks/todo.md          → Start with: "# VQMS Task Tracker\n\n## Current Phase: 1\n"
tasks/lessons.md       → Start with: "# VQMS Lessons Learned\n"
Flow.md                → Runtime walkthrough of what is built (update after every phase)
README.md              → Project overview and setup (update after every phase)
docs/references/       → Must contain the four reference files (coding standards + architecture doc + solution flow doc + implementation plan)
.env.copy              → Copy the template from the Environment Variables section below
.gitignore             → Must include: .env, __pycache__/, *.pyc, .venv/, data/logs/, data/vector_store/, data/storage/, uv.lock
```

---

## Build Order — 8 Phases (from Implementation Plan)

Follow this exact phase order. Do NOT skip phases or build out of sequence. Each phase has gate criteria that must be met before proceeding.

### Phase 1: Foundation and Data Layer
**Purpose:** Establish the database schema, Pydantic models, Redis key schemas, and project skeleton that all subsequent phases depend on.

**What to Build:**
- PostgreSQL schema (intake, workflow, routing, audit, memory, reporting namespaces)
- All Pydantic models (QuerySubmission, ParsedEmailPayload, AnalysisResult, DraftResponse, TriagePackage, RoutingDecision, TicketRecord, SLAMetrics, AgentMessage, ToolCall, Budget)
- Redis key schema definitions
- FastAPI project structure with health check endpoint
- Alembic migration setup
- `.env` configuration

**Gate Criteria:** All models pass validation tests. Database migrations run cleanly. Health check returns 200.

### Phase 2: Intake Services (Email + Portal)
**Purpose:** Build both entry points so queries can enter the system. Both paths produce an SQS message with identical payload structure.

**What to Build:**
- (A) Portal intake: POST /queries endpoint with JWT auth, Pydantic validation, ID generation, idempotency check, PostgreSQL insert, EventBridge publish, SQS enqueue, HTTP 201 response
- (B) Email intake: MS Graph webhook receiver, MIME parser, vendor identification (Salesforce lookup + fallback chain), thread correlation, raw email S3 storage, identical SQS enqueue

**Gate Criteria:** Both paths produce valid SQS messages. Idempotency works. Vendor ID resolved (or UNRESOLVED for email). Thread correlation returns NEW/EXISTING_OPEN/REPLY_TO_CLOSED.

### Phase 3: AI Pipeline Core (Steps 7–9)
**Purpose:** Build the LangGraph orchestrator, Query Analysis Agent (LLM Call #1), routing engine, and KB search. This is the brain of VQMS.

**What to Build:**
- (A) LangGraph graph with SQS consumer, context loading node (Step 7)
- (B) Query Analysis Agent (Step 8: prompt template → Bedrock Claude → parse AnalysisResult → confidence branching at 0.85)
- (C) Routing Service (Step 9A: deterministic rules engine)
- (D) KB Search Service (Step 9B: embed query → cosine similarity on S3 vector store)
- (E) Decision point: KB match >= 80% routes to Path A; otherwise Path B

**Gate Criteria:** LangGraph graph executes end-to-end. Analysis produces valid AnalysisResult. Routing produces valid RoutingDecision. KB search returns ranked articles. Confidence branching correctly divides Path A/B/C.

### Phase 4: Response Generation and Delivery (Steps 10–12)
**Purpose:** Build the Resolution Agent (Path A), Communication Agent (Path B), Quality Gate, ticket creation, and email delivery. After this phase, the happy path works end-to-end.

**What to Build:**
- (A) Resolution Agent (Step 10A): LLM Call #2 using KB facts
- (B) Communication Drafting Agent (Step 10B): acknowledgment-only email
- (C) Quality & Governance Gate (Step 11): 7-check validation
- (D) ServiceNow ticket creation (Step 12)
- (E) Email delivery via MS Graph /sendMail (Step 12)
- (F) Status updates: PostgreSQL, Redis, EventBridge events

**Gate Criteria:** Both Path A and Path B produce validated emails. Quality Gate catches PII, restricted terms, and format violations. Ticket created in ServiceNow. Email sent via MS Graph.

### Phase 5: Human Review and Path C (Steps 8C.1–8C.3)
**Purpose:** Build the low-confidence human review workflow.

**What to Build:**
- (A) TriagePackage creation with Step Functions callback token and pause
- (B) Human review API: GET /triage/queue, POST /triage/{id}/review
- (C) Workflow resume via SendTaskSuccess with corrected data

**Gate Criteria:** Workflow pauses on low confidence. Triage package contains all required fields. Reviewer corrections resume workflow through standard pipeline.

### Phase 6: SLA Monitoring and Closure (Steps 13–16)
**Purpose:** Build SLA monitoring, Path B human investigation flow, and closure/reopen logic.

**What to Build:**
- (A) SLA Monitor: Step Functions timer with 70/85/95% escalation
- (B) Path B resolution flow: ServiceNow webhook → Communication Agent → Quality Gate → email delivery
- (C) Closure logic: confirmation detection, 5-day auto-close, reopen vs new-linked-ticket
- (D) Episodic memory: save closure summary for future context

**Gate Criteria:** SLA escalation fires at correct thresholds. Path B end-to-end works. Auto-closure works. Reopen creates correct ticket state. Episodic memory saved.

### Phase 7: Frontend Portal (React)
**Purpose:** Build the React vendor portal and human review triage portal.

**What to Build:**
- (A) Vendor portal: login (Cognito/SSO), dashboard with KPIs, query wizard, query detail/tracking
- (B) Triage review portal: reviewer login, triage queue, correction form
- (C) Admin dashboard: SLA metrics, path distribution, cost tracking

**Gate Criteria:** Vendor can submit and track queries. Reviewer can review and correct triage packages. Dashboard shows real KPIs.

### Phase 8: Integration Testing, Hardening, and Production Readiness
**Purpose:** Replace all stubs with real integrations, run end-to-end tests, harden for production.

**What to Build:**
- (A) Replace all stub adapters with real connections
- (B) End-to-end test suite for all 3 paths
- (C) Load testing
- (D) Security audit
- (E) Monitoring setup
- (F) Documentation (API docs, runbook, architecture diagrams)

**Gate Criteria:** All 3 paths work with real services. Reference scenario (Rajesh, TechNova, Path A, ~11s, ~$0.033) works end-to-end. Load test passes. Security audit clean.

---

## Development Code Examples

These examples show the level of simplicity and commenting we expect in development code.

### Example 1: A Simple Pydantic Model (Clear, Commented)

```python
"""Module: models/vendor.py

Pydantic models for vendor data in VQMS.

These models define the shape of vendor information as it flows
through the pipeline — from Salesforce lookup to agent decisions.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VendorTier(str, Enum):
    """Vendor importance level — determines SLA targets and escalation speed.

    Tier is pulled from Salesforce during vendor resolution.
    Higher tiers get faster SLA targets and earlier escalations.
    """

    PLATINUM = "platinum"  # Most important — fastest SLA, immediate escalation
    GOLD = "gold"          # High priority — shorter SLA than standard
    SILVER = "silver"      # Medium priority
    STANDARD = "standard"  # Default tier for unclassified vendors


class VendorMatch(BaseModel):
    """Result of looking up a vendor in Salesforce.

    The Vendor Resolution Service produces this after trying
    to match an email sender against Salesforce CRM records.
    """

    # Vendor identity
    vendor_id: str = Field(description="Salesforce Account ID")
    vendor_name: str = Field(description="Company name from Salesforce")
    vendor_tier: VendorTier = Field(
        default=VendorTier.STANDARD,
        description="SLA tier — drives response time targets",
    )

    # How we found this vendor
    match_method: str = Field(
        description="How the vendor was matched: "
        "EMAIL_EXACT, VENDOR_ID_BODY, or NAME_SIMILARITY",
    )
    match_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How confident we are in this match (0.0 to 1.0)",
    )

    # Flags for routing decisions
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Any risk flags from Salesforce (e.g., 'payment_overdue')",
    )
```

### Example 2: A Simple Service Function (Easy to Follow)

```python
"""Module: services/vendor_resolution.py

Vendor Resolution Service for VQMS.

Matches an email sender to a vendor in Salesforce CRM.
Uses a three-step fallback strategy:
  1. Exact email match
  2. Vendor ID extracted from email body
  3. Fuzzy name similarity match

For portal queries, vendor_id is already known from the JWT token,
so this service is used primarily for enrichment (tier, risk flags,
account manager).

Corresponds to Step E2.5 (email path) and Step 7.3 (context loading)
in the VQMS Solution Flow Document, and Step 5B in the Architecture Doc.
"""

from __future__ import annotations

import logging

from src.models.vendor import VendorMatch, VendorTier

logger = logging.getLogger(__name__)


# Confidence thresholds for each matching method
# Exact email matches are highly reliable, name similarity less so
EXACT_EMAIL_CONFIDENCE = 0.95
VENDOR_ID_CONFIDENCE = 0.90
NAME_SIMILARITY_CONFIDENCE = 0.60

# Below this confidence, we flag the match as unresolved
# and the orchestrator will route to human review
MINIMUM_MATCH_CONFIDENCE = 0.50


class VendorResolutionError(Exception):
    """Raised when vendor lookup fails unexpectedly.

    This is NOT raised for "vendor not found" — that is a normal
    business case that returns a low-confidence VendorMatch.
    This is for actual failures: Salesforce API down, auth error, etc.
    """


async def resolve_vendor_from_email(
    sender_email: str,
    email_body: str,
    *,
    correlation_id: str | None = None,
) -> VendorMatch:
    """Find which vendor sent this email by checking Salesforce.

    Tries three matching strategies in order. Returns the best
    match found, even if confidence is low. The orchestrator
    decides whether the confidence is high enough to proceed
    automatically or route to human review.

    Args:
        sender_email: The email address of the person who sent
            the vendor query (e.g., "john@acme-corp.com").
        email_body: Plain text body of the email. Used as a fallback
            to look for vendor ID patterns like "Vendor ID: V12345".
        correlation_id: Tracing ID for this request.

    Returns:
        VendorMatch with the best match found. If no match at all,
        returns a VendorMatch with match_confidence=0.0 and
        match_method="UNRESOLVED".

    Raises:
        VendorResolutionError: If Salesforce API is unreachable
            or returns an unexpected error.
    """
    logger.info(
        "Starting vendor resolution",
        extra={
            "sender_email": sender_email,
            "correlation_id": correlation_id,
        },
    )

    # TODO: Implement in Phase 2
    # Step 1: Try exact email match in Salesforce Contact.Email
    # Step 2: If no match, look for vendor ID pattern in email body
    # Step 3: If no match, try fuzzy name matching against Salesforce Account.Name
    # Step 4: If all fail, return UNRESOLVED with confidence 0.0
    raise NotImplementedError("Phase 2 implementation pending")
```

### Example 3: A Simple Test (Readable, No Complex Fixtures)

```python
"""Tests for vendor resolution service.

These tests verify the vendor matching logic using simple
mock data. No real Salesforce calls are made — all API
responses are mocked.
"""

import pytest

from src.models.vendor import VendorMatch, VendorTier


class TestVendorMatch:
    """Test the VendorMatch pydantic model validation."""

    def test_valid_vendor_match_creates_successfully(self):
        """A VendorMatch with all required fields should be created without errors."""
        match = VendorMatch(
            vendor_id="SF-ACC-001",
            vendor_name="Acme Corporation",
            vendor_tier=VendorTier.GOLD,
            match_method="EMAIL_EXACT",
            match_confidence=0.95,
        )

        assert match.vendor_id == "SF-ACC-001"
        assert match.vendor_name == "Acme Corporation"
        assert match.vendor_tier == VendorTier.GOLD
        assert match.match_confidence == 0.95

    def test_default_tier_is_standard(self):
        """When no tier is specified, the vendor should default to STANDARD."""
        match = VendorMatch(
            vendor_id="SF-ACC-002",
            vendor_name="Unknown Corp",
            match_method="NAME_SIMILARITY",
            match_confidence=0.60,
        )

        assert match.vendor_tier == VendorTier.STANDARD

    def test_confidence_must_be_between_zero_and_one(self):
        """Confidence scores outside 0.0-1.0 should raise a validation error."""
        with pytest.raises(ValueError):
            VendorMatch(
                vendor_id="SF-ACC-003",
                vendor_name="Bad Corp",
                match_method="EMAIL_EXACT",
                match_confidence=1.5,  # Invalid: above 1.0
            )

    def test_risk_flags_default_to_empty_list(self):
        """If no risk flags are provided, the list should be empty (not None)."""
        match = VendorMatch(
            vendor_id="SF-ACC-004",
            vendor_name="Safe Corp",
            match_method="EMAIL_EXACT",
            match_confidence=0.90,
        )

        assert match.risk_flags == []
        assert isinstance(match.risk_flags, list)
```

---

## Scope Control

### What to DO (development mode)
- Create every file with proper module docstrings, imports, and type hints
- Write clear, commented function signatures with descriptive docstrings
- Use `TODO` comments with phase references for unimplemented logic
- Create all Pydantic models with field descriptions and validation rules
- Create all SQL migration files with proper schema definitions
- Write simple, readable unit tests for every model and utility function
- Follow the build order — never jump ahead to later phases

### What NOT to do (save for production)
- Do NOT create deployment files (Dockerfile, CDK, SAM, CloudFormation, Terraform, CI/CD) until explicitly approved
- Do NOT write code that creates, deletes, or modifies AWS resources (limited office IAM privileges)
- Do NOT assume real AWS credentials are available — always provide local/mock fallback via adapter pattern
- Do NOT call AWS Secrets Manager directly — read secrets from environment variables in dev
- Do NOT build complex abstraction layers (Protocol classes, factory patterns) until needed
- Do NOT add OpenTelemetry instrumentation on every function — basic logging is enough for now
- Do NOT implement full circuit breaker patterns — simple retry with backoff is sufficient
- Do NOT build rate limiters with token bucket algorithms — basic semaphore limits are fine
- Do NOT optimize for performance — optimize for readability and correctness first

---

## Common Mistakes to Avoid (from Architecture Doc + Solution Flow Doc + Implementation Plan)

- Do not start with UI or dashboards — the value is in the backend pipeline
- Do not tightly couple orchestration with integrations — services communicate through clean interfaces
- Do not mix parsing logic with business logic — email parsing is mechanical, business decisions happen in agents
- Do not call Bedrock directly from every module — all LLM calls AND embedding calls go through the Bedrock Integration Service
- Do not create a ticket before thread correlation is checked — always check for existing tickets first
- Do not skip idempotency — every external write must be idempotent (Redis keys, check-before-create)
- Do not build every branch before one happy path works — get new-email-to-acknowledgment working first
- Do not leave audit logging until later — every side-effect writes to audit.action_log from day one
- Do not hardcode prompts across files — versioned templates in `prompts/` loaded by Bedrock Integration Service
- Do not forget dead letter queue handling — every SQS queue has vqms-dlq as its DLQ
- Do not write local/mock fallback code in adapters — all adapters connect to real cloud services; use `moto` for tests only
- Do not write boto3 resource creation calls (create_bucket, create_queue, etc.) — infra is pre-provisioned by the DevOps team
- Do not treat portal and email paths as separate systems — they MUST converge into the same unified pipeline at the orchestrator
- Do not confuse Path A and Path B email types — Path A sends RESOLUTION (full answer), Path B sends ACKNOWLEDGMENT (no answer, just confirmation)
- Do not start SLA timers for Path C before human review completes — review time is excluded from SLA
- Do not send any email to the vendor during Path C pause — workflow is fully stopped until reviewer acts
- Do not skip KB search even for Path B — the KB search result (low/no match) is what DETERMINES it is Path B
- Do not use the Resolution Agent for Path B acknowledgments — Resolution Agent is Path A only; Communication Drafting Agent handles Path B
- Do not extract vendor_id from request payload — always from JWT claims
- Do not silently swallow Quality Gate failures — trigger DRAFT_REJECTED status and route to human review

---

## Design Checklists (from Coding Standards)

### Agent Design Checklist
- [ ] Single responsibility and focused tool scope
- [ ] System prompt minimal, task-oriented, and versioned
- [ ] Self-check and reviewer loop defined
- [ ] Stop conditions and max hops defined
- [ ] Policy enforcement integrated

### RAG Checklist
- [ ] Proper chunking by semantic boundaries with metadata (document_id, chunk_id, source_url, timestamp)
- [ ] Filter strategies defined (category, tenant, language, freshness)
- [ ] Retrieval metrics instrumented
- [ ] Source citations enforced
- [ ] PII redaction before index

### Ops Checklist (for production readiness — Phase 8)
- [ ] Rate limits per provider/tenant
- [ ] Circuit breakers configured
- [ ] Budget manager active
- [ ] Observability (logs/traces/metrics)
- [ ] Runbooks and rollback plan

---

## Risks, Dependencies, and Assumptions (from Implementation Plan)

### Risks
- **Bedrock latency:** LLM calls target ~3-4 seconds per call. Latency spikes could impact Path A's ~11-second target. Mitigation: set timeout and fallback to Path B if resolution LLM call exceeds threshold.
- **KB quality:** Path A resolution quality depends entirely on KB article accuracy and coverage. Poor KB articles produce incorrect AI responses despite high confidence. Mitigation: KB article review process and quality scoring.
- **Salesforce vendor matching:** Email path depends on matching sender email to Salesforce contacts. Vendors using personal email may result in UNRESOLVED. Mitigation: fallback chain (email → body extraction → fuzzy name match).
- **SLA timer accuracy:** Step Functions wait states have minimum granularity. Very short SLAs may not trigger escalation thresholds accurately. Mitigation: test with real SLA windows.

### Dependencies
- AWS account with Bedrock access (Claude Sonnet 3.5 and Titan Embed v2 model access)
- Salesforce CRM instance with vendor master data and API credentials
- ServiceNow ITSM instance with incident table access
- Microsoft 365 tenant with Graph API permissions for shared mailbox and sendMail
- Cognito user pool (vqms-agent-portal-users) configured with vendor and reviewer roles
- Company SSO (Okta or Azure AD) federated with Cognito for vendor authentication
- Knowledge base articles loaded into S3 vector store with embeddings

### Assumptions
- The confidence threshold of 0.85 for Path A/B vs Path C is a **configurable parameter**, not hardcoded
- KB articles are pre-embedded and stored in S3 (embedding pipeline is outside scope of this plan)
- Prompt templates (query-analysis, resolution, acknowledgment) are pre-authored and versioned in S3
- The 7-check Quality Gate rules are defined in **configuration**, not hardcoded
- SLA tiers and escalation thresholds are loaded from **configuration** (Silver + High = 4 hours)

---

## Dependencies

### Canonical Dependencies for VQMS

```
# ===========================
# Core Framework
# ===========================
fastapi
uvicorn[standard]
pydantic>=2.0
pydantic-settings

# ===========================
# AI / LLM — Amazon Bedrock + LangChain/LangGraph
# ===========================
boto3
botocore
langchain>=0.3
langchain-aws
langchain-community
langgraph>=0.2
langsmith

# ===========================
# Database — PostgreSQL + pgvector
# ===========================
asyncpg
psycopg2-binary
pgvector
sqlalchemy[asyncio]
alembic
sshtunnel                     # SSH tunnel to bastion host for RDS access

# ===========================
# Cache — Redis
# ===========================
redis[hiredis]

# ===========================
# API & Web — External Service Adapters
# ===========================
httpx
aiohttp
requests
msal                          # Microsoft Graph API auth
simple-salesforce             # Salesforce CRM adapter
pysnow                        # ServiceNow ITSM adapter

# ===========================
# Email Parsing
# ===========================
python-multipart
email-validator

# ===========================
# Observability & Logging
# ===========================
structlog
opentelemetry-api
opentelemetry-sdk
opentelemetry-instrumentation-fastapi
opentelemetry-exporter-otlp
aws-xray-sdk

# ===========================
# Templating & Prompts
# ===========================
jinja2

# ===========================
# Security & Compliance
# ===========================
cryptography
python-jose[cryptography]

# ===========================
# Utilities
# ===========================
python-dotenv
pyyaml
tenacity                      # Retry with exponential backoff
python-dateutil
orjson                        # Fast JSON serialization

# ===========================
# Testing
# ===========================
pytest
pytest-asyncio
pytest-cov
pytest-mock
moto[s3,sqs,events,stepfunctions]   # AWS service mocking
fakeredis                         # Redis mocking for tests without real Redis
ragas                         # RAG evaluation framework
deepeval                      # LLM-as-a-judge evaluation

# ===========================
# Dev Tools
# ===========================
ruff
mypy
black
isort
pre-commit
```

> **Note:** The project uses `uv` as the package manager. The actual source of truth for dependencies is `pyproject.toml`. If someone cannot use `uv`, they can install from `requirements.txt` via `pip install -r requirements.txt`.

### requirements.txt Maintenance Rule (ALWAYS ENFORCED)

The requirements.txt file must ALWAYS stay in sync with the codebase. Follow these rules:

- **When installing a new package:** Always use `uv add <package>` to install, then immediately add the package to requirements.txt under the correct category group with a comment explaining what it is used for.
- **When removing a package:** Remove it from both pyproject.toml and requirements.txt.
- **When creating any new .py file:** After writing the file, check if it imports any new third-party package. If yes, add it to requirements.txt immediately.
- **Before finishing any task:** Run a quick scan of all imports and verify requirements.txt has every third-party package listed.
- **Never leave requirements.txt out of date.** If you install something and forget to add it to requirements.txt, that is a mistake — log it in tasks/lessons.md.
- **Format:** Group packages by category with comment headers. One package per line. Add a short inline comment for packages whose purpose is not obvious.

---

## Environment Variables (.env.copy)

```env
# ============================================================
# VQMS Environment Variables Template
# Copy this file to .env and fill in real values
# NEVER commit .env to git — only .env.copy is committed
# ============================================================

# ===========================
# APPLICATION
# ===========================
APP_ENV=development                          # development | staging | production
APP_NAME=vqms
APP_VERSION=1.0.0
APP_DEBUG=true                               # true in dev, false in production
APP_PORT=8000
LOG_LEVEL=DEBUG                              # DEBUG | INFO | WARNING | ERROR
CORRELATION_ID_HEADER=X-Correlation-ID

# ===========================
# SECRETS BACKEND
# ===========================
APP_SECRETS_BACKEND=env                      # "env" or "secretsmanager" — use .env in dev

# ===========================
# AWS GENERAL
# ===========================
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<your-aws-access-key>
AWS_SECRET_ACCESS_KEY=<your-aws-secret-key>
AWS_SESSION_TOKEN=<optional-session-token>
AWS_ACCOUNT_ID=<your-aws-account-id>

# ===========================
# AMAZON BEDROCK (LLM)
# ===========================
# All LLM calls go through Bedrock Integration Service
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_REGION=us-east-1
BEDROCK_MAX_TOKENS=4096
BEDROCK_TEMPERATURE=0.1
BEDROCK_FALLBACK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
BEDROCK_MAX_RETRIES=3
BEDROCK_TIMEOUT_SECONDS=30

# ===========================
# AMAZON BEDROCK (Embeddings)
# ===========================
# Used by KB Search Service for query embedding
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
BEDROCK_EMBEDDING_DIMENSIONS=1536

# ===========================
# POSTGRESQL DATABASE
# ===========================
# Primary database — 5 schemas, 11 tables
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=vqms
POSTGRES_USER=<your-db-user>
POSTGRES_PASSWORD=<your-db-password>
POSTGRES_POOL_MIN=5
POSTGRES_POOL_MAX=20
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}

# ===========================
# SSH TUNNEL (Bastion → RDS)
# ===========================
# RDS is not directly accessible — all DB connections go through SSH tunnel
SSH_HOST=<bastion-host-ip-or-dns>
SSH_PORT=22
SSH_USERNAME=<ssh-username>
SSH_PRIVATE_KEY_PATH=<path-to-private-key.pem>
RDS_HOST=<rds-endpoint.region.rds.amazonaws.com>
RDS_PORT=5432

# ===========================
# PGVECTOR (Semantic Memory)
# ===========================
PGVECTOR_DIMENSIONS=1536
PGVECTOR_HNSW_M=16
PGVECTOR_HNSW_EF_CONSTRUCTION=64

# ===========================
# REDIS CACHE
# ===========================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=<your-redis-password>
REDIS_DB=0
REDIS_SSL=false
REDIS_KEY_PREFIX=vqms:
REDIS_DEFAULT_TTL_SECONDS=3600

# ===========================
# MICROSOFT GRAPH API (Email)
# ===========================
GRAPH_API_TENANT_ID=<your-azure-tenant-id>
GRAPH_API_CLIENT_ID=<your-azure-app-client-id>
GRAPH_API_CLIENT_SECRET=<your-azure-app-client-secret>
GRAPH_API_MAILBOX=vendorsupport@yourcompany.com
GRAPH_API_POLL_INTERVAL_SECONDS=60
GRAPH_API_WEBHOOK_URL=<optional-webhook-notification-url>

# ===========================
# SALESFORCE CRM (Vendor Resolution)
# ===========================
SALESFORCE_INSTANCE_URL=https://yourcompany.my.salesforce.com
SALESFORCE_USERNAME=<your-sf-username>
SALESFORCE_PASSWORD=<your-sf-password>
SALESFORCE_SECURITY_TOKEN=<your-sf-security-token>
SALESFORCE_CONSUMER_KEY=<your-sf-consumer-key>
SALESFORCE_CONSUMER_SECRET=<your-sf-consumer-secret>

# ===========================
# SERVICENOW ITSM (Ticket Operations)
# ===========================
SERVICENOW_INSTANCE_URL=https://yourcompany.service-now.com
SERVICENOW_USERNAME=<your-snow-username>
SERVICENOW_PASSWORD=<your-snow-password>
SERVICENOW_CLIENT_ID=<your-snow-oauth-client-id>
SERVICENOW_CLIENT_SECRET=<your-snow-oauth-client-secret>
SERVICENOW_ASSIGNMENT_GROUP=<default-assignment-group>

# ===========================
# AWS S3 (Storage)
# ===========================
S3_BUCKET_EMAIL_RAW=vqms-email-raw-prod
S3_BUCKET_ATTACHMENTS=vqms-email-attachments-prod
S3_BUCKET_AUDIT_ARTIFACTS=vqms-audit-artifacts-prod
S3_BUCKET_KNOWLEDGE=vqms-knowledge-artifacts-prod

# ===========================
# AWS SQS (Queues)
# ===========================
SQS_QUEUE_PREFIX=vqms-
SQS_DLQ_NAME=vqms-dlq
SQS_MAX_RECEIVE_COUNT=3
SQS_VISIBILITY_TIMEOUT=300

# ===========================
# AWS EVENTBRIDGE (Events)
# ===========================
EVENTBRIDGE_BUS_NAME=vqms-event-bus
EVENTBRIDGE_SOURCE=com.vqms

# ===========================
# AWS STEP FUNCTIONS
# ===========================
STEP_FUNCTIONS_STATE_MACHINE_ARN=<your-state-machine-arn>

# ===========================
# AWS COMPREHEND (PII Detection)
# ===========================
COMPREHEND_LANGUAGE_CODE=en

# ===========================
# AWS COGNITO (Auth)
# ===========================
COGNITO_USER_POOL_ID=<your-user-pool-id>
COGNITO_CLIENT_ID=<your-cognito-client-id>
COGNITO_DOMAIN=<your-cognito-domain>

# ===========================
# PORTAL CONFIGURATION
# ===========================
# Portal path entry point settings
PORTAL_SESSION_TTL_HOURS=8
PORTAL_QUERY_ID_PREFIX=VQ
PORTAL_SSO_ENABLED=false                     # true to enable federated SSO (Okta/Azure AD)
PORTAL_SSO_PROVIDER=<okta|azure_ad>
PORTAL_SSO_METADATA_URL=<your-sso-metadata-url>

# ===========================
# AWS SECRETS MANAGER
# ===========================
SECRETS_MANAGER_PREFIX=vqms/

# ===========================
# OPENTELEMETRY (Observability)
# ===========================
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=vqms
OTEL_TRACES_SAMPLER=parentbased_traceid_ratio
OTEL_TRACES_SAMPLER_ARG=1.0

# ===========================
# SLA CONFIGURATION
# ===========================
SLA_WARNING_THRESHOLD_PERCENT=70
SLA_L1_ESCALATION_THRESHOLD_PERCENT=85
SLA_L2_ESCALATION_THRESHOLD_PERCENT=95
SLA_DEFAULT_HOURS=24

# ===========================
# AGENT CONFIGURATION
# ===========================
AGENT_CONFIDENCE_THRESHOLD=0.85
AGENT_MAX_HOPS=4
AGENT_BUDGET_MAX_TOKENS_IN=8000
AGENT_BUDGET_MAX_TOKENS_OUT=4096
AGENT_BUDGET_CURRENCY_LIMIT_USD=0.50

# ===========================
# KB SEARCH CONFIGURATION
# ===========================
# Knowledge base search settings for Path A/B decision
KB_MATCH_THRESHOLD=0.80                      # Minimum cosine similarity for KB article match
KB_MAX_RESULTS=5                             # Max KB articles to return per search
KB_RESOLUTION_CONFIDENCE_THRESHOLD=0.85      # Min Resolution Agent confidence to proceed with Path A
```

---

## Final Development Checklist (from Implementation Plan)

Before declaring the system complete, verify every item below:

### Data Layer
- [ ] PostgreSQL schema deployed with all namespaces (intake, workflow, routing, audit, memory, reporting)
- [ ] Redis key families operational with correct TTLs
- [ ] S3 buckets created (raw email, attachments, knowledge artifacts, audit)
- [ ] Alembic migrations baselined and version-controlled

### Entry Points
- [ ] Portal path: POST /queries returns query_id in < 500ms
- [ ] Email path: webhook ingestion processes emails in < 5 seconds
- [ ] Idempotency guards reject duplicate submissions on both paths
- [ ] Thread correlation correctly identifies NEW, EXISTING_OPEN, REPLY_TO_CLOSED

### AI Pipeline
- [ ] LangGraph orchestrator consumes from SQS and executes full graph
- [ ] Query Analysis Agent classifies intent with > 0.85 confidence for clear queries
- [ ] Confidence branching correctly routes to Path A/B (>= 0.85) or Path C (< 0.85)
- [ ] KB search returns ranked articles filtered by category
- [ ] Routing engine assigns correct team and SLA based on rules

### Response Generation
- [ ] Resolution Agent (Path A) drafts email with specific KB-sourced facts
- [ ] Communication Agent (Path B) drafts acknowledgment with ticket number and SLA
- [ ] Quality Gate passes all 7 checks on valid drafts and rejects invalid ones
- [ ] PII detection strips sensitive data from outbound emails
- [ ] ServiceNow tickets created with correct assignment and metadata
- [ ] Emails delivered via MS Graph /sendMail with correct threading

### Path C
- [ ] Low-confidence queries pause workflow via Step Functions callback
- [ ] Triage portal displays TriagePackage for reviewer
- [ ] Reviewer corrections resume workflow with validated data

### SLA
- [ ] SLA monitor fires escalation at 70/85/95% thresholds
- [ ] Path C SLA clock starts after review, not before
- [ ] SLA metrics recorded in reporting.sla_metrics

### Closure
- [ ] Confirmation replies close tickets
- [ ] 5-business-day auto-closure works
- [ ] Reopen vs new-linked-ticket decision works correctly
- [ ] Episodic memory saved on closure

### Frontend
- [ ] Vendor portal: login, dashboard, wizard, query tracking
- [ ] Triage portal: queue, review, correction submission

### Monitoring & Security
- [ ] Correlation ID propagated across all services
- [ ] EventBridge events published for all state transitions
- [ ] Audit log records every action with timestamp and actor
- [ ] JWT auth enforced on all endpoints via Cognito Authorizer
- [ ] vendor_id extracted from JWT, never from payload

### Testing
- [ ] All 3 paths (A, B, C) pass end-to-end integration tests
- [ ] Reference scenario (Rajesh, TechNova, Path A, ~11s, ~$0.033) works end-to-end

---

## Core Principles
- **Development First:** We are writing development code — simple, clear, easy to understand. Production hardening comes later.
- **Standards for Naming, Not Complexity:** Follow the coding standards for naming conventions, project structure, and documentation. Skip the advanced patterns (circuit breakers, token buckets, full OpenTelemetry) until production mode.
- **Architecture Aligned:** Every agent, service, integration, queue, event, and flow must trace back to the VQMS architecture doc and solution flow doc.
- **Two Entry Points, One Pipeline:** Email and Portal paths produce different payloads on different queues but converge into the same unified AI pipeline at Step 7 (LangGraph Orchestrator). Code must handle both origins cleanly.
- **Three Paths Are First-Class:** Path A (AI-Resolved), Path B (Human-Team-Resolved), and Path C (Low-Confidence) are not edge cases — they are core system behavior. Every component from routing to communication drafting to SLA monitoring must be path-aware.
- **Bottom-Up Build:** Data models → storage → services → orchestration → agents. Never top-down.
- **Simplicity First:** Make every change as simple as possible. Minimal code impact.
- **Comments That Teach:** Write comments that explain the WHY. A new developer should be able to read any file and understand the reasoning behind decisions.
- **Descriptive Names Over Clever Code:** If a name is good enough, you do not need a comment. If you need a comment to explain what a variable holds, rename the variable.
- **Correlation Everywhere:** Every function in the pipeline must accept and propagate `correlation_id`.
- **Idempotency Everywhere:** Every external write must be idempotent. Use message-id keys in Redis, check-before-create for ServiceNow.
- **No Deployment Without Approval:** Infrastructure and deployment files are gated behind explicit user approval.
- **Office AWS Constraints:** This is an enterprise project with limited IAM privileges. All code must work locally without AWS access and switch to real AWS via config flags. Never create AWS resources from code.
- **Stubs First, Real Later:** Build each adapter with a stub/mock that returns realistic test data. Replace with real integrations in Phase 8.
- **Configurable Thresholds:** Confidence threshold (0.85), KB match threshold (0.80), SLA targets, Quality Gate rules — all must be configurable, not hardcoded.
