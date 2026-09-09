"""AiProvider interface — replaceable adapter (spec §11).

`generate_commentary` returns a raw `dict`, not `AiCommentaryOutput`,
deliberately: the return value is untrusted regardless of which provider
produced it (mock or real), so evaluation_service always re-validates it
against the strict schema rather than trusting a type hint. The context
argument is the trusted, already-built AI-input allowlist (no PII, no raw
document bytes) — see AiCommentaryContext.

No timeout parameter here — timeout enforcement is the orchestrator's job
(wraps any provider call in a hard deadline), so a future real provider
doesn't need to reimplement it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from models.evaluation import AiCommentaryContext


class AiProvider(ABC):
    @abstractmethod
    def generate_commentary(self, context: AiCommentaryContext) -> dict[str, Any]:
        """Return a dict shaped like AiCommentaryOutput — not guaranteed
        valid; the caller must validate before trusting it."""
