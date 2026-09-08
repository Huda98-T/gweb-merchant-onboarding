"""DynamoDB requires `Decimal` for numbers (rejects native `float`), so
request/response data crosses this conversion at the storage boundary."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_decimal(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_decimal(v) for v in value]
    return value


def from_decimal(value: Any) -> Any:
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if as_int == value else float(value)
    if isinstance(value, dict):
        return {k: from_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_decimal(v) for v in value]
    return value
