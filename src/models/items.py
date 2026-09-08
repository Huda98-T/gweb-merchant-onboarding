"""Pydantic models for the DynamoDB item shapes used by Phase 1.

Mirrors GWEB_Implementation_Spec.md §2.2. Every item shares the single-table
`PK`/`SK` envelope; `EVAL#`, `DOC#`, `MCC#`, `POLICY#` item types are not
modeled yet — they belong to later phases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class ApplicationMetaItem(BaseModel):
    """`PK = APP#<appId>`, `SK = META`."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(default="META", alias="SK")
    status: ApplicationStatus = ApplicationStatus.DRAFT
    version: int = 1
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")
    applicant_complete: bool = Field(default=False, alias="applicantComplete")
    business_complete: bool = Field(default=False, alias="businessComplete")
    # Idempotency cache (§2.4): last accepted requestId for a mutating write
    # on this application, and the response body that was returned for it.
    last_request_id: str | None = Field(default=None, alias="lastRequestId")
    last_response: dict[str, Any] | None = Field(default=None, alias="lastResponse")


class PersonItem(BaseModel):
    """`PK = APP#<appId>`, `SK = PERSON#<personId>`."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(alias="SK")
    person_id: str = Field(alias="personId")
    role: str
    ownership_pct: float | None = Field(default=None, alias="ownershipPct")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    dob: str
    address: dict[str, Any]
    id_type: str = Field(alias="idType")
    id_last4: str = Field(alias="idLast4")
    consent_timestamp: str | None = Field(default=None, alias="consentTimestamp")
    consent_version: str | None = Field(default=None, alias="consentVersion")


class BusinessItem(BaseModel):
    """`PK = APP#<appId>`, `SK = BUSINESS`."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(default="BUSINESS", alias="SK")
    legal_name: str = Field(alias="legalName")
    dba: str | None = None
    entity_type: str = Field(alias="entityType")
    registration_id: str = Field(alias="registrationId")
    addresses: dict[str, Any]
    volume_metrics: dict[str, Any] = Field(alias="volumeMetrics")
    existing_processor: dict[str, Any] | None = Field(default=None, alias="existingProcessor")
