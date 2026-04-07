"""Application settings for VQMS.

Loads configuration from environment variables and .env file
using pydantic-settings. All modules import settings from here
via get_settings() which returns a cached singleton.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """Central configuration loaded from environment variables.

    Every configurable value in the system lives here. Modules
    access settings via get_settings() — never read os.environ
    directly except in this class.
    """

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # --- Application ---
    app_env: str = "development"
    app_name: str = "vqms"
    app_version: str = "1.0.0"
    app_debug: bool = True
    app_port: int = 8000
    log_level: str = "DEBUG"
    correlation_id_header: str = "X-Correlation-ID"

    # --- Secrets Backend ---
    app_secrets_backend: str = "env"

    # --- PostgreSQL ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "vqms"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_pool_min: int = 5
    postgres_pool_max: int = 20
    database_url: str = ""

    # --- SSH Tunnel (Bastion → RDS) ---
    # RDS is not directly accessible — DB connections go through SSH tunnel
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_username: str = ""
    ssh_private_key_path: str = ""
    rds_host: str = ""
    rds_port: int = 5432

    # --- pgvector ---
    pgvector_dimensions: int = 1536
    pgvector_hnsw_m: int = 16
    pgvector_hnsw_ef_construction: int = 64

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_ssl: bool = False
    redis_key_prefix: str = "vqms:"
    redis_default_ttl_seconds: int = 3600

    # --- Microsoft Graph API (Email) ---
    graph_api_tenant_id: str = ""
    graph_api_client_id: str = ""
    graph_api_client_secret: str = ""
    graph_api_mailbox: str = ""
    graph_api_poll_interval_seconds: int = 60

    # --- Agent Configuration ---
    # Confidence below this threshold routes to Path C (human review)
    agent_confidence_threshold: float = 0.85
    agent_max_hops: int = 4
    agent_budget_max_tokens_in: int = 8000
    agent_budget_max_tokens_out: int = 4096
    agent_budget_currency_limit_usd: float = 0.50

    # --- KB Search ---
    # KB match below this threshold means Path B (human team resolves)
    kb_match_threshold: float = 0.80
    kb_max_results: int = 5
    kb_resolution_confidence_threshold: float = 0.85

    # --- AWS S3 Buckets ---
    # Pre-provisioned bucket names, read from env vars
    s3_bucket_email_raw: str = "vqms-email-raw-prod"
    s3_bucket_attachments: str = "vqms-email-attachments-prod"
    s3_bucket_audit_artifacts: str = "vqms-audit-artifacts-prod"
    s3_bucket_knowledge: str = "vqms-knowledge-artifacts-prod"

    # --- AWS SQS Queues ---
    sqs_query_intake_queue: str = "vqms-query-intake-queue"
    sqs_email_intake_queue: str = "vqms-email-intake-queue"

    # --- AWS EventBridge ---
    eventbridge_bus_name: str = "vqms-event-bus"
    eventbridge_source: str = "com.vqms"

    # --- AWS General ---
    aws_region: str = "us-east-1"

    # --- SLA ---
    sla_warning_threshold_percent: int = 70
    sla_l1_escalation_threshold_percent: int = 85
    sla_l2_escalation_threshold_percent: int = 95
    sla_default_hours: int = 24

    @model_validator(mode="after")
    def build_database_url(self) -> AppSettings:
        """Build database_url from individual postgres fields if not set.

        The .env.copy template uses shell-style interpolation for
        DATABASE_URL, but pydantic-settings does not support that.
        So we build the URL from parts when it is empty or contains
        unresolved ${...} placeholders.

        NOTE: When using SSH tunnel, postgres_host and postgres_port
        will be overridden at runtime with the tunnel's local bind
        address. The database_url is rebuilt dynamically by
        src/db/connection.py after the tunnel is established.
        """
        url = self.database_url
        if not url or "${" in url:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached application settings singleton.

    Uses lru_cache so the .env file is only read once per process.
    """
    return AppSettings()
