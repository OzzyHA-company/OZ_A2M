"""Structured logging for OZ_A2M."""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict

import structlog
from pythonjsonlogger import jsonlogger


def _add_timestamp(logger, method_name, event_dict):
    """Add timestamp to event."""
    event_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"
    return event_dict


def _add_service_name(logger, method_name, event_dict):
    """Add service name to event."""
    event_dict["service"] = "oz_a2m"
    return event_dict


def setup_logging(log_level: str = "INFO", log_format: str = "json"):
    """Setup structured logging."""
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    pre_chain = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
    ]

    if log_format == "json":
        formatter = jsonlogger.JsonFormatter(
            "%(timestamp)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "level", "name": "logger"},
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, log_level.upper()))

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if log_format == "json" else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get structured logger."""
    return structlog.get_logger(name)
