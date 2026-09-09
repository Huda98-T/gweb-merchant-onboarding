"""Full review/submit flow through the real handlers, against moto.
Builds a complete application through every prior-phase endpoint, then
exercises submit's blocking rules, idempotency, and payload contents.
"""

from __future__ import annotations

import json

import boto3

from handlers import (
    classify_mcc,
    complete_document,
    confirm_mcc,
    create_application,
    evaluate,
    get_review,
    patch_applicant,
    patch_business,
    presign_document,
    submit,
)
from tests.conftest import BUCKET_NAME, FakeLambdaContext

CONTEXT = FakeLambdaContext()
PDF_CONTENT = b"%PDF-1.4\n" + b"x" * 5000


def _event(
    *, path_id: str, token: str, body: dict | None = None, document_id: str | None = None
) -> dict:
    event: dict = {"pathParameters": {"id": path_id}, "headers": {"x-application-token": token}}
    if document_id is not None:
        event["pathParameters"]["documentId"] = document_id
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def _create_application() -> str:
    return _body(create_application.handler({"headers": {}}, CONTEXT))["applicationId"]


def _add_applicant(app_id: str) -> None:
    patch_applicant.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "p1",
                "firstName": "Ada",
                "lastName": "Lovelace",
                "dob": "1990-01-01",
                "address": {"line1": "1 Main St"},
                "role": "controller",
                "ownershipPct": 100,
                "idType": "passport",
                "idLast4": "1234",
                "consentVersion": "v1",
            },
        ),
        CONTEXT,
    )


def _add_business(app_id: str) -> None:
    patch_business.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "b1",
                "legalName": "Ada's Bakery LLC",
                "entityType": "LLC",
                "registrationId": "EIN-123",
                "addresses": {"business": {"line1": "1 Main St"}},
                "volumeMetrics": {"monthlyVolume": 50000, "currentProcessingRate": 0.025},
            },
        ),
        CONTEXT,
    )


def _upload_and_accept_document(app_id: str, doc_type: str, request_id: str) -> str:
    presigned = _body(
        presign_document.handler(
            _event(
                path_id=app_id,
                token=app_id,
                body={
                    "requestId": f"presign-{request_id}",
                    "docType": doc_type,
                    "fileName": "doc.pdf",
                    "mimeType": "application/pdf",
                    "sizeBytes": len(PDF_CONTENT),
                },
            ),
            CONTEXT,
        )
    )
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=BUCKET_NAME, Key=presigned["s3Key"], Body=PDF_CONTENT
    )
    complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": f"complete-{request_id}"},
        ),
        CONTEXT,
    )
    return presigned["documentId"]


def _confirm_mcc(app_id: str, code: str) -> None:
    classify_mcc.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={"requestId": "c1", "selfSelectedActivity": "Restaurant"},
        ),
        CONTEXT,
    )
    confirm_mcc.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "cf1", "code": code}), CONTEXT
    )


def _evaluate(app_id: str) -> None:
    evaluate.handler(_event(path_id=app_id, token=app_id, body={"requestId": "e1"}), CONTEXT)


def _build_complete_application(documents_bucket, *, mcc_code: str = "5812") -> str:
    app_id = _create_application()
    _add_applicant(app_id)
    _add_business(app_id)
    _upload_and_accept_document(app_id, "GOVERNMENT_ID", "gov")
    _upload_and_accept_document(app_id, "BUSINESS_REGISTRATION", "reg")
    _upload_and_accept_document(app_id, "BANK_EVIDENCE", "bank")
    _confirm_mcc(app_id, mcc_code)
    _evaluate(app_id)
    return app_id


def test_complete_application_submits_successfully(documents_bucket):
    app_id = _build_complete_application(documents_bucket)
    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["status"] == "SUBMITTED"
    assert body["reviewPayload"]["ready"] is True
    assert body["reviewPayload"]["blockingIssues"] == []


def test_submit_blocked_when_applicant_missing(documents_bucket):
    app_id = _create_application()
    _add_business(app_id)
    _upload_and_accept_document(app_id, "GOVERNMENT_ID", "gov")
    _upload_and_accept_document(app_id, "BUSINESS_REGISTRATION", "reg")
    _upload_and_accept_document(app_id, "BANK_EVIDENCE", "bank")
    _confirm_mcc(app_id, "5812")
    _evaluate(app_id)

    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    assert response["statusCode"] == 400
    body = _body(response)
    assert body["status"] == "DRAFT"
    assert any(i["code"] == "APPLICANT_MISSING" for i in body["missingItems"])


def test_submit_blocked_when_business_missing(documents_bucket):
    app_id = _create_application()
    _add_applicant(app_id)
    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    assert response["statusCode"] == 400
    body = _body(response)
    assert any(i["code"] == "BUSINESS_MISSING" for i in body["missingItems"])


def test_submit_blocked_when_required_documents_missing(documents_bucket):
    app_id = _create_application()
    _add_applicant(app_id)
    _add_business(app_id)
    _confirm_mcc(app_id, "5812")
    _evaluate(app_id)

    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    body = _body(response)
    assert response["statusCode"] == 400
    missing_fields = {i["field"] for i in body["missingItems"]}
    assert "documents.GOVERNMENT_ID" in missing_fields
    assert "documents.BUSINESS_REGISTRATION" in missing_fields
    assert "documents.BANK_EVIDENCE" in missing_fields


def test_submit_blocked_when_mcc_not_confirmed(documents_bucket):
    app_id = _create_application()
    _add_applicant(app_id)
    _add_business(app_id)
    _upload_and_accept_document(app_id, "GOVERNMENT_ID", "gov")
    _upload_and_accept_document(app_id, "BUSINESS_REGISTRATION", "reg")
    _upload_and_accept_document(app_id, "BANK_EVIDENCE", "bank")

    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    body = _body(response)
    assert response["statusCode"] == 400
    assert any(i["code"] == "MCC_NOT_CONFIRMED" for i in body["missingItems"])


def test_submit_blocked_when_evaluation_missing(documents_bucket):
    app_id = _create_application()
    _add_applicant(app_id)
    _add_business(app_id)
    _upload_and_accept_document(app_id, "GOVERNMENT_ID", "gov")
    _upload_and_accept_document(app_id, "BUSINESS_REGISTRATION", "reg")
    _upload_and_accept_document(app_id, "BANK_EVIDENCE", "bank")
    _confirm_mcc(app_id, "5812")

    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    body = _body(response)
    assert response["statusCode"] == 400
    assert any(i["code"] == "EVALUATION_INCOMPLETE" for i in body["missingItems"])


def test_submit_blocked_when_conditional_license_missing_for_enhanced_review_mcc(documents_bucket):
    app_id = _create_application()
    _add_applicant(app_id)
    _add_business(app_id)
    _upload_and_accept_document(app_id, "GOVERNMENT_ID", "gov")
    _upload_and_accept_document(app_id, "BUSINESS_REGISTRATION", "reg")
    _upload_and_accept_document(app_id, "BANK_EVIDENCE", "bank")
    _confirm_mcc(app_id, "6211")  # ENHANCED_REVIEW -> license required
    _evaluate(app_id)

    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    body = _body(response)
    assert response["statusCode"] == 400
    assert "documents.BUSINESS_LICENSE" in {i["field"] for i in body["missingItems"]}


def test_submit_succeeds_once_conditional_license_is_provided(documents_bucket):
    app_id = _create_application()
    _add_applicant(app_id)
    _add_business(app_id)
    _upload_and_accept_document(app_id, "GOVERNMENT_ID", "gov")
    _upload_and_accept_document(app_id, "BUSINESS_REGISTRATION", "reg")
    _upload_and_accept_document(app_id, "BANK_EVIDENCE", "bank")
    _upload_and_accept_document(app_id, "BUSINESS_LICENSE", "lic")
    _confirm_mcc(app_id, "6211")
    _evaluate(app_id)

    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT
    )
    assert response["statusCode"] == 200
    assert _body(response)["reviewPayload"]["requiresManualReview"] is True


def test_submit_requires_matching_token(documents_bucket):
    app_id = _build_complete_application(documents_bucket)
    response = submit.handler(
        _event(path_id=app_id, token="wrong", body={"requestId": "s1"}), CONTEXT
    )
    assert response["statusCode"] == 401


def test_submit_returns_404_for_unknown_application(documents_bucket):
    response = submit.handler(
        _event(path_id="ghost", token="ghost", body={"requestId": "s1"}), CONTEXT
    )
    assert response["statusCode"] == 404


def test_submit_is_idempotent_on_repeated_call(documents_bucket):
    app_id = _build_complete_application(documents_bucket)
    first = _body(
        submit.handler(_event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT)
    )
    second = _body(
        submit.handler(_event(path_id=app_id, token=app_id, body={"requestId": "s2"}), CONTEXT)
    )
    assert first == second


def test_already_submitted_application_does_not_re_validate_or_error(documents_bucket):
    app_id = _build_complete_application(documents_bucket)
    submit.handler(_event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT)

    response = submit.handler(
        _event(path_id=app_id, token=app_id, body={"requestId": "s2"}), CONTEXT
    )
    assert response["statusCode"] == 200
    assert _body(response)["status"] == "SUBMITTED"


def test_review_endpoint_reflects_readiness_before_submission(documents_bucket):
    app_id = _build_complete_application(documents_bucket)
    response = get_review.handler(_event(path_id=app_id, token=app_id), CONTEXT)
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["ready"] is True
    assert body["applicationStatus"] == "DRAFT"
    assert body["business"]["legalName"] == "Ada's Bakery LLC"
    assert body["mcc"]["confirmed"]["code"] == "5812"
    assert body["evaluation"]["status"] == "COMPLETE"


def test_review_endpoint_requires_matching_token(documents_bucket):
    app_id = _create_application()
    response = get_review.handler(_event(path_id=app_id, token="wrong"), CONTEXT)
    assert response["statusCode"] == 401


def test_review_and_submit_payloads_never_expose_s3_key_or_checksum(documents_bucket):
    app_id = _build_complete_application(documents_bucket)
    review_body = _body(get_review.handler(_event(path_id=app_id, token=app_id), CONTEXT))
    submit_body = _body(
        submit.handler(_event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT)
    )

    for payload in (review_body, submit_body["reviewPayload"]):
        raw = json.dumps(payload)
        assert "s3Key" not in raw
        assert "checksumSha256" not in raw
        for doc in payload["documents"]:
            assert set(doc.keys()) == {"documentId", "docType", "status", "fileName", "verifiedAt"}


def test_normalized_payload_is_persisted_with_document_metadata_not_content(documents_bucket):
    app_id = _build_complete_application(documents_bucket)
    submit.handler(_event(path_id=app_id, token=app_id, body={"requestId": "s1"}), CONTEXT)

    from adapters.db import dynamo_client

    item = dynamo_client.get_item(f"APP#{app_id}", "SUBMISSION")
    assert item is not None
    normalized = item["normalizedPayload"]
    assert normalized["individuals"][0]["firstName"] == "Ada"
    assert len(normalized["documents"]) == 3
    for doc in normalized["documents"]:
        assert "s3Key" in doc  # metadata reference is fine — this item is never returned via API
        assert "checksumSha256" in doc
        assert doc["status"] == "ACCEPTED"
