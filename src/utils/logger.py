"""Structured JSON logging setup for VQMS.

Configures structlog to produce JSON-formatted logs with
correlation IDs, timestamps, and caller info. All modules
use standard logging.getLogger(__name__) — structlog wraps
it automatically after setup_logging() is called.

Logs go to two destinations:
  1. Console (stdout) — human-readable in DEBUG, JSON otherwise
  2. File (data/logs/) — always JSON, one file per day with rotation

The log directory (data/logs/) is created automatically if missing.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

# Log files go here — relative to project root
LOG_DIR = Path("data/logs")

# Rotate log files at 10 MB, keep last 5 rotated files
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5


def _ensure_log_dir() -> Path:
    """Create the log directory if it does not exist.

    Returns the absolute path to the log directory.
    """
    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


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
        log_filename: Custom log filename. If None, uses
            'vqms_YYYY-MM-DD.log' based on current date.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.DEBUG)

    # Structlog processors that run on every log entry
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Configure structlog to wrap stdlib loggers
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
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer()
            if log_level.upper() == "DEBUG"
            else structlog.processors.JSONRenderer(),
        ],
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
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                log_filename = f"vqms_{today}.log"

            log_path = log_dir / log_filename

            file_formatter = structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
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

    # Silence noisy third-party loggers
    for noisy_logger in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog-wrapped logger for the given module name.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A bound logger that produces structured output.
    """
    return structlog.get_logger(name)
