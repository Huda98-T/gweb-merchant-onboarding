"""Timeout-budget helper — see GWEB_Implementation_Spec.md §1.3.

First wired into a handler in Phase 2 (document /complete's S3 HEAD/GET
calls). Kept generic so a later AI-adapter/evaluate handler can reuse it.
"""

from __future__ import annotations

from typing import Protocol

SOFT_DEADLINE_MS = 30_000
OUTBOUND_CALL_BUDGET_FRACTION = 0.6

# Phase 2 (document /complete): with the 45s hard Lambda Timeout, bailing
# out once less than this remains — i.e. once ~35s have already elapsed —
# is the "internal target around 35 seconds" before starting the S3
# GetObject stream, the slowest step in the handler.
DOCUMENT_STREAM_MIN_REMAINING_MS = 10_000


class LambdaContext(Protocol):
    def get_remaining_time_in_millis(self) -> int: ...


def remaining_ms(context: LambdaContext) -> int:
    return context.get_remaining_time_in_millis()


def is_near_soft_deadline(context: LambdaContext, threshold_ms: int = SOFT_DEADLINE_MS) -> bool:
    """True once less than `threshold_ms` remains in this invocation."""
    return remaining_ms(context) <= threshold_ms


def outbound_call_timeout_seconds(context: LambdaContext) -> float:
    """Timeout to apply to an outbound call starting now: ~60% of what's left."""
    return max(remaining_ms(context) * OUTBOUND_CALL_BUDGET_FRACTION / 1000, 0.0)
