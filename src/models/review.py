"""Review/readiness and submission models (spec §3 submit, extended with a
justified GET /review endpoint — same pattern as Phase 3's mcc/confirm:
the assessment requires the applicant be able to review before
submitting, not just discover blocking issues via a failed POST).

Validation is 100% deterministic (spec requirement: submission must not
depend on AI) — see submit_service.py. The client-facing review/submit
payload never includes s3Key, checksums, or raw document content; the
separately *persisted* NormalizedSubmissionPayload (submit_service.py) is
richer (document metadata for downstream processor use) but is never
returned over the API.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from models.api import BusinessView, PersonView
from models.documents import DocumentStatus, DocumentType
from models.evaluation import GetEvaluationResponse
from models.items import ApplicationStatus
from models.mcc import MccView, RiskTier


class ValidationIssue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    message: str
    field: str


class DocumentSummaryView(BaseModel):
    """No s3Key, no checksum — internal storage details stay internal."""

    model_config = ConfigDict(populate_by_name=True)

    document_id: str = Field(alias="documentId")
    doc_type: DocumentType = Field(alias="docType")
    status: DocumentStatus
    file_name: str = Field(alias="fileName")
    verified_at: str | None = Field(default=None, alias="verifiedAt")


class BusinessActivityView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    self_selected_activity: str = Field(alias="selfSelectedActivity")
    business_description: str | None = Field(default=None, alias="businessDescription")


class ReviewResponse(BaseModel):
    """`GET /applications/{id}/review` — and the shape of `submit`'s
    `reviewPayload` on success. Client-facing: no secrets, no document
    contents, no S3 references."""

    model_config = ConfigDict(populate_by_name=True)

    application_status: ApplicationStatus = Field(alias="applicationStatus")
    applicant: list[PersonView] = Field(default_factory=list)
    business: BusinessView | None = None
    documents: list[DocumentSummaryView] = Field(default_factory=list)
    missing_document_types: list[DocumentType] = Field(
        default_factory=list, alias="missingDocumentTypes"
    )
    business_activity: BusinessActivityView | None = Field(default=None, alias="businessActivity")
    mcc: MccView = Field(default_factory=MccView)
    risk_tier: RiskTier = Field(default=RiskTier.STANDARD, alias="riskTier")
    requires_manual_review: bool = Field(default=False, alias="requiresManualReview")
    evaluation: GetEvaluationResponse | None = None
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[ValidationIssue] = Field(default_factory=list, alias="blockingIssues")
    ready: bool = False


class NormalizedDocumentRef(BaseModel):
    """Downstream-processor document reference — metadata only, per
    'do not include raw document bytes' (s3Key is a storage *reference*,
    not content; this model is persisted, never returned over the API)."""

    model_config = ConfigDict(populate_by_name=True)

    document_id: str = Field(alias="documentId")
    doc_type: DocumentType = Field(alias="docType")
    status: DocumentStatus
    s3_key: str = Field(alias="s3Key")
    checksum_sha256: str | None = Field(default=None, alias="checksumSha256")
    verified_at: str | None = Field(default=None, alias="verifiedAt")


class ConsentRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str = Field(alias="personId")
    consent_version: str | None = Field(default=None, alias="consentVersion")
    consent_timestamp: str | None = Field(default=None, alias="consentTimestamp")


class NormalizedSubmissionPayload(BaseModel):
    """Persisted on successful submit for downstream processor/provider
    integration — never returned by any API response in this phase.

    `individuals` covers both the "applicant" and "ownership/controllers"
    sections the assessment lists separately: Phase 1's PersonItem.role is
    a free-text field, not a fixed taxonomy, so this repo has no reliable
    way to split "the applicant" from "the beneficial owners" beyond what
    `role` already says per person — inventing that split here would mean
    guessing at business rules the spec never defined. Each entry's `role`
    is what a downstream consumer would filter on.
    """

    model_config = ConfigDict(populate_by_name=True)

    individuals: list[PersonView] = Field(default_factory=list)
    business: BusinessView | None = None
    documents: list[NormalizedDocumentRef] = Field(default_factory=list)
    classification: MccView = Field(default_factory=MccView)
    risk_tier: RiskTier = Field(default=RiskTier.STANDARD, alias="riskTier")
    evaluation: GetEvaluationResponse | None = None
    consent: list[ConsentRecord] = Field(default_factory=list)
    submitted_at: str = Field(alias="submittedAt")
    request_id: str = Field(alias="requestId")


class SubmitRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId", min_length=1)


class SubmissionItem(BaseModel):
    """`PK = APP#<appId>`, `SK = SUBMISSION` — written once, atomically
    with META's DRAFT->SUBMITTED transition (put_item_with_meta_version_bump).
    Caches the client-facing review payload (for idempotent re-serving on
    a repeat submit) and holds the full normalized_payload for downstream
    processor consumption."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(default="SUBMISSION", alias="SK")
    submitted_at: str = Field(alias="submittedAt")
    request_id: str = Field(alias="requestId")
    review_payload: ReviewResponse = Field(alias="reviewPayload")
    normalized_payload: NormalizedSubmissionPayload = Field(alias="normalizedPayload")


class SubmitResponse(BaseModel):
    """`POST /applications/{id}/submit` — spec §3: `200 { status:
    "SUBMITTED", reviewPayload }` or `400 { missingItems: [...] }`."""

    model_config = ConfigDict(populate_by_name=True)

    status: ApplicationStatus
    review_payload: ReviewResponse | None = Field(default=None, alias="reviewPayload")
    missing_items: list[ValidationIssue] = Field(default_factory=list, alias="missingItems")
