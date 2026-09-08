"""API Gateway HTTP API (v2) event parsing helpers."""

from __future__ import annotations

import base64
import json
from typing import Any

from common.errors import RequestValidationError


def get_path_param(event: dict, name: str) -> str:
    params = event.get("pathParameters") or {}
    value = params.get(name)
    if not value:
        raise RequestValidationError(f"Missing path parameter: {name}")
    return value


def parse_json_body(event: dict) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RequestValidationError("Request body is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RequestValidationError("Request body must be a JSON object")
    return parsed
