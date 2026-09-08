"""Timeout-budget helper — see GWEB_Implementation_Spec.md §1.3.

Not exercised by the Phase 1 handlers (none make outbound calls yet), but
provided now as shared infrastructure for the document/AI-adapter handlers
that will use it to decide when to fall back to the async PROCESSING path.
"""

from __future__ import annotations

from typing import Protocol

SOFT_DEADLINE_MS = 30_000
OUTBOUND_CALL_BUDGET_FRACTION = 0.6


class LambdaContext(Protocol):
    def get_remaining_time_in_millis(self) -> int: ...


def remaining_ms(context: LambdaContext) -> int:
    return context.get_remaining_time_in_millis()


def is_near_soft_deadline(context: LambdaContext) -> bool:
    """True once less than the soft deadline remains in this invocation."""
    return remaining_ms(context) <= SOFT_DEADLINE_MS


def outbound_call_timeout_seconds(context: LambdaContext) -> float:
    """Timeout to apply to an outbound call starting now: ~60% of what's left."""
    return max(remaining_ms(context) * OUTBOUND_CALL_BUDGET_FRACTION / 1000, 0.0)
