"""Orchestrates AI-assisted evaluation: budget check -> deterministic rate
calc -> deterministic risk flags -> timeout-wrapped AI commentary call ->
persist EVAL#LATEST. Mirrors document_service.py's/mcc_service.py's role.

Separation of concerns is structural, not just convention: rate_calculation_
service and risk_flag_service are called here directly and their outputs
are placed into the response before the AI adapter is ever invoked — the
AI call only receives already-final numbers (AiCommentaryContext) and can
only return text (AiCommentaryOutput has no numeric fields).
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from adapters.ai.base import AiProvider
from adapters.ai.mock_provider import MockAiProvider
from adapters.db import dynamo_client
from common.decimal_utils import from_decimal, to_decimal
from common.errors import NotFoundError, RequestValidationError, UpstreamTimeoutError
from common.logger import get_logger
from common.timeouts import (
    EVALUATION_AI_CALL_MIN_REMAINING_MS,
    outbound_call_timeout_seconds,
    remaining_ms,
)
from models.evaluation import (
    AiCommentaryContext,
    AiCommentaryOutput,
    EvalItem,
    EvaluateRequest,
    EvaluateResponse,
    EvaluationStatus,
    GetEvaluationResponse,
)
from services import mcc_catalog_service, rate_calculation_service, risk_flag_service

logger = get_logger(__name__)

_FALLBACK_SUMMARY = (
    "AI commentary is unavailable for this evaluation; deterministic figures above are unaffected."
)


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


def _call_ai_with_timeout(
    provider: AiProvider, context: AiCommentaryContext, timeout_seconds: float
) -> AiCommentaryOutput:
    """Hard-deadlines the adapter call. A Python thread that's still
    blocked past the timeout can't be forcibly killed — we simply stop
    waiting for it, which is what protects the Lambda's own response
    budget (the frozen/recycled execution environment handles cleanup).

    Deliberately NOT a `with ThreadPoolExecutor(...) as executor:` block —
    its __exit__ calls shutdown(wait=True), which would block until the
    hung thread actually finishes, silently defeating the timeout below.
    `shutdown(wait=False)` lets this function return immediately instead.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(provider.generate_commentary, context)
    try:
        raw = future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        executor.shutdown(wait=False)
        raise UpstreamTimeoutError("AI commentary call timed out") from exc
    executor.shutdown(wait=False)

    try:
        return AiCommentaryOutput.model_validate(raw)
    except ValidationError:
        logger.warning("ai_output_validation_failed")
        return AiCommentaryOutput(summary=_FALLBACK_SUMMARY, highlights=[])


def evaluate_application(
    application_id: str, request: EvaluateRequest, context, ai_provider: AiProvider | None = None
) -> EvaluateResponse:
    pk = _application_pk(application_id)
    items = {i["SK"]: from_decimal(i) for i in dynamo_client.query_by_pk(pk)}
    if "META" not in items:
        raise NotFoundError("Application not found")

    existing_eval = items.get("EVAL#LATEST")
    if existing_eval is not None:
        cached = _idempotent_replay(existing_eval, request.request_id, EvaluateResponse)
        if cached is not None:
            return cached

    if remaining_ms(context) < EVALUATION_AI_CALL_MIN_REMAINING_MS:
        eval_id = uuid.uuid4().hex
        response = EvaluateResponse(eval_id=eval_id, status=EvaluationStatus.PROCESSING)
        _persist(pk, eval_id, response, request.request_id)
        return response

    business_item = items.get("BUSINESS")
    if business_item is None:
        raise RequestValidationError("Business profile must be completed before evaluation")

    statement_metrics = rate_calculation_service.build_statement_metrics(business_item)
    effective_rate = rate_calculation_service.compute_effective_rate(statement_metrics)

    mcc_confirmed = items.get("MCC#CONFIRMED")
    statement_doc = (
        items.get(f"DOC#{request.statement_doc_id}") if request.statement_doc_id else None
    )
    risk_flags = risk_flag_service.compute_risk_flags(
        statement_metrics=statement_metrics,
        effective_rate=effective_rate,
        mcc_confirmed=mcc_confirmed,
        statement_doc_id=request.statement_doc_id,
        statement_doc=statement_doc,
    )

    mcc_code = mcc_confirmed.get("code") if mcc_confirmed else None
    mcc_catalog_entry = mcc_catalog_service.get_entry(mcc_code) if mcc_code else None

    ai_context = AiCommentaryContext(
        mcc_code=mcc_code,
        mcc_description=mcc_catalog_entry.get("description") if mcc_catalog_entry else None,
        risk_tier=mcc_confirmed.get("riskTier") if mcc_confirmed else None,
        effective_rate=effective_rate,
        monthly_volume=statement_metrics.monthly_volume,
        risk_flag_messages=[f.message for f in risk_flags],
    )

    eval_id = uuid.uuid4().hex
    try:
        ai_commentary = _call_ai_with_timeout(
            ai_provider or MockAiProvider(), ai_context, outbound_call_timeout_seconds(context)
        )
    except UpstreamTimeoutError:
        failed = EvaluateResponse(eval_id=eval_id, status=EvaluationStatus.FAILED)
        _persist(
            pk, eval_id, failed, request.request_id, failure_reason="AI commentary call timed out"
        )
        raise

    response = EvaluateResponse(
        eval_id=eval_id,
        status=EvaluationStatus.COMPLETE,
        statement_metrics=statement_metrics,
        effective_rate=effective_rate,
        ai_commentary=ai_commentary,
        risk_flags=risk_flags,
    )
    _persist(pk, eval_id, response, request.request_id)
    return response


def _persist(
    pk: str,
    eval_id: str,
    response: EvaluateResponse,
    request_id: str,
    *,
    failure_reason: str | None = None,
) -> None:
    item = EvalItem(
        pk=pk,
        eval_id=eval_id,
        status=response.status,
        statement_metrics=response.statement_metrics,
        effective_rate=response.effective_rate,
        ai_commentary=response.ai_commentary,
        risk_flags=response.risk_flags,
        failure_reason=failure_reason,
        generated_at=_utc_now_iso(),
        last_request_id=request_id,
        last_response=response.model_dump(by_alias=True, exclude_none=True),
    )
    dynamo_client.put_item(to_decimal(item.model_dump(by_alias=True, exclude_none=True)))


def get_evaluation(application_id: str) -> GetEvaluationResponse:
    pk = _application_pk(application_id)
    dynamo_client.get_item_or_404(pk, "META", not_found_message="Application not found")
    eval_item = dynamo_client.get_item(pk, "EVAL#LATEST")
    if eval_item is None:
        raise NotFoundError("No evaluation has been requested for this application yet")
    return GetEvaluationResponse.model_validate(from_decimal(eval_item))
