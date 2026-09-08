"""Structured, redaction-aware logging.

Emits JSON log records (CloudWatch Logs friendly) and redacts field names
that commonly carry PII before they ever reach the log line, so a handler
can log a data dict without having to remember to scrub it by hand.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

# Field names redacted wherever they appear in a logged `extra` payload,
# no matter which item/model they came from.
REDACTED_FIELDS = {
    "dob",
    "address",
    "idLast4",
    "id_last4",
    "checksum",
    "consentTimestamp",
    "consent_timestamp",
    "firstName",
    "first_name",
    "lastName",
    "last_name",
    "uploadUrl",
    "upload_url",
    "presignedUrl",
    "presigned_url",
}
REDACTED_PLACEHOLDER = "***REDACTED***"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED_PLACEHOLDER if k in REDACTED_FIELDS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload["data"] = _redact(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _RedactingLoggerAdapter(logging.LoggerAdapter):
    """Lets call sites pass `extra={...}` naturally; stores it for the formatter."""

    def process(self, msg: str, kwargs: dict) -> tuple:
        extra = kwargs.pop("extra", None)
        kwargs["extra"] = {"extra_fields": extra} if extra else {}
        return msg, kwargs


def get_logger(name: str) -> logging.LoggerAdapter:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
        logger.propagate = False
    return _RedactingLoggerAdapter(logger, {})
