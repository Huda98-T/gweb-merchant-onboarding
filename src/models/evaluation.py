"""AI-assisted evaluation models (spec §2.2 EVAL#, §3 evaluate/evaluation).

EVAL#LATEST is a single-slot item (per-application "current evaluation"),
not per-call EVAL#<evalId> history — approved deviation: matches spec
§2.3's own listed alternative ("or maintain EVAL#LATEST pointer"), and
`GET /evaluation` has no evalId in its path anyway.

Deterministic numbers (statementMetrics, effectiveRate) and AI text
(aiCommentary) are separate model classes on purpose — nothing in
AiCommentaryOutput can carry a number that overrides rate_calculation_service's
output; riskFlags are likewise never AI-authored (see risk_flag_service.py).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluationStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class RiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskFlag(BaseModel):
    """Deterministic only — see risk_flag_service.py. `field` is always a
    real dot-path into the application data that triggered the flag."""

    model_config = ConfigDict(populate_by_name=True)

    field: str
    message: str
    severity: RiskSeverity


class StatementMetrics(BaseModel):
    """Derived from BUSINESS.volumeMetrics (Phase 1 data) — no OCR, no
    parsing of statementDocId's actual bytes."""

    model_config = ConfigDict(populate_by_name=True)

    monthly_volume: float = Field(alias="monthlyVolume")
    average_ticket: float | None = Field(default=None, alias="averageTicket")
    current_processing_rate: float | None = Field(default=None, alias="currentProcessingRate")
    transaction_count: int | None = Field(default=None, alias="transactionCount")
    per_transaction_fee: float | None = Field(default=None, alias="perTransactionFee")


class AiCommentaryOutput(BaseModel):
    """Strict schema for AI-adapter output — text only, no numeric fields
    exist on this model, so AI cannot supply a number even by accident.
    Treated as untrusted regardless of which provider produced it; the
    orchestrator always re-validates a raw dict against this schema."""

    model_config = ConfigDict(populate_by_name=True)

    summary: str = Field(min_length=1)
    highlights: list[str] = Field(default_factory=list)


class AiCommentaryContext(BaseModel):
    """Trusted input built by the orchestrator — the AI-input allowlist.
    No personId/dob/address/idLast4/checksums/raw document bytes."""

    model_config = ConfigDict(populate_by_name=True)

    mcc_code: str | None = None
    mcc_description: str | None = None
    risk_tier: str | None = None
    effective_rate: float
    monthly_volume: float
    risk_flag_messages: list[str] = Field(default_factory=list)


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId", min_length=1)
    statement_doc_id: str | None = Field(default=None, alias="statementDocId")


class EvaluateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    eval_id: str = Field(alias="evalId")
    status: EvaluationStatus
    statement_metrics: StatementMetrics | None = Field(default=None, alias="statementMetrics")
    effective_rate: float | None = Field(default=None, alias="effectiveRate")
    ai_commentary: AiCommentaryOutput | None = Field(default=None, alias="aiCommentary")
    risk_flags: list[RiskFlag] = Field(default_factory=list, alias="riskFlags")


class GetEvaluationResponse(BaseModel):
    """`GET /applications/{id}/evaluation` — spec §3 (no evalId in this shape)."""

    model_config = ConfigDict(populate_by_name=True)

    status: EvaluationStatus
    statement_metrics: StatementMetrics | None = Field(default=None, alias="statementMetrics")
    effective_rate: float | None = Field(default=None, alias="effectiveRate")
    ai_commentary: AiCommentaryOutput | None = Field(default=None, alias="aiCommentary")
    risk_flags: list[RiskFlag] = Field(default_factory=list, alias="riskFlags")


class EvalItem(BaseModel):
    """`PK = APP#<appId>`, `SK = EVAL#LATEST`."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(default="EVAL#LATEST", alias="SK")
    eval_id: str = Field(alias="evalId")
    status: EvaluationStatus
    statement_metrics: StatementMetrics | None = Field(default=None, alias="statementMetrics")
    effective_rate: float | None = Field(default=None, alias="effectiveRate")
    ai_commentary: AiCommentaryOutput | None = Field(default=None, alias="aiCommentary")
    risk_flags: list[RiskFlag] = Field(default_factory=list, alias="riskFlags")
    failure_reason: str | None = Field(default=None, alias="failureReason")
    generated_at: str = Field(alias="generatedAt")
    last_request_id: str | None = Field(default=None, alias="lastRequestId")
    last_response: dict[str, Any] | None = Field(default=None, alias="lastResponse")
