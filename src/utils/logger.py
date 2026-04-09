"""Structured JSON logging setup for VQMS.

Configures structlog to produce JSON-formatted logs with
correlation IDs, timestamps, and caller info. All modules
use standard logging.getLogger(__name__) — structlog wraps
it automatically after setup_logging() is called.

Logs go to two destinations:
  1. Console (stdout) — human-readable in DEBUG, JSON otherwise
  2. File (data/logs/) — always JSON, one file with rotation

The log directory (data/logs/) is created automatically if missing.

Also provides four logging decorators:
  - @log_api_call      — FastAPI route handlers
  - @log_service_call  — services, adapters, orchestration nodes
  - @log_llm_call      — LLM factory functions (llm_complete, llm_embed)
  - @log_policy_decision — confidence checks, path decisions, routing
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import traceback
import uuid
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from src.utils.log_context import LogContext

# Log files go here — relative to project root
LOG_DIR = Path("data/logs")

# Rotate log files at 10 MB, keep last 5 rotated files
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5

# Fields that the ensure_default_fields processor adds if missing
_DEFAULT_FIELDS = {
    "correlation_id": None,
    "query_id": None,
    "execution_id": None,
    "agent_role": None,
    "username": None,
    "role": None,
    "tenant": None,
    "step": None,
    "status": None,
    "tool": None,
    "latency_ms": None,
    "tokens_in": None,
    "tokens_out": None,
    "cost_usd": None,
    "model": None,
    "provider": None,
    "was_fallback": None,
    "policy_decision": None,
    "safety_flags": None,
}


def _ensure_log_dir() -> Path:
    """Create the log directory if it does not exist.

    Returns the absolute path to the log directory.
    """
    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def ensure_default_fields(
    logger: Any,  # noqa: ARG001
    method_name: str,  # noqa: ARG001
    event_dict: dict,
) -> dict:
    """Structlog processor that ensures all VQMS fields exist.

    If a field was not passed via extra={} or structlog bind(),
    it gets a default value of None. This prevents KeyError in
    downstream processors and gives log aggregation tools a
    consistent schema.
    """
    for field_name, default_value in _DEFAULT_FIELDS.items():
        if field_name not in event_dict:
            event_dict[field_name] = default_value
    return event_dict


def _strip_none_fields(
    logger: Any,  # noqa: ARG001
    method_name: str,  # noqa: ARG001
    event_dict: dict,
) -> dict:
    """Structlog processor that removes None-valued fields before output.

    Runs just before the renderer so the JSON output is clean.
    Keeps the field if the value is any non-None falsy value
    (0, False, empty string) — only strips actual None.
    """
    return {k: v for k, v in event_dict.items() if v is not None}


def setup_logging(
    log_level: str = "DEBUG",
    *,
    log_to_file: bool = True,
    log_filename: str | None = None,
) -> None:
    """Configure structlog and stdlib logging for the application.

    Call this once at application startup (in main.py lifespan).
    After this call, any logger obtained via logging.getLogger()
    will produce structured JSON output to both console and file.

    Args:
        log_level: Minimum log level as a string (DEBUG, INFO, etc.).
        log_to_file: Whether to write logs to data/logs/ directory.
            Defaults to True.
        log_filename: Custom log filename. If None, uses 'vqms.log'.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.DEBUG)

    # Processors that run for ALL log entries (structlog + stdlib)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        ensure_default_fields,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Extra pre-chain for stdlib-originated logs only.
    # ExtraAdder() reads the LogRecord's extra={} fields (correlation_id,
    # tool, agent_role, etc.) and merges them into the event dict.
    # It must run BEFORE ensure_default_fields so real values take
    # priority over None defaults. ExtraAdder requires _record which
    # only exists on stdlib LogRecords, so it cannot go in
    # structlog.configure() (that chain handles structlog-native logs).
    stdlib_pre_chain: list[structlog.types.Processor] = [
        structlog.stdlib.ExtraAdder(),
        *shared_processors,
    ]

    # Configure structlog for structlog-native logs
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- Console handler: human-readable in DEBUG, JSON otherwise ---
    if log_level.upper() == "DEBUG":
        console_final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _strip_none_fields,
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        console_final_processors = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _strip_none_fields,
            structlog.processors.JSONRenderer(),
        ]

    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=stdlib_pre_chain,
        processors=console_final_processors,
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.setLevel(numeric_level)

    # --- File handler: always JSON, rotated by size ---
    if log_to_file:
        try:
            log_dir = _ensure_log_dir()

            if log_filename is None:
                log_filename = "vqms.log"

            log_path = log_dir / log_filename

            file_formatter = structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=stdlib_pre_chain,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    _strip_none_fields,
                    structlog.processors.JSONRenderer(),
                ],
            )

            file_handler = RotatingFileHandler(
                filename=str(log_path),
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(numeric_level)

            root_logger.addHandler(file_handler)
        except OSError as e:
            # If we can't write logs to file, warn but don't crash
            root_logger.warning(
                "Could not set up file logging: %s — logging to console only",
                e,
            )

    # Silence noisy third-party loggers.
    # botocore/urllib3: SQS long-poll cycle logs every 20s when queue is empty
    # watchfiles: file change detection noise from uvicorn reload
    # paramiko: SSH keepalive messages from the bastion tunnel
    for noisy_logger in (
        "uvicorn.access",
        "httpx",
        "httpcore",
        "botocore",
        "urllib3",
        "watchfiles",
        "paramiko",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog-wrapped logger for the given module name.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A bound logger that produces structured output.
    """
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Logging Decorators
# ---------------------------------------------------------------------------


def _extract_log_ctx(args: tuple, kwargs: dict) -> LogContext:
    """Extract or build a LogContext from function arguments.

    Priority:
      1. log_ctx= kwarg (explicit LogContext)
      2. correlation_id= kwarg (build minimal LogContext)
      3. First positional arg is a dict with correlation_id (LangGraph state)
      4. Empty LogContext (fallback)
    """
    # 1. Explicit LogContext in kwargs
    if "log_ctx" in kwargs:
        return kwargs["log_ctx"]

    # 2. correlation_id kwarg
    cid = kwargs.get("correlation_id")
    if cid:
        return LogContext(correlation_id=cid)

    # 3. First arg is a state dict (common in orchestration nodes)
    if args and isinstance(args[0], dict) and "correlation_id" in args[0]:
        return LogContext.from_state(args[0])

    return LogContext()


def _get_module_name(func: Any) -> str:
    """Extract a short module name from a function for agent_role default."""
    module = getattr(func, "__module__", "") or ""
    return module.rsplit(".", maxsplit=1)[-1] if module else "unknown"


def log_api_call(func):  # noqa: ANN001, ANN201
    """Decorator for FastAPI endpoints.

    Creates a LogContext from the request and logs API
    START/END/FAILED with method, path, status_code, latency_ms.
    """
    _logger = logging.getLogger(func.__module__ or __name__)

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()

        # Find the Request object in kwargs or args
        from fastapi import Request

        request = kwargs.get("request")
        if request is None:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        # Build LogContext from request
        cid = None
        username = "anonymous"
        user_role = "unknown"
        if request is not None:
            cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
            username = request.headers.get("x-vendor-id", "anonymous")
            user_role = request.headers.get("x-role", "VENDOR")
        else:
            cid = kwargs.get("x_correlation_id") or str(uuid.uuid4())

        ctx = LogContext(
            correlation_id=cid,
            agent_role="api",
            username=username,
            role=user_role,
        )

        method = request.method if request else "?"
        path = str(request.url.path) if request else func.__name__

        _logger.info(
            f"API START: {method} {path}",
            extra=ctx.to_dict(),
        )

        try:
            result = await func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            status_code = getattr(result, "status_code", 200)

            _logger.info(
                f"API END: {method} {path} — status={status_code} — {elapsed_ms:.1f}ms",
                extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
            )
            return result

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            status_code = getattr(exc, "status_code", 500)
            _logger.error(
                f"API FAILED: {method} {path} — {type(exc).__name__}: {exc} — {elapsed_ms:.1f}ms",
                extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
            )
            raise

    return wrapper


def log_service_call(func):  # noqa: ANN001, ANN201
    """Decorator for service/agent/adapter functions.

    Looks for log_ctx in kwargs, falls back to correlation_id,
    falls back to state dict in first arg. Logs START/END/FAILED
    with latency_ms. Handles both async and sync functions.
    """
    _logger = logging.getLogger(func.__module__ or __name__)
    module_name = _get_module_name(func)

    if asyncio.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            ctx = _extract_log_ctx(args, kwargs)
            if ctx.agent_role is None:
                ctx = ctx.with_update(agent_role=module_name)

            _logger.info(f"SERVICE START: {func.__name__}", extra=ctx.to_dict())

            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                _logger.info(
                    f"SERVICE END: {func.__name__} — {elapsed_ms:.1f}ms",
                    extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
                )
                return result
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                _logger.error(
                    f"SERVICE FAILED: {func.__name__} — {type(exc).__name__}: {exc}",
                    extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
                )
                _logger.debug(traceback.format_exc(), extra=ctx.to_dict())
                raise

        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        ctx = _extract_log_ctx(args, kwargs)
        if ctx.agent_role is None:
            ctx = ctx.with_update(agent_role=module_name)

        _logger.info(f"SERVICE START: {func.__name__}", extra=ctx.to_dict())

        try:
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _logger.info(
                f"SERVICE END: {func.__name__} — {elapsed_ms:.1f}ms",
                extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _logger.error(
                f"SERVICE FAILED: {func.__name__} — {type(exc).__name__}: {exc}",
                extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
            )
            raise

    return sync_wrapper


def log_llm_call(func):  # noqa: ANN001, ANN201
    """Decorator for LLM factory functions (llm_complete, llm_embed).

    Enriches the log with tokens_in, tokens_out, cost_usd, model,
    provider, was_fallback, and latency_ms from the result dict.

    The decorated function must return a dict with LLM metadata.
    """
    _logger = logging.getLogger(func.__module__ or __name__)

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        cid = kwargs.get("correlation_id")

        ctx = LogContext(
            correlation_id=cid,
            agent_role="llm_factory",
            tool=f"llm_{func.__name__}",
        )

        _logger.info(f"LLM CALL START: {func.__name__}", extra=ctx.to_dict())

        try:
            result = await func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Enrich context with LLM result fields
            ctx = ctx.with_llm_result(
                provider=result.get("provider", "unknown"),
                model=result.get("model", "unknown"),
                tokens_in=result.get("tokens_in", 0),
                tokens_out=result.get("tokens_out", 0),
                cost_usd=result.get("cost_usd", 0.0),
                latency_ms=round(elapsed_ms, 1),
                was_fallback=result.get("was_fallback", False),
            )

            _logger.info(
                f"LLM CALL END: {func.__name__} — "
                f"{elapsed_ms:.1f}ms — "
                f"in:{result.get('tokens_in', 0)} out:{result.get('tokens_out', 0)} "
                f"${result.get('cost_usd', 0):.4f}",
                extra=ctx.to_dict(),
            )
            return result

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _logger.error(
                f"LLM CALL FAILED: {func.__name__} — {type(exc).__name__}: {exc}",
                extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
            )
            raise

    return wrapper


def log_policy_decision(func):  # noqa: ANN001, ANN201
    """Decorator for conditional routing functions.

    Handles functions that return strings ("pass"/"fail",
    "path_a"/"path_b") or dicts. Logs the return value as
    policy_decision in the LogContext.

    Builds LogContext from the first positional arg (state dict).
    """
    _logger = logging.getLogger(func.__module__ or __name__)
    module_name = _get_module_name(func)

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        ctx = _extract_log_ctx(args, kwargs)
        if ctx.agent_role is None:
            ctx = ctx.with_update(agent_role=module_name)

        try:
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Extract decision from result
            decision = str(result) if isinstance(result, str) else ""

            ctx = ctx.with_update(
                latency_ms=round(elapsed_ms, 1),
                policy_decision=decision,
            )

            _logger.info(
                f"POLICY DECISION: {func.__name__} → {decision}",
                extra=ctx.to_dict(),
            )
            return result

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _logger.error(
                f"POLICY DECISION FAILED: {func.__name__} — {type(exc).__name__}: {exc}",
                extra=ctx.with_update(latency_ms=round(elapsed_ms, 1)).to_dict(),
            )
            raise

    return wrapper
