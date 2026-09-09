"""MockAiProvider — the only AiProvider implementation in Phase 4.

Deterministic (same context -> same output, no randomness) and template-
based: it only arranges numbers and MCC text the orchestrator already
computed into sentences. It never invents a number of its own.
"""

from __future__ import annotations

from typing import Any

from adapters.ai.base import AiProvider
from models.evaluation import AiCommentaryContext


class MockAiProvider(AiProvider):
    def generate_commentary(self, context: AiCommentaryContext) -> dict[str, Any]:
        if context.mcc_code:
            classification = f"MCC {context.mcc_code} ({context.mcc_description})"
        else:
            classification = "no confirmed MCC"

        summary = (
            f"This business is classified as {classification}, with an effective "
            f"processing rate of {context.effective_rate:.2%} on "
            f"${context.monthly_volume:,.0f} in monthly volume. "
            f"{len(context.risk_flag_messages)} risk flag(s) were identified."
        )
        return {"summary": summary, "highlights": list(context.risk_flag_messages)}
