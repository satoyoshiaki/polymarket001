"""Structured logging helpers."""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import LoggingConfig


def configure_logging(config: LoggingConfig) -> None:
    """Configure process-wide structured logging."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
    ]
    renderer: structlog.types.Processor
    if config.json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    logging.basicConfig(
        level=getattr(logging, config.level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.EventRenamer("message"),
            structlog.processors.dict_tracebacks,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, config.level.upper(), logging.INFO)
        ),
    )

