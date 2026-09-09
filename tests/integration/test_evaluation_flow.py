"""Full evaluate -> poll flow through the real handlers, against moto.
Includes the slow/hanging AI-adapter timeout test (design constraint:
prove it's actually caught within budget, not mocked away).
"""

from __future__ import annotations

import json
import time

from adapters.ai.base import AiProvider
from handlers import (
    classify_mcc,
    confirm_mcc,
    create_application,
    evaluate,
    get_application,
    get_evaluation,
    patch_business,
)
from models.evaluation import EvaluateRequest
from services import evaluation_service
from tests.conftest import FakeLambdaContext

CONTEXT = FakeLambdaContext()  # 45_000ms remaining — plenty of budget


class _NearlyExpiredContext:
    """Below EVALUATION_AI_CALL_MIN_REMAINING_MS — forces the PROCESSING preflight branch."""

    def get_remaining_time_in_millis(self) -> int:
        return 5_000


class _JustEnoughBudgetContext:
    """Just above the preflight threshold — the AI call is attempted, but
    outbound_call_timeout_seconds() works out to a few seconds, keeping
    the hang test's real wall-clock wait short."""

    def get_remaining_time_in_millis(self) -> int:
        return 10_100


class _HangingAiProvider(AiProvider):
    def generate_commentary(self, context):
        time.sleep(10)  # longer than _JustEnoughBudgetContext's ~6s timeout
        return {"summary": "should never be seen", "highlights": []}


def _event(*, path_id: str, token: str, body: dict | None = None) -> dict:
    event: dict = {"pathParameters": {"id": path_id}, "headers": {"x-application-token": token}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def _create_application() -> str:
    return _body(create_application.handler({"headers": {}}, CONTEXT))["applicationId"]


def _set_business_volume_metrics(app_id: str, **volume_metrics) -> None:
    patch_business.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "biz-1",
                "legalName": "Ada's Bakery LLC",
                "entityType": "LLC",
                "registrationId": "EIN-123",
                "addresses": {"business": {"line1": "1 Main St"}},
                "volumeMetrics": volume_metrics,
            },
        ),
        CONTEXT,
    )


def test_evaluate_happy_path_returns_complete_with_separated_numbers_and_commentary(dynamodb_table):
    app_id = _create_application()
    _set_business_volume_metrics(
        app_id,
        monthlyVolume=50000,
        currentProcessingRate=0.029,
        transactionCount=500,
        perTransactionFee=0.10,
    )

    response = evaluate.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "r1"}), CONTEXT
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["status"] == "COMPLETE"
    assert body["effectiveRate"] == 0.03
    assert body["statementMetrics"]["monthlyVolume"] == 50000
    assert body["aiCommentary"]["summary"]
    assert isinstance(body["riskFlags"], list)
    # deterministic numbers are not present anywhere inside the AI text as
    # a different, AI-invented value — the only rate mentioned is ours.
    assert "3.00%" in body["aiCommentary"]["summary"]


def test_evaluate_requires_matching_token(dynamodb_table):
    app_id = _create_application()
    response = evaluate.handler(
        _event(path_id=app_id, token="wrong", body={"requestId": "r1"}), CONTEXT
    )
    assert response["statusCode"] == 401


def test_evaluate_returns_404_for_unknown_application(dynamodb_table):
    response = evaluate.handler(
        _event(path_id="ghost", token="ghost", body={"requestId": "r1"}), CONTEXT
    )
    assert response["statusCode"] == 404


def test_evaluate_requires_business_profile_first(dynamodb_table):
    app_id = _create_application()
    response = evaluate.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "r1"}), CONTEXT
    )
    assert response["statusCode"] == 400


def test_evaluate_is_idempotent_on_repeated_request_id(dynamodb_table):
    app_id = _create_application()
    _set_business_volume_metrics(app_id, monthlyVolume=1000, currentProcessingRate=0.02)
    body = {"requestId": "r-retry"}
    first = _body(evaluate.handler(_event(path_id=app_id, token=app_id, body=body), CONTEXT))
    second = _body(evaluate.handler(_event(path_id=app_id, token=app_id, body=body), CONTEXT))
    assert first == second


def test_evaluate_flags_enhanced_review_mcc_and_cites_it(dynamodb_table):
    app_id = _create_application()
    _set_business_volume_metrics(app_id, monthlyVolume=1000, currentProcessingRate=0.02)
    classify_mcc.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={"requestId": "c1", "selfSelectedActivity": "Money order"},
        ),
        CONTEXT,
    )
    confirm_mcc.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "cf1", "code": "6051"}), CONTEXT
    )

    body = _body(
        evaluate.handler(_event(path_id=app_id, token=app_id, body={"requestId": "r1"}), CONTEXT)
    )
    flag = next(f for f in body["riskFlags"] if f["field"] == "mcc.confirmed.riskTier")
    assert "6051" in flag["message"]
    assert flag["severity"] == "HIGH"


def test_evaluate_low_budget_returns_processing_without_calling_ai(dynamodb_table, monkeypatch):
    app_id = _create_application()
    _set_business_volume_metrics(app_id, monthlyVolume=1000, currentProcessingRate=0.02)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("AI provider must not be called when budget is too low")

    monkeypatch.setattr(
        evaluation_service, "_call_ai_with_timeout", lambda *a, **k: _fail_if_called()
    )

    response = evaluate.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "r1"}), _NearlyExpiredContext()
    )
    assert response["statusCode"] == 202
    body = _body(response)
    assert body["status"] == "PROCESSING"

    poll = _body(get_evaluation.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    assert poll["status"] == "PROCESSING"


def test_evaluate_hanging_ai_call_times_out_within_budget_and_persists_failed(dynamodb_table):
    app_id = _create_application()
    _set_business_volume_metrics(app_id, monthlyVolume=1000, currentProcessingRate=0.02)

    started = time.monotonic()
    try:
        evaluation_service.evaluate_application(
            app_id,
            EvaluateRequest(requestId="r1"),
            _JustEnoughBudgetContext(),
            ai_provider=_HangingAiProvider(),
        )
        raised = False
    except Exception:
        raised = True
    elapsed = time.monotonic() - started

    assert raised
    assert elapsed < 9  # caught well before the provider's own 10s sleep would return
    poll = _body(get_evaluation.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    assert poll["status"] == "FAILED"


def test_get_evaluation_returns_404_before_any_evaluate_call(dynamodb_table):
    app_id = _create_application()
    response = get_evaluation.handler(_event(path_id=app_id, token=app_id), CONTEXT)
    assert response["statusCode"] == 404


def test_get_evaluation_requires_matching_token(dynamodb_table):
    app_id = _create_application()
    response = get_evaluation.handler(_event(path_id=app_id, token="wrong"), CONTEXT)
    assert response["statusCode"] == 401


def test_evaluation_is_visible_in_application_aggregate(dynamodb_table):
    app_id = _create_application()
    _set_business_volume_metrics(app_id, monthlyVolume=1000, currentProcessingRate=0.02)
    evaluate.handler(_event(path_id=app_id, token=app_id, body={"requestId": "r1"}), CONTEXT)

    state = _body(get_application.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    assert state["evaluation"]["status"] == "COMPLETE"
    assert state["evaluation"]["effectiveRate"] == 0.02
