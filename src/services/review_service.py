"""Builds the read-only review/readiness view — shared by GET /review and
submit_service.py's validation gate (same computation, so "what /review
shows you" and "what /submit checks" can never drift apart).

100% deterministic — no AI involved in readiness/blocking decisions
(spec requirement). Client-facing only: no s3Key, no checksums, no
document bytes.
"""

from __future__ import annotations

from adapters.db import dynamo_client
from common.decimal_utils import from_decimal
from common.errors import NotFoundError
from models.api import ApplicationMetaView, BusinessView, PersonView
from models.documents import DocumentStatus, DocumentType
from models.evaluation import EvaluationStatus, GetEvaluationResponse
from models.mcc import MccConfirmedView, MccProposedView, MccView, RiskTier
from models.review import BusinessActivityView, DocumentSummaryView, ReviewResponse, ValidationIssue

ALWAYS_REQUIRED_DOC_TYPES = (
    DocumentType.GOVERNMENT_ID,
    DocumentType.BUSINESS_REGISTRATION,
    DocumentType.BANK_EVIDENCE,
)


def application_pk(application_id: str) -> str:
    return f"APP#{application_id}"


def _license_required(mcc_confirmed: MccConfirmedView | None) -> bool:
    """Conditional requirement: a business license is required once the
    confirmed MCC is under any elevated policy tier (STANDARD doesn't
    need one on file for this prototype)."""
    return mcc_confirmed is not None and mcc_confirmed.risk_tier != RiskTier.STANDARD


def build_review(application_id: str) -> ReviewResponse:
    pk = application_pk(application_id)
    raw_items = dynamo_client.query_by_pk(pk)
    items = [from_decimal(item) for item in raw_items]
    meta_item = next((i for i in items if i["SK"] == "META"), None)
    if meta_item is None:
        raise NotFoundError("Application not found")

    meta = ApplicationMetaView.model_validate(meta_item)
    person_items = [i for i in items if i["SK"].startswith("PERSON#")]
    applicant = [PersonView.model_validate(p) for p in person_items]

    business_item = next((i for i in items if i["SK"] == "BUSINESS"), None)
    business = BusinessView.model_validate(business_item) if business_item else None

    doc_items = [i for i in items if i["SK"].startswith("DOC#")]
    documents = [DocumentSummaryView.model_validate(d) for d in doc_items]
    accepted_types = {d.doc_type for d in documents if d.status == DocumentStatus.ACCEPTED}

    mcc_proposed_item = next((i for i in items if i["SK"] == "MCC#PROPOSED"), None)
    mcc_proposed = MccProposedView.model_validate(mcc_proposed_item) if mcc_proposed_item else None
    mcc_confirmed_item = next((i for i in items if i["SK"] == "MCC#CONFIRMED"), None)
    mcc_confirmed = (
        MccConfirmedView.model_validate(mcc_confirmed_item) if mcc_confirmed_item else None
    )

    business_activity = (
        BusinessActivityView(
            self_selected_activity=mcc_proposed.self_selected_activity,
            business_description=mcc_proposed.business_description,
        )
        if mcc_proposed
        else None
    )

    eval_item = next((i for i in items if i["SK"] == "EVAL#LATEST"), None)
    evaluation = GetEvaluationResponse.model_validate(eval_item) if eval_item else None

    required_doc_types = list(ALWAYS_REQUIRED_DOC_TYPES)
    if _license_required(mcc_confirmed):
        required_doc_types.append(DocumentType.BUSINESS_LICENSE)
    missing_document_types = [t for t in required_doc_types if t not in accepted_types]

    risk_tier = mcc_confirmed.risk_tier if mcc_confirmed else RiskTier.STANDARD
    high_risk_flags = [
        f for f in (evaluation.risk_flags if evaluation else []) if f.severity.value == "HIGH"
    ]
    requires_manual_review = risk_tier != RiskTier.STANDARD or bool(high_risk_flags)

    blocking_issues: list[ValidationIssue] = []
    if not applicant:
        blocking_issues.append(
            ValidationIssue(
                code="APPLICANT_MISSING",
                message="No applicant/owner information on file.",
                field="applicant",
            )
        )
    if business is None:
        blocking_issues.append(
            ValidationIssue(
                code="BUSINESS_MISSING", message="Business profile is incomplete.", field="business"
            )
        )
    for doc_type in missing_document_types:
        blocking_issues.append(
            ValidationIssue(
                code="DOCUMENT_MISSING",
                message=f"Required document not accepted: {doc_type.value}.",
                field=f"documents.{doc_type.value}",
            )
        )
    if mcc_confirmed is None:
        blocking_issues.append(
            ValidationIssue(
                code="MCC_NOT_CONFIRMED",
                message="MCC classification has not been confirmed.",
                field="mcc.confirmed",
            )
        )
    if evaluation is None or evaluation.status != EvaluationStatus.COMPLETE:
        blocking_issues.append(
            ValidationIssue(
                code="EVALUATION_INCOMPLETE",
                message="A completed evaluation is required before submission.",
                field="evaluation",
            )
        )

    warnings: list[str] = []
    if requires_manual_review:
        warnings.append("This application is flagged for enhanced manual review.")

    return ReviewResponse(
        application_status=meta.status,
        applicant=applicant,
        business=business,
        documents=documents,
        missing_document_types=missing_document_types,
        business_activity=business_activity,
        mcc=MccView(proposed=mcc_proposed, confirmed=mcc_confirmed),
        risk_tier=risk_tier,
        requires_manual_review=requires_manual_review,
        evaluation=evaluation,
        warnings=warnings,
        blocking_issues=blocking_issues,
        ready=not blocking_issues,
    )
