"""Full MCC search -> classify -> confirm flow through the real handlers,
against moto. Decisions #1/#2/#4/#6.
"""

from __future__ import annotations

import json

from handlers import classify_mcc, confirm_mcc, create_application, get_application, search_mcc
from tests.conftest import FakeLambdaContext

CONTEXT = FakeLambdaContext()


def _event(
    *,
    path_id: str | None = None,
    token: str | None = None,
    body: dict | None = None,
    query: str | None = None,
) -> dict:
    event: dict = {"headers": {}}
    if path_id is not None:
        event["pathParameters"] = {"id": path_id}
    if token is not None:
        event["headers"]["x-application-token"] = token
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {"query": query}
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def _create_application() -> str:
    return _body(create_application.handler({"headers": {}}, CONTEXT))["applicationId"]


def test_search_mcc_requires_no_auth_and_returns_matches(dynamodb_table):
    response = search_mcc.handler(_event(query="restaurant"), CONTEXT)
    assert response["statusCode"] == 200
    codes = {r["code"] for r in _body(response)["results"]}
    assert "5812" in codes


def test_search_mcc_returns_400_for_missing_query(dynamodb_table):
    response = search_mcc.handler(_event(), CONTEXT)
    assert response["statusCode"] == 400


def test_classify_happy_path_persists_proposal(dynamodb_table):
    app_id = _create_application()
    response = classify_mcc.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "r1",
                "selfSelectedActivity": "Restaurant",
                "businessDescription": "Pizza",
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["candidates"]
    assert body["candidates"][0]["code"] == "5812"

    state = _body(get_application.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    assert state["mcc"]["proposed"]["candidates"][0]["code"] == "5812"
    assert state["mcc"]["confirmed"] is None


def test_classify_requires_matching_token(dynamodb_table):
    app_id = _create_application()
    response = classify_mcc.handler(
        _event(
            path_id=app_id,
            token="wrong",
            body={"requestId": "r1", "selfSelectedActivity": "Restaurant"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 401


def test_classify_returns_404_for_unknown_application(dynamodb_table):
    response = classify_mcc.handler(
        _event(
            path_id="ghost",
            token="ghost",
            body={"requestId": "r1", "selfSelectedActivity": "Restaurant"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 404


def test_classify_is_idempotent_on_repeated_request_id(dynamodb_table):
    app_id = _create_application()
    body = {"requestId": "r-retry", "selfSelectedActivity": "Restaurant"}
    first = _body(classify_mcc.handler(_event(path_id=app_id, token=app_id, body=body), CONTEXT))
    second = _body(classify_mcc.handler(_event(path_id=app_id, token=app_id, body=body), CONTEXT))
    assert first == second


def test_classify_strong_match_on_enhanced_review_code_requires_manual_review_via_policy(
    dynamodb_table,
):
    # Confidence is well above the 0.5 low-confidence threshold, isolating
    # that requiresManualReview here is driven by risk policy, not by a
    # weak match.
    app_id = _create_application()
    response = classify_mcc.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={"requestId": "r1", "selfSelectedActivity": "Security Brokers/Dealers"},
        ),
        CONTEXT,
    )
    body = _body(response)
    assert body["candidates"][0]["code"] == "6211"
    assert body["candidates"][0]["confidence"] >= 0.5
    assert body["requiresManualReview"] is True


def test_confirm_happy_path_persists_confirmation(dynamodb_table):
    app_id = _create_application()
    response = confirm_mcc.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "r1", "code": "5812"}), CONTEXT
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["code"] == "5812"
    assert body["riskTier"] == "STANDARD"
    assert body["requiresManualReview"] is False

    state = _body(get_application.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    assert state["mcc"]["confirmed"]["code"] == "5812"


def test_confirm_allows_correcting_to_a_different_code_than_proposed(dynamodb_table):
    app_id = _create_application()
    classify_mcc.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={"requestId": "r1", "selfSelectedActivity": "Restaurant"},
        ),
        CONTEXT,
    )
    confirm_response = confirm_mcc.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "r2", "code": "5411"}), CONTEXT
    )
    assert confirm_response["statusCode"] == 200
    body = _body(confirm_response)
    assert body["code"] == "5411"  # applicant corrected away from the proposed 5812

    state = _body(get_application.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    assert state["mcc"]["proposed"]["candidates"][0]["code"] == "5812"  # what the system proposed
    assert state["mcc"]["confirmed"]["code"] == "5411"  # what the applicant confirmed


def test_confirm_works_without_a_prior_classify_call(dynamodb_table):
    app_id = _create_application()
    response = confirm_mcc.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "r1", "code": "5812"}), CONTEXT
    )
    assert response["statusCode"] == 200
    state = _body(get_application.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    assert state["mcc"]["proposed"] is None
    assert state["mcc"]["confirmed"]["code"] == "5812"


def test_confirm_rejects_unknown_code(dynamodb_table):
    app_id = _create_application()
    response = confirm_mcc.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "r1", "code": "0000"}), CONTEXT
    )
    assert response["statusCode"] == 400


def test_confirm_requires_matching_token(dynamodb_table):
    app_id = _create_application()
    response = confirm_mcc.handler(
        _event(path_id=app_id, token="wrong", body={"requestId": "r1", "code": "5812"}), CONTEXT
    )
    assert response["statusCode"] == 401


def test_confirm_returns_404_for_unknown_application(dynamodb_table):
    response = confirm_mcc.handler(
        _event(path_id="ghost", token="ghost", body={"requestId": "r1", "code": "5812"}), CONTEXT
    )
    assert response["statusCode"] == 404


def test_confirm_is_idempotent_on_repeated_request_id(dynamodb_table):
    app_id = _create_application()
    body = {"requestId": "r-retry", "code": "5812"}
    first = _body(confirm_mcc.handler(_event(path_id=app_id, token=app_id, body=body), CONTEXT))
    second = _body(confirm_mcc.handler(_event(path_id=app_id, token=app_id, body=body), CONTEXT))
    assert first == second


def test_confirm_6012_is_enhanced_review_and_reason_is_not_mislabeled_quasi_cash(dynamodb_table):
    app_id = _create_application()
    body = _body(
        confirm_mcc.handler(
            _event(path_id=app_id, token=app_id, body={"requestId": "r1", "code": "6012"}), CONTEXT
        )
    )
    assert body["riskTier"] == "ENHANCED_REVIEW"
    assert "quasi" not in body["riskReason"].lower()
    assert body["requiresManualReview"] is True


def test_confirm_6051_is_enhanced_review_and_reason_mentions_quasi_cash(dynamodb_table):
    app_id = _create_application()
    body = _body(
        confirm_mcc.handler(
            _event(path_id=app_id, token=app_id, body={"requestId": "r1", "code": "6051"}), CONTEXT
        )
    )
    assert body["riskTier"] == "ENHANCED_REVIEW"
    assert "quasi-cash" in body["riskReason"].lower()


def test_confirm_6211_is_enhanced_review_and_reason_mentions_securities_brokerage(dynamodb_table):
    app_id = _create_application()
    body = _body(
        confirm_mcc.handler(
            _event(path_id=app_id, token=app_id, body={"requestId": "r1", "code": "6211"}), CONTEXT
        )
    )
    assert body["riskTier"] == "ENHANCED_REVIEW"
    assert "securities brokerage" in body["riskReason"].lower()
