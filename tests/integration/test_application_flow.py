"""Full happy-path flow through the Phase 1 Lambda handlers, against moto.

create -> get -> patch applicant -> patch business -> get, plus the
ownership-check, not-found, and idempotent-replay behaviors called out in
spec §2.4 / §3.
"""

from __future__ import annotations

import json

from handlers import create_application, get_application, patch_applicant, patch_business
from tests.conftest import FakeLambdaContext

CONTEXT = FakeLambdaContext()


def _http_event(
    *,
    path_id: str | None = None,
    token: str | None = None,
    body: dict | None = None,
) -> dict:
    event: dict = {"headers": {}}
    if path_id is not None:
        event["pathParameters"] = {"id": path_id}
    if token is not None:
        event["headers"]["x-application-token"] = token
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def test_full_happy_path_create_get_patch_applicant_patch_business(dynamodb_table):
    create_response = create_application.handler({"headers": {}}, CONTEXT)
    assert create_response["statusCode"] == 201
    created = _body(create_response)
    app_id = created["applicationId"]
    assert created["status"] == "DRAFT"
    assert created["version"] == 1

    get_response = get_application.handler(_http_event(path_id=app_id, token=app_id), CONTEXT)
    assert get_response["statusCode"] == 200
    state = _body(get_response)
    assert state["meta"]["status"] == "DRAFT"
    assert state["meta"]["version"] == 1
    assert state["applicant"] == []
    assert state["business"] is None
    assert state["documents"] == []

    applicant_response = patch_applicant.handler(
        _http_event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "req-applicant-1",
                "firstName": "Ada",
                "lastName": "Lovelace",
                "dob": "1990-01-01",
                "address": {"line1": "1 Main St", "city": "London"},
                "role": "controller",
                "ownershipPct": 60.5,
                "idType": "passport",
                "idLast4": "1234",
                "consentVersion": "v1",
            },
        ),
        CONTEXT,
    )
    assert applicant_response["statusCode"] == 200
    applicant_body = _body(applicant_response)
    person_id = applicant_body["personId"]
    assert applicant_body["version"] == 2

    business_response = patch_business.handler(
        _http_event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "req-business-1",
                "legalName": "Ada's Bakery LLC",
                "entityType": "LLC",
                "registrationId": "EIN-123",
                "addresses": {"business": {"line1": "1 Main St"}},
                "volumeMetrics": {"monthlyVolume": 10000.5},
            },
        ),
        CONTEXT,
    )
    assert business_response["statusCode"] == 200
    assert _body(business_response)["version"] == 3

    final_state = _body(get_application.handler(_http_event(path_id=app_id, token=app_id), CONTEXT))
    assert final_state["meta"]["version"] == 3
    assert len(final_state["applicant"]) == 1
    assert final_state["applicant"][0]["personId"] == person_id
    assert final_state["applicant"][0]["firstName"] == "Ada"
    assert final_state["applicant"][0]["ownershipPct"] == 60.5
    assert final_state["business"]["legalName"] == "Ada's Bakery LLC"
    assert final_state["business"]["volumeMetrics"]["monthlyVolume"] == 10000.5


def test_get_application_requires_matching_token(dynamodb_table):
    app_id = _body(create_application.handler({"headers": {}}, CONTEXT))["applicationId"]

    response = get_application.handler(_http_event(path_id=app_id, token="wrong-token"), CONTEXT)
    assert response["statusCode"] == 401


def test_get_application_returns_404_for_unknown_application(dynamodb_table):
    response = get_application.handler(
        _http_event(path_id="does-not-exist", token="does-not-exist"), CONTEXT
    )
    assert response["statusCode"] == 404


def test_patch_applicant_is_idempotent_on_repeated_request_id(dynamodb_table):
    app_id = _body(create_application.handler({"headers": {}}, CONTEXT))["applicationId"]
    payload = {
        "requestId": "req-retry",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "dob": "1990-01-01",
        "address": {"line1": "1 Main St"},
        "role": "controller",
        "idType": "passport",
        "idLast4": "1234",
    }

    first = _body(
        patch_applicant.handler(_http_event(path_id=app_id, token=app_id, body=payload), CONTEXT)
    )
    second = _body(
        patch_applicant.handler(_http_event(path_id=app_id, token=app_id, body=payload), CONTEXT)
    )

    assert first == second  # replayed from the idempotency cache, not reapplied

    state = _body(get_application.handler(_http_event(path_id=app_id, token=app_id), CONTEXT))
    assert len(state["applicant"]) == 1  # no duplicate person created
    assert state["meta"]["version"] == 2  # version only bumped once
