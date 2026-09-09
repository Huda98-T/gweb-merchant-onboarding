"""MCC classification models — catalog search, deterministic classification,
and applicant confirmation/correction (spec §2.2/§3, refined by the
approved Phase 3 decisions).

MCC#PROPOSED and MCC#CONFIRMED stay separate DynamoDB items (decision #1)
so the audit trail shows both what the system proposed and what the
applicant ultimately confirmed — deliberately not collapsed into one item.
The catalog and risk policy are NOT DynamoDB items (decision #5): they are
packaged static files, loaded once and cached (see mcc_catalog_service.py).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RiskTier(StrEnum):
    STANDARD = "STANDARD"
    ENHANCED_REVIEW = "ENHANCED_REVIEW"
    RESTRICTED = "RESTRICTED"


class CatalogSearchResult(BaseModel):
    """One row of `GET /mcc?query=`."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    description: str
    category: str


class SearchMccResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    results: list[CatalogSearchResult] = Field(default_factory=list)


class MccCandidate(BaseModel):
    """One classification candidate — also the shape stored in
    MCC#PROPOSED's `candidates` list."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    description: str
    confidence: float
    reason: str


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId", min_length=1)
    self_selected_activity: str = Field(alias="selfSelectedActivity", min_length=1)
    business_description: str | None = Field(default=None, alias="businessDescription")


class ClassifyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    candidates: list[MccCandidate] = Field(default_factory=list)
    requires_manual_review: bool = Field(alias="requiresManualReview")


class ConfirmMccRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId", min_length=1)
    code: str = Field(min_length=1)
    self_selected_activity: str | None = Field(default=None, alias="selfSelectedActivity")


class ConfirmMccResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    confirmed_at: str = Field(alias="confirmedAt")
    risk_tier: RiskTier = Field(alias="riskTier")
    risk_reason: str = Field(alias="riskReason")
    requires_manual_review: bool = Field(alias="requiresManualReview")


class MccProposedItem(BaseModel):
    """`PK = APP#<appId>`, `SK = MCC#PROPOSED`."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(default="MCC#PROPOSED", alias="SK")
    candidates: list[MccCandidate] = Field(default_factory=list)
    requires_manual_review: bool = Field(alias="requiresManualReview")
    generated_at: str = Field(alias="generatedAt")
    self_selected_activity: str = Field(alias="selfSelectedActivity")
    business_description: str | None = Field(default=None, alias="businessDescription")
    last_request_id: str | None = Field(default=None, alias="lastRequestId")
    last_response: dict[str, Any] | None = Field(default=None, alias="lastResponse")


class MccConfirmedItem(BaseModel):
    """`PK = APP#<appId>`, `SK = MCC#CONFIRMED`."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(default="MCC#CONFIRMED", alias="SK")
    code: str
    confirmed_at: str = Field(alias="confirmedAt")
    self_selected_activity: str | None = Field(default=None, alias="selfSelectedActivity")
    risk_tier: RiskTier = Field(alias="riskTier")
    risk_reason: str = Field(alias="riskReason")
    provider: str = "default"
    last_request_id: str | None = Field(default=None, alias="lastRequestId")
    last_response: dict[str, Any] | None = Field(default=None, alias="lastResponse")


class MccProposedView(BaseModel):
    """Nested under `GET /applications/{id}`'s `mcc.proposed`."""

    model_config = ConfigDict(populate_by_name=True)

    candidates: list[MccCandidate] = Field(default_factory=list)
    requires_manual_review: bool = Field(alias="requiresManualReview")
    generated_at: str = Field(alias="generatedAt")
    self_selected_activity: str = Field(alias="selfSelectedActivity")
    business_description: str | None = Field(default=None, alias="businessDescription")


class MccConfirmedView(BaseModel):
    """Nested under `GET /applications/{id}`'s `mcc.confirmed`."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    confirmed_at: str = Field(alias="confirmedAt")
    self_selected_activity: str | None = Field(default=None, alias="selfSelectedActivity")
    risk_tier: RiskTier = Field(alias="riskTier")
    risk_reason: str = Field(alias="riskReason")
    provider: str = "default"


class MccView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    proposed: MccProposedView | None = None
    confirmed: MccConfirmedView | None = None
