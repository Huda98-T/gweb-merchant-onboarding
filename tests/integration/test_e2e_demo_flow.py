"""The single, narrative end-to-end test for the whole system (Phase 6):
create -> applicant/business -> document presign -> direct-upload
completion -> classify -> confirm MCC -> evaluate -> review -> submit.

This intentionally overlaps with the more granular Phase 1-5 test suites
(which remain the authoritative per-feature coverage) — this file exists
purely so a reviewer can read one function top-to-bottom and see the
entire merchant-onboarding journey exercised against the real handlers,
same as the demo UI does against the local demo server.
"""

from __future__ import annotations

import hashlib
import json

import boto3

from handlers import (
    classify_mcc,
    complete_document,
    confirm_mcc,
    create_application,
    evaluate,
    get_application,
    get_review,
    patch_applicant,
    patch_business,
    presign_document,
    submit,
)
from tests.conftest import BUCKET_NAME, FakeLambdaContext

CONTEXT = FakeLambdaContext()
STATEMENT_PDF = b"%PDF-1.4\n" + b"statement-bytes" * 200


def _event(*, app_id: str, token: str, doc_id: str | None = None, body: dict | None = None) -> dict:
    event: dict = {"pathParameters": {"id": app_id}, "headers": {"x-application-token": token}}
    if doc_id is not None:
        event["pathParameters"]["documentId"] = doc_id
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def test_full_merchant_onboarding_journey_happy_path(documents_bucket):
    # 1. Create the application — the returned ID doubles as the bearer token.
    create_response = create_application.handler({"headers": {}}, CONTEXT)
    assert create_response["statusCode"] == 201
    app_id = _body(create_response)["applicationId"]
    token = app_id

    # 2. Applicant / controller information.
    applicant_response = patch_applicant.handler(
        _event(
            app_id=app_id,
            token=token,
            body={
                "requestId": "req-applicant",
                "firstName": "Ada",
                "lastName": "Lovelace",
                "dob": "1990-01-01",
                "address": {"line1": "1 Main St", "city": "London"},
                "role": "controller",
                "ownershipPct": 100,
                "idType": "passport",
                "idLast4": "1234",
                "consentVersion": "v1",
            },
        ),
        CONTEXT,
    )
    assert applicant_response["statusCode"] == 200

    # 3. Business information, including the volume/rate data the
    #    deterministic rate calculation reads later.
    business_response = patch_business.handler(
        _event(
            app_id=app_id,
            token=token,
            body={
                "requestId": "req-business",
                "legalName": "Ada's Bakery LLC",
                "entityType": "LLC",
                "registrationId": "EIN-123456",
                "addresses": {"business": {"line1": "1 Main St"}},
                "volumeMetrics": {
                    "monthlyVolume": 50000,
                    "currentProcessingRate": 0.029,
                    "transactionCount": 500,
                    "perTransactionFee": 0.10,
                },
            },
        ),
        CONTEXT,
    )
    assert business_response["statusCode"] == 200

    # 4. Documents: presign -> real direct-to-S3 PUT (no Lambda in the
    #    middle) -> complete/verify, for each required type.
    document_ids = {}
    for doc_type in ("GOVERNMENT_ID", "BUSINESS_REGISTRATION", "BANK_EVIDENCE"):
        presigned = _body(
            presign_document.handler(
                _event(
                    app_id=app_id,
                    token=token,
                    body={
                        "requestId": f"req-presign-{doc_type}",
                        "docType": doc_type,
                        "fileName": "statement.pdf",
                        "mimeType": "application/pdf",
                        "sizeBytes": len(STATEMENT_PDF),
                    },
                ),
                CONTEXT,
            )
        )
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=BUCKET_NAME, Key=presigned["s3Key"], Body=STATEMENT_PDF
        )
        complete_response = complete_document.handler(
            _event(
                app_id=app_id,
                token=token,
                doc_id=presigned["documentId"],
                body={"requestId": f"req-complete-{doc_type}"},
            ),
            CONTEXT,
        )
        assert complete_response["statusCode"] == 200
        complete_body = _body(complete_response)
        assert complete_body["status"] == "ACCEPTED"
        assert complete_body["checksumSha256"] == hashlib.sha256(STATEMENT_PDF).hexdigest()
        document_ids[doc_type] = presigned["documentId"]

    # 5. Business activity -> deterministic MCC classification.
    classify_response = classify_mcc.handler(
        _event(
            app_id=app_id,
            token=token,
            body={
                "requestId": "req-classify",
                "selfSelectedActivity": "Restaurant",
                "businessDescription": "Neighborhood bakery and cafe",
            },
        ),
        CONTEXT,
    )
    assert classify_response["statusCode"] == 200
    top_candidate = _body(classify_response)["candidates"][0]
    assert top_candidate["code"] == "5812"  # Eating places and Restaurants

    # 6. Applicant confirms the proposed MCC.
    confirm_response = confirm_mcc.handler(
        _event(
            app_id=app_id,
            token=token,
            body={"requestId": "req-confirm", "code": top_candidate["code"]},
        ),
        CONTEXT,
    )
    assert confirm_response["statusCode"] == 200
    assert _body(confirm_response)["riskTier"] == "STANDARD"

    # 7. Evaluation: deterministic rate/fee math + mock AI commentary.
    evaluate_response = evaluate.handler(
        _event(app_id=app_id, token=token, body={"requestId": "req-evaluate"}), CONTEXT
    )
    assert evaluate_response["statusCode"] == 200
    evaluate_body = _body(evaluate_response)
    assert evaluate_body["status"] == "COMPLETE"
    assert evaluate_body["effectiveRate"] == 0.03
    assert evaluate_body["aiCommentary"]["summary"]

    # 8. Review — the applicant-facing readiness view is fully green.
    review_response = get_review.handler(_event(app_id=app_id, token=token), CONTEXT)
    assert review_response["statusCode"] == 200
    review_body = _body(review_response)
    assert review_body["ready"] is True
    assert review_body["blockingIssues"] == []
    assert review_body["mcc"]["confirmed"]["code"] == "5812"

    # 9. Submit — transitions DRAFT -> SUBMITTED and persists the
    #    normalized downstream payload atomically.
    submit_response = submit.handler(
        _event(app_id=app_id, token=token, body={"requestId": "req-submit"}), CONTEXT
    )
    assert submit_response["statusCode"] == 200
    submit_body = _body(submit_response)
    assert submit_body["status"] == "SUBMITTED"

    # 10. The full aggregate view now reflects the submitted state.
    final_state = _body(get_application.handler(_event(app_id=app_id, token=token), CONTEXT))
    assert final_state["meta"]["status"] == "SUBMITTED"
    assert final_state["evaluation"]["status"] == "COMPLETE"
    assert final_state["mcc"]["confirmed"]["code"] == "5812"


def test_critical_blocking_path_missing_documents_and_mcc_blocks_submission(documents_bucket):
    """The critical negative path: an application with applicant/business
    info but no documents and no confirmed MCC must not be submittable."""
    app_id = _body(create_application.handler({"headers": {}}, CONTEXT))["applicationId"]
    token = app_id

    patch_applicant.handler(
        _event(
            app_id=app_id,
            token=token,
            body={
                "requestId": "req-applicant",
                "firstName": "Grace",
                "lastName": "Hopper",
                "dob": "1985-05-05",
                "address": {"line1": "2 Main St"},
                "role": "controller",
                "ownershipPct": 100,
                "idType": "passport",
                "idLast4": "5678",
            },
        ),
        CONTEXT,
    )
    patch_business.handler(
        _event(
            app_id=app_id,
            token=token,
            body={
                "requestId": "req-business",
                "legalName": "Grace's Consulting LLC",
                "entityType": "LLC",
                "registrationId": "EIN-999",
                "addresses": {"business": {"line1": "2 Main St"}},
                "volumeMetrics": {"monthlyVolume": 1000, "currentProcessingRate": 0.02},
            },
        ),
        CONTEXT,
    )
    # No documents, no MCC classification, no evaluation.

    submit_response = submit.handler(
        _event(app_id=app_id, token=token, body={"requestId": "req-submit"}), CONTEXT
    )
    assert submit_response["statusCode"] == 400
    body = _body(submit_response)
    assert body["status"] == "DRAFT"
    codes = {issue["code"] for issue in body["missingItems"]}
    assert "DOCUMENT_MISSING" in codes
    assert "MCC_NOT_CONFIRMED" in codes
    assert "EVALUATION_INCOMPLETE" in codes

    # Confirm the application truly was not persisted as SUBMITTED.
    state = _body(get_application.handler(_event(app_id=app_id, token=token), CONTEXT))
    assert state["meta"]["status"] == "DRAFT"
