"""Orchestrates MCC classification and confirmation for one application:
ties classification_service (pure algorithm), mcc_catalog_service (catalog
+ risk policy), and dynamo_client (MCC#PROPOSED / MCC#CONFIRMED items)
together — mirrors application_service.py's/document_service.py's role.

Idempotency is scoped per-item (MCC#PROPOSED's own lastRequestId/
lastResponse, MCC#CONFIRMED's own) — PATCH-style, like Phase 1's applicant/
business upserts, since both are single-slot "current state" items that a
repeat call safely overwrites rather than a per-call-random-id create.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from adapters.db import dynamo_client
from common.decimal_utils import from_decimal, to_decimal
from common.errors import RequestValidationError
from models.mcc import (
    ClassifyRequest,
    ClassifyResponse,
    ConfirmMccRequest,
    ConfirmMccResponse,
    MccConfirmedItem,
    MccProposedItem,
    RiskTier,
)
from services import classification_service, mcc_catalog_service

LOW_CONFIDENCE_THRESHOLD = 0.5
_DEFAULT_PROVIDER = "default"


def _application_pk(application_id: str) -> str:
    return f"APP#{application_id}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _idempotent_replay[T: BaseModel](
    item: dict, request_id: str, response_model: type[T]
) -> T | None:
    if item.get("lastRequestId") == request_id and item.get("lastResponse"):
        return response_model.model_validate(item["lastResponse"])
    return None


def classify_application(application_id: str, request: ClassifyRequest) -> ClassifyResponse:
    pk = _application_pk(application_id)
    dynamo_client.get_item_or_404(pk, "META", not_found_message="Application not found")

    existing = dynamo_client.get_item(pk, "MCC#PROPOSED")
    if existing is not None:
        cached = _idempotent_replay(from_decimal(existing), request.request_id, ClassifyResponse)
        if cached is not None:
            return cached

    catalog = mcc_catalog_service.all_entries()
    candidates = classification_service.classify(
        request.self_selected_activity, request.business_description, catalog
    )

    requires_manual_review = False
    if candidates:
        top = candidates[0]
        tier, _ = mcc_catalog_service.resolve_risk_tier(top.code, _DEFAULT_PROVIDER)
        requires_manual_review = (
            top.confidence < LOW_CONFIDENCE_THRESHOLD or tier != RiskTier.STANDARD
        )

    response = ClassifyResponse(
        candidates=candidates, requires_manual_review=requires_manual_review
    )

    item = MccProposedItem(
        pk=pk,
        candidates=candidates,
        requires_manual_review=requires_manual_review,
        generated_at=_utc_now_iso(),
        self_selected_activity=request.self_selected_activity,
        business_description=request.business_description,
        last_request_id=request.request_id,
        last_response=response.model_dump(by_alias=True),
    )
    dynamo_client.put_item(to_decimal(item.model_dump(by_alias=True, exclude_none=True)))
    return response


def confirm_mcc(application_id: str, request: ConfirmMccRequest) -> ConfirmMccResponse:
    pk = _application_pk(application_id)
    dynamo_client.get_item_or_404(pk, "META", not_found_message="Application not found")

    if mcc_catalog_service.get_entry(request.code) is None:
        raise RequestValidationError(f"Unknown MCC code: {request.code}")

    existing = dynamo_client.get_item(pk, "MCC#CONFIRMED")
    if existing is not None:
        cached = _idempotent_replay(from_decimal(existing), request.request_id, ConfirmMccResponse)
        if cached is not None:
            return cached

    tier, reason = mcc_catalog_service.resolve_risk_tier(request.code, _DEFAULT_PROVIDER)
    confirmed_at = _utc_now_iso()

    response = ConfirmMccResponse(
        code=request.code,
        confirmed_at=confirmed_at,
        risk_tier=tier,
        risk_reason=reason,
        requires_manual_review=tier != RiskTier.STANDARD,
    )

    item = MccConfirmedItem(
        pk=pk,
        code=request.code,
        confirmed_at=confirmed_at,
        self_selected_activity=request.self_selected_activity,
        risk_tier=tier,
        risk_reason=reason,
        provider=_DEFAULT_PROVIDER,
        last_request_id=request.request_id,
        last_response=response.model_dump(by_alias=True),
    )
    dynamo_client.put_item(to_decimal(item.model_dump(by_alias=True, exclude_none=True)))
    return response
