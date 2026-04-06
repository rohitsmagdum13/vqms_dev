# 1) Python Coding Standards for GenAI

## 1.1 General Python Practices

- **Version:** Use Python ≥ 3.10.
- **Environment:** Manage environments with venv, pip, or uv package manager; ensure reproducible builds via lock files and `constraints.txt`.
- **Formatting:** PEP 8 + Black.
  - Sort imports: `isort`.
  - Clean code: No unused imports or variables
  - Linting: `flake8` or `ruff`
  - Typing: Enforce type hints with `mypy` for public modules.
- **Naming Conventions:** Readable without comments; `snake_case` for variables/functions, `UPPER_CASE` for constants.
  - Eg. `first_name` (variable), `def math_addition()`, `CONSTANT_VARIABLE`
- **Documentation:** Every function must have a Docstring
- **Error Handling:** Implement error handling using domain-specific exceptions. Never suppress or swallow errors silently. Include correlation IDs in logs for tracing. Never log secrets.
- **Testing:** Unit tests must be considered for every function (refer to Section 21).
- **Configuration:** Use `pydantic` for validated configuration. Adopt a hierarchical YAML structure (default, dev, prod). Store secrets exclusively in environment variables (`.env`) or secret managers.

## 1.2 GenAI-Specific Patterns

- **Prompt Management:** Store versioned prompts under `prompts/` with metadata (ID, owner, created, inputs, evaluation).
- **LLM Client Abstraction:** Wrap provider SDKs behind an interface to enable swapping without code changes.
- **Serialization & Contracts:** Enforce JSON-only tool I/O with `pydantic` models; do not parse free-form text without validation.
- **Streaming & Async:** Prefer `asyncio` for concurrency, stream tokens when UX requires; use semaphores to bound concurrency.
- **Determinism:** Set random seeds for evaluation; log model, provider, temperature, and system prompt hash.
- **Agent Termination:** Define clear termination conditions and timeout limits (iteration limits for agents).
- **Cost & Token Budgeting:** Attach per-request budget (max tokens in/out, currency limit) and enforce at the orchestration layer.

Implementation Snippets

### LLM Client Protocol

```python
from typing import Protocol

class LLMClient(Protocol):
    async def complete(self, prompt: str, *, model: str, temperature: float, tools: list | None) -> dict:
        ...

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        ...
```

### Budget Dataclass

```python
from dataclasses import dataclass

@dataclass
class Budget:
    max_tokens_in: int
    max_tokens_out: int
    currency_limit: float
```

# 2) Multi-Layer Agent Architecture & Orchestration

## 2.1 Architectural Principles

- **Layering:** Interface → Orchestration → Agent (decision logic) → Tools (external services) → Memory (state management). Keep concerns separated.
- **Contracts First:** Define message envelope schemas for inter-agent communication.
- **Idempotency & Reentrancy:** Actions must be idempotent; maintain state snapshots for resumption.

AgentMessage Schema (Pydantic)

```python
from pydantic import BaseModel
from typing import Any, Literal
from datetime import datetime

class ToolCall(BaseModel):
    name: str
    args: dict

class AgentMessage(BaseModel):
    id: str
    parent_id: str | None
    role: Literal['system','planner','worker','reviewer','user']
    content: str | dict
    tool_calls: list[ToolCall] = []
    annotations: dict[str, Any] = {}  # cost, tokens, safety flags
    correlation_id: str
    timestamp: datetime
```

## 2.2 Orchestration Patterns

- **Supervisor-Worker:** Planner delegates subgoals; Reviewer validates outputs.
- **Router:** Direct requests via classifier or rule engine based on intent and policy.
- **Blackboard:** Shared state store; mediator manages contention.
- **DAG/State Machine:** Fixed workflows with timeouts and cancellation tokens.

## 2.3 Tool Use & Policy Enforcement

```python
from pydantic import BaseModel

class Tool(BaseModel):
    name: str
    schema_in: type[BaseModel]
    schema_out: type[BaseModel]
    scopes_required: set[str]
    max_runtime_ms: int
```

- **Guarded Execution:** Sandbox risky tools; restrict to allowed domains; enforce per-tool limits.
- **Policy-as-Code:** Use a policy engine to decide tool eligibility based on user, tenant, and purpose.

## 2.4 Budget, Timeouts & Cancellation

- Each request carries a Budget, deadline, and cancellation token; propagate across agents.
- Default max hops (e.g., 4 steps) to prevent infinite loops.
- Enforce budgets and deadlines in the orchestration layer.

# 3) Memory Management Standards

## 3.1 Memory Types

- **Short-Term (Conversation/Session):** Windowed buffer with compaction (summarization).
- **Long-Term (Semantic/Vector Store):** Knowledge base and episodic memory with data lineage.
- **Working Memory:** Scratchpad for current task, cleared on completion.
- **Policy Memory:** User preferences, allowed tools, RBAC tokens (avoid exposing PII).

## 3.2 Retention & Privacy

- Explicit TTLs per memory type (e.g., session 24h, long-term 180 days).
- Redact PII before persistence; encrypt at rest; restrict rehydration scope.
- **Right to Forget:** Deletion APIs must cascade across vector stores and caches.

## 3.3 RAG Quality Guidelines

- **Chunking:** Chunk data by semantic boundaries to preserve context. Store metadata (document_id, chunk_id, source_url, timestamp).
- **Metadata:** Index metadata fields (tenant, language, freshness) for efficient filtering.
- **Process:** Retrieval First, Generation Second. Cite sources and track provenance.
- **Ranking:** Use a Re-ranking approach to find the top relevant chunks for the user query.

## 3.4 Memory Interfaces

```python
from typing import Protocol

class MemoryStore(Protocol):
    async def write(self, key: str, value: dict, ttl: int | None) -> None: ...
    async def read(self, key: str) -> dict | None: ...
    async def search(self, query: str, top_k: int, filters: dict) -> list[dict]: ...
    async def delete(self, key: str) -> None: ...
```

# 4) Agentic Framework Best Practices

## 4.1 Agent Design

- **Single Responsibility:** Focused capability and toolset per agent.
- **System Prompt Discipline:** Minimal, task-oriented, versioned prompts.
- **Self-Reflection:** Workers self-check; reviewers run checklists.
- **Stop Conditions:** Define success criteria and max iterations.

## 4.2 Planning & Decomposition

- **Hierarchical planning:** High-level goals → subgoals → tool calls.
- **Format:** Explicit plans in JSON with end states and acceptance criteria.

## 4.3 Safety & Resilience

- **Prompt Injection Defense:** Do not execute instructions from user documents; enforce policy for tools; strip untrusted directives.
- **Content Moderation:** Filter inputs/outputs; route risky content to human-in-the-loop.
- **Circuit Breakers:** Trip on repeated provider errors or cost spikes; escalate to fallback.

## 4.4 Cost & Token Budget Enforcement

- **Global Budget Manager:** Track cumulative tokens/costs across agents per request.
- **Action:** Deny further generation when the budget is exceeded; propose a shorter answer path.

## 4.5 Observability-in-Design

- Structured logs, traces, and metrics at each agent hop.
- Log `correlation_id`, `agent_role`, `tool`, `latency_ms`, `tokens_in/out`, `cost`, `policy_decisions`, `safety_flags`.

# 5) Throttling, Concurrency & Rate Limits

## 5.1 Principles

- **Multi-dimensional limits:** Per-provider, per-tenant, per-user, per-tool.
- **Async-first:** `asyncio` with bounded semaphores and backpressure.
- **Fairness:** Token bucket for bursts; weighted priority for SLA tiers.

## 5.2 Implementation Snippet

```python
import asyncio

from collections import defaultdict

from contextlib import asynccontextmanager

class RateLimiter:
    def __init__(self, max_concurrent: int, rpm: int):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._rpm = rpm
        self._window = 60
        self._counts = defaultdict(int)
        self._reset_task = asyncio.create_task(self._reset())

    async def _reset(self):
        while True:
            await asyncio.sleep(self._window)
            self._counts.clear()

    @asynccontextmanager
    async def acquire(self, key: str):
        await self._sem.acquire()
        try:
            if self._counts[key] >= self._rpm:
                await asyncio.sleep(1.0)
            self._counts[key] += 1
            yield
        finally:
            self._sem.release()
```

# 6) Fallbacks & Degradation

- **Model Fallback:** Primary → Secondary when rate-limited or erroring.
- **Capability Fallback:** Switch to alternative tool when one fails.
- **Answer Fallback:** Return short summary or cached result when budgets are exhausted.
- **Human Escalation:** Route to human with full context and repro bundle.

```python
async def safe_complete(llm: LLMClient, prompt: str, model_chain: list[str]):
    for model in model_chain:
        try:
            return await llm.complete(prompt, model=model, temperature=0.2, tools=None)
        except TransientLLMError:
            continue
        except PermanentLLMError as e:
            raise e
    return {"text": "Service is busy. Here is a brief answer based on cached data.", "source": "cache"}
```

# 7) Error Handling & Retries

- **Retry Policy:** Exponential backoff for transient errors only.
- **Classification:** Differentiate transient (429, timeouts) vs permanent (400, policy violations).
- **Idempotent Replays:** Request hash for deduplication.
- **Circuit Breaker:** Open after N failures; log and alert; cool-down window.

# 8) Testing & Evaluation

## 8.1 Conventional Testing

- Unit tests for utilities, prompt rendering, schema validation.
- Integration tests with mock LLM stubs; deterministic outputs via fixtures.
- Contract tests for tool I/O with strict Pydantic models.

## 8.2 LLM-specific Evaluation

- **Golden Sets:** Curated inputs with expected constraints (faithfulness, completeness, style, safety).
- **RAG Eval:** Retrieval `precision@k`, source diversity, citation accuracy.
- **Agent Eval:** Steps ≤ max hops, cost ≤ budget, policy adherence.
- **Offline Scoring:** Rubric-based graders to avoid circular self-eval.
- **A/B & Canary:** Route % traffic to new prompts/models; compare telemetry.

# 9) Observability, Telemetry & Cost Control

- **Logging:** JSON logging; do not log PII; include `correlation_id`, `tenant_id`, `user_id_hash`, `agent`, `tool`, `latency`, `tokens`, `cost`, `model`, `prompt_id`, `policy decisions`.
- **Tracing:** OpenTelemetry with spans per agent/tool.
- **Metrics:** SLO dashboards (latency p95, success rate, cost/request, moderation blocks).
- **Cost Guardrails:** Per-tenant daily and per-request limits; alerts on anomalies.
- **Drift Monitoring:** Track input distribution shifts; prompt/model performance trends.
- **Optimization:** Prompt Caching Approach.

# 10) Security, Compliance & Responsible AI

- **Secrets:** Env vars or vault; rotate keys; least privilege; never commit secrets in code. Share env file offline or use secrets manager service on cloud.
- **Data Handling:** Encrypt at rest/in transit; redact PII before LLM; honor data residency.
- **Threat Model:** Prompt injection, data exfiltration, tool abuse; sandbox risky tools.
- **RBAC:** Per-tool and per-agent scopes; audit trails for tool calls.
- **Responsible AI:** Safety filters, bias audits, user disclosure; model cards and risk classification; human-in-the-loop for high-risk decisions.

# 11) Deployment, Operations & Runbooks

- **CI/CD:** Lint, type-check, unit/integration/security scans; artifact signing.
- **Release Management:** Semantic versioning for services, prompts, and models.
- **Blue/Green & Rollback:** Config flags to roll forward/back; keep previous prompt/model versions hot.
- **Runbooks:** Incident response, escalation paths, circuit breaker ops, cache warmers.
- **Backups:** Vector stores, indexes, and policy memories; tested restore procedures.

# 12) Architecture - Directory Structure

```text
agentic_ai_project/
├── Doc/                           # Project documentation
│   ├── System_Architecture.md     # System architecture diagrams
│   ├── Application_Workflow.md    # Workflow of the application
│   └── Agents.md                  # Detailed descriptions of agents
├── security/                      # Security and compliance configurations
│   ├── guardrails_config.yaml
│   ├── data_privacy_policy.md
│   ├── access_control.yaml
│   ├── encryption_config.yaml
│   ├── audit_logging_config.yaml
│   └── gdpr_compliance_checklist.md
├── config/                        # Configuration files
│   ├── __init__.py
│   ├── agents_config.yaml         # Agent personas, goals, backstories
│   ├── tools_config.yaml          # API keys and tool settings
│   ├── model_config.yaml          # LLM settings
│   ├── logging_config.yaml
│   ├── database_config.yaml
│   ├── dev_config.yaml
│   ├── test_config.yaml
│   ├── prod_config.yaml
├── src/                           # Source code
│   ├── agents/                    # Agent definitions
│   │   ├── __init__.py
│   │   └── abc_agent.py           # Abstract base class
│   ├── tools/                     # Function calling
│   │   ├── __init__.py
│   │   └── custom_tools.py        # Custom tools (email, PDF, MCP, etc.)
│   ├── memory/                    # State management
│   │   ├── __init__.py
│   │   ├── short_term.py          # Conversation history
│   │   └── long_term.py           # Vector DB (RAG)
│   ├── orchestration/             # Agent communication
│   │   ├── __init__.py
│   │   ├── graph.py               # LangGraph state machine
│   │   ├── router.py              # Task routing logic
│   │   └── manager.py             # Hierarchical manager logic
│   ├── llm/                       # Model wrappers
│   │   ├── __init__.py
│   │   ├── factory.py             # Model instance factory
│   │   ├── utils.py               # RAG indexing, chunking
│   │   └── security_helpers.py    # Encryption, hashing
│   ├── utils/                     # General utilities
│   │   ├── logger.py
│   │   └── helpers.py
│   └── evaluation/                # Evaluation modules
│       ├── matrix.py              # Metrics and matrices
│       ├── eval.py                # Evaluation logic
│       └── result_folder/         # Output folder
├── data/                          # Data storage
│   ├── knowledge_base/            # RAG Documents
│   ├── vector_store/              # Local vector DB files
│   ├── logs/                      # Execution logs
│   └── artifacts/                 # Generated files
├── tests/                         # Testing suite
│   ├── unit/                      # Unit tests
│   └── evals/                     # LLM-as-a-judge evals
├── notebooks/                     # Jupyter notebooks
│   ├── tool_testing.ipynb
│   └── agent_simulation.ipynb
├── .env                           # Environment variables (Never committed)
├── .gitignore                     # Git ignore rules
├── Dockerfile                     # Containerization
├── requirements.txt               # Python dependencies
├── main.py                        # Entry point
└── README.md                      # Project overview
```

# 14) Prompt Template Example (Versioned)

{# prompts/doc_summary_v2.jinja #}

# System:

You are a concise summarizer. Follow constraints strictly:

- Cite sources with their titles and links.

- Do not invent facts.

# User:

Summarize the following document for a {{ audience }} in a {{ tone }} tone.

Include: 3 key points and 2 risks.

{{ document_text }}

# 15) Checklists

Agent Design Checklist

- Single responsibility & tool scope
- System prompt minimal & versioned
- Self-check & reviewer loop defined
- Stop conditions & max hops
- Policy enforcement integrated

RAG Checklist

- Proper chunking & metadata
- Filter strategies defined
- Retrieval metrics instrumented
- Source citations enforced
- PII redaction before index

Ops Checklist

- Rate limits per provider/tenant
- Circuit breakers configured
- Budget manager active
- Observability (logs/traces/metrics)
- Runbooks & rollback plan

# 16) Governance & Documentation

- **Solution Design Document (SGD):** Capture model, prompt, and tooling choices.
- **Model & Prompt Cards:** Risks, metrics, version history.
- **Data Lineage:** Sources, transforms, retention.
- **Approvals:** Security, Compliance, and Business owner signoffs before production.
- **Risk Logs & Dataflow Diagrams.**

# 17) Non-Functional Requirements (SLOs)

- **Latency:** p95 ≤ target per endpoint (e.g., 1200 ms for simple Q&A; streaming allowed).
- **Availability:** 99.9% monthly; failover to secondary region/provider.
- **Cost:** ≤ target currency per 1000 requests; alerts at 80%, hard cap at 100%.
- **Safety:** 100% of outputs pass moderation; 0 PII leakage.
- **Notifications:** Error handling notifications provided.

# 18) Example Policies (Declarative)

```yaml
# orchestration/policies/tool_access.yaml

rules:
  - id: allow_rag_for_docs
    if:
      intent: ["summarize", "answer_faq"]
      user_role: ["analyst", "manager"]
    then:
      allow_tools: ["rag_search", "web_fetch"]
      deny_tools: ["code_exec_sandbox"]
```

# 19) Glossary

- **Agent:** Autonomous component with role, prompt, and toolset.
- **Tool:** External capability exposed via a structured interface (DB, search, code exec).
- **Orchestration:** Coordination of agents, policies, budgets, and tool calls.
- **RAG:** Retrieval-Augmented Generation—retrieve context before generation.

# 20) Quick Start Recommendations

- Start with single-agent + RAG; add agents only when necessary.
- Introduce `planner` + `reviewer` for complex tasks.
- Instrument telemetry & budgets from day one.
- Maintain prompt & model versioning with golden-set evaluation.
- Enforce `policy-as-code` for tool access and safety.

# 21) Evaluation Metrics

LLM-Based Evaluation for RAG Pipelines In RAG pipelines, traditional metrics (BLEU, ROUGE) are often insufficient. LLM-based evaluation uses a language model to judge the quality of retrieval and generation.

What LLM-Based Evaluation Measures:

1. **Answer Relevance:** Does the answer address the `user` question?
2. **Faithfulness / Groundedness:** Is the answer supported by the retrieved context?
3. **Context Relevance:** Are the retrieved documents relevant to the question?
4. **Completeness:** Does the answer cover all required information?

Common Libraries:

- **RAGAS:** Purpose-built for RAG (Relevance, Faithfulness, Context Precision/Recall).
- **LangChain Evaluators:** LLM-as-a-judge with predefined criteria.

Example: LLM Judge Prompt

```text
Question: {question}

Retrieved Context: {context}

Answer: {answer}

Evaluate the answer on a scale of 0 to 1 for faithfulness.

Only return the numeric score.
```

Example: Simple LLM-Based Scoring Code

```python
def llm_judge_score(llm, prompt):
    response = llm(prompt)
    return float(response.strip())
```

Example: RAGAS Faithfulness Metric

```python
from ragas.metrics import faithfulness
from ragas import evaluate

score = evaluate(
    dataset,
    metrics=[faithfulness]
)
```

Output Format (Standard)

```json
{
    "metric": "faithfulness",
    "score": 0.91
}
```

Appendix: Project Structure Automation Script

The following Python script automates the creation of the directory structure defined in Section 12.

```python
import os

def create_project_structure():
    project_name = input("Enter the project name/folder_name : ")

    # Define the directory structure
    directories = [
        "Doc",
        "security",
        "config",
        "src/agents",
        "src/tools",
        "src/memory",
        "src/orchestration",
        "src/llm",
        "src/utils",
        "src/evaluation/result_folder",
        "data/knowledge_base",
        "data/vector_store",
        "data/logs",
        "data/artifacts",
        "tests/unit",
        "tests/evals",
        "notebooks"
    ]

    # Define the files and their specific locations
    files_map = {
        "Doc": [
            "System_Architecture.md",
            "Application_Workflow.md",
            "Agents.md"
        ],
        "security": [
            "guardrails_config.yaml",
            "data_privacy_policy.md",
            "access_control.yaml",
            "encryption_config.yaml",
            "audit_logging_config.yaml",
            "gdpr_compliance_checklist.md"
        ],
        "config": [
            "__init__.py",
            "agents_config.yaml",
            "tools_config.yaml",
            "model_config.yaml",
            "logging_config.yaml",
            "database_config.yaml",
            "dev_config.yaml",
            "test_config.yaml",
            "prod_config.yaml"
        ],
        "src/agents": [
            "__init__.py",
            "abc_agent.py"
        ],
        "src/tools": [
            "__init__.py",
            "custom_tools.py"
        ],
        "src/memory": [
            "__init__.py",
            "short_term.py",
            "long_term.py"
        ],
        "src/orchestration": [
            "__init__.py",
            "graph.py",
            "router.py",
            "manager.py"
        ],
        "src/llm": [
            "__init__.py",
            "factory.py",
            "utils.py",
            "security_helpers.py"
        ],
        "src/utils": [
            "logger.py",
            "helpers.py"
        ],
        "src/evaluation": [
            "matrix.py",
            "eval.py"
        ],
        "notebooks": [
            "tool_testing.ipynb",
            "agent_simulation.ipynb"
        ],
        # Root files
        "": [
            ".env",
            ".gitignore",
            "Dockerfile",
            "requirements.txt",
            "main.py",
            "README.md"
        ]
    }

    # 1. Create Directories

    print(f"🚀 Creating project: {project_name}")

    if not os.path.exists(project_name):
        os.makedirs(project_name)

    for directory in directories:
        dir_path = os.path.join(project_name, directory)
        os.makedirs(dir_path, exist_ok=True)

        # Create __init__.py in src_subfolders if missing in the file_map but needed for python packages
        if directory.startswith("src") and "__init__.py" not in files_map.get(directory, []):
            # Check if it's not the result_folder which shouldn't be a package
            if "result_folder" not in directory:
                with open(os.path.join(dir_path, "__init__.py"), 'w') as f:
                    pass

    # 2. Create Files with Boilerplate Content

    for folder, filenames in files_map.items():
        for filename in filenames:
            file_path = os.path.join(project_name, folder, filename)

            # Skip if file exists to avoid overwriting
            if os.path.exists(file_path):
                continue

            content = ""

            # Add specific content based on file type/name
            if filename == ".gitignore":
                content = ".env\n__pycache__/\n*.pyc\n.ipynb_checkpoints/\ndata/logs/\ndata/vector_store/"
            elif filename == "requirements.txt":
                content = "langchain\nlanggraph\nopenai\nanthropic\npydantic\npython-dotenv\nchromadb"
            elif filename.endswith(".md"):
                content = f"# {filename.replace('.md', '').replace('_', ' ')}\n\nDescription goes here."
            elif filename.endswith(".yaml"):
                content = "# Configuration settings\n"
            elif filename.endswith(".py"):
                if filename == "__init__.py":
                    content = ""
                else:
                    content = f'"""\nModule: {filename}\nDescription: Implementation details here.\n"""\n\ndef main():\n    pass\n'
            elif filename.endswith(".ipynb"):
                # Minimal valid JSON for an empty notebook
                content = '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'

            with open(file_path, 'w') as f:
                f.write(content)

    print("✅ Project structure created successfully!")
    print(f"📁 Location: {os.path.abspath(project_name)}")

if __name__ == "__main__":
    create_project_structure()
```
