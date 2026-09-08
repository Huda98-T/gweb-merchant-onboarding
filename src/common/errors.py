"""Application-level errors and the handler error-wrapping decorator.

Every handler is wrapped with `@handle_errors`, which converts known error
types into the right HTTP status code and a clean JSON body, and turns
anything unexpected into a generic 500 (never leaking internals to the
client). See GWEB_Implementation_Spec.md §11 / §10.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from common.logger import get_logger
from common.responses import build_response

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for errors that should be surfaced to the client as-is."""

    status_code = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    """Raised on optimistic-concurrency (version mismatch) failures."""

    status_code = 409


class RequestValidationError(AppError):
    """Raised for malformed/invalid request input (body, path, headers)."""

    status_code = 400


class UnauthorizedError(AppError):
    status_code = 401


def handle_errors(handler: Callable[..., dict]) -> Callable[..., dict]:
    """Decorator wrapping a Lambda handler with consistent error responses."""

    @functools.wraps(handler)
    def wrapper(event: dict, context: Any) -> dict:
        try:
            return handler(event, context)
        except ValidationError as exc:
            logger.warning("request_validation_failed", extra={"errors": exc.errors()})
            return build_response(
                400,
                {"message": "Invalid request body", "errors": exc.errors()},
            )
        except AppError as exc:
            logger.warning(
                "app_error",
                extra={"status_code": exc.status_code, "message": exc.message},
            )
            body = {"message": exc.message}
            if exc.details:
                body.update(exc.details)
            return build_response(exc.status_code, body)
        except Exception:
            logger.exception("unhandled_error")
            return build_response(500, {"message": "Internal server error"})

    return wrapper
