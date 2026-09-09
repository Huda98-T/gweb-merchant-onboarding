"""Submission: validates via review_service (deterministic, no AI), and on
success atomically writes the SUBMISSION item + bumps META to SUBMITTED
using the same conditional-transaction helper Phase 1's applicant/business
patches use — concurrency-safe for free, no new adapter code needed.

Idempotency is resource-level, not just requestId-cache: once SUBMITTED,
a repeat call (any requestId) returns the already-persisted result rather
than re-validating or re-writing — submission is a one-way state
transition, so "submit again" should be a safe no-op, not an error.
"""

from __future__ import annotations

from datetime import UTC, datetime

from adapters.db import dynamo_client
from common.decimal_utils import from_decimal, to_decimal
from models.items import ApplicationStatus
from models.review import (
    ConsentRecord,
    NormalizedDocumentRef,
    NormalizedSubmissionPayload,
    ReviewResponse,
    SubmissionItem,
    SubmitRequest,
    SubmitResponse,
)
from services import review_service


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_normalized_payload(
    application_id: str, review: ReviewResponse, request_id: str, submitted_at: str
) -> NormalizedSubmissionPayload:
    pk = review_service.application_pk(application_id)
    items = [from_decimal(i) for i in dynamo_client.query_by_pk(pk)]
    doc_items = [i for i in items if i["SK"].startswith("DOC#")]

    documents = [
        NormalizedDocumentRef(
            document_id=d["documentId"],
            doc_type=d["docType"],
            status=d["status"],
            s3_key=d["s3Key"],
            checksum_sha256=d.get("checksumSha256"),
            verified_at=d.get("verifiedAt"),
        )
        for d in doc_items
    ]
    consent = [
        ConsentRecord(
            person_id=p.person_id,
            consent_version=p.consent_version,
            consent_timestamp=p.consent_timestamp,
        )
        for p in review.applicant
    ]

    return NormalizedSubmissionPayload(
        individuals=review.applicant,
        business=review.business,
        documents=documents,
        classification=review.mcc,
        risk_tier=review.risk_tier,
        evaluation=review.evaluation,
        consent=consent,
        submitted_at=submitted_at,
        request_id=request_id,
    )


def submit_application(application_id: str, request: SubmitRequest) -> SubmitResponse:
    pk = review_service.application_pk(application_id)
    meta_item = from_decimal(
        dynamo_client.get_item_or_404(pk, "META", not_found_message="Application not found")
    )

    if meta_item["status"] == ApplicationStatus.SUBMITTED.value:
        submission_item = dynamo_client.get_item(pk, "SUBMISSION")
        cached_review = (
            ReviewResponse.model_validate(from_decimal(submission_item)["reviewPayload"])
            if submission_item
            else review_service.build_review(application_id)
        )
        return SubmitResponse(status=ApplicationStatus.SUBMITTED, review_payload=cached_review)

    review = review_service.build_review(application_id)
    if not review.ready:
        return SubmitResponse(status=ApplicationStatus.DRAFT, missing_items=review.blocking_issues)

    submitted_at = _utc_now_iso()
    normalized = _build_normalized_payload(application_id, review, request.request_id, submitted_at)
    submission = SubmissionItem(
        pk=pk,
        submitted_at=submitted_at,
        request_id=request.request_id,
        review_payload=review,
        normalized_payload=normalized,
    )

    dynamo_client.put_item_with_meta_version_bump(
        item=to_decimal(submission.model_dump(by_alias=True, exclude_none=True)),
        meta_pk=pk,
        expected_version=meta_item["version"],
        meta_updates={
            "status": ApplicationStatus.SUBMITTED.value,
            "updatedAt": submitted_at,
            "lastRequestId": request.request_id,
        },
    )
    return SubmitResponse(status=ApplicationStatus.SUBMITTED, review_payload=review)
