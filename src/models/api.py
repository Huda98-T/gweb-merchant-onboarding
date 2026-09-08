"""Request/response models for the Phase 1 routes (see spec §3).

Field names use the API's camelCase directly via aliases so the models
double as the OpenAPI-shaped contract, while handler code can use normal
snake_case attribute access.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from models.items import ApplicationStatus


class CreateApplicationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    application_id: str = Field(alias="applicationId")
    status: ApplicationStatus
    version: int


class PatchApplicantRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId")
    person_id: str | None = Field(default=None, alias="personId")
    first_name: str = Field(alias="firstName", min_length=1)
    last_name: str = Field(alias="lastName", min_length=1)
    dob: str
    address: dict[str, Any]
    role: str = Field(min_length=1)
    ownership_pct: float | None = Field(default=None, alias="ownershipPct", ge=0, le=100)
    id_type: str = Field(alias="idType", min_length=1)
    id_last4: str = Field(alias="idLast4", min_length=4, max_length=4)
    consent_version: str | None = Field(default=None, alias="consentVersion")


class PatchApplicantResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    person_id: str = Field(alias="personId")
    version: int


class PatchBusinessRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId")
    legal_name: str = Field(alias="legalName", min_length=1)
    dba: str | None = None
    entity_type: str = Field(alias="entityType", min_length=1)
    registration_id: str = Field(alias="registrationId", min_length=1)
    addresses: dict[str, Any]
    volume_metrics: dict[str, Any] = Field(alias="volumeMetrics")
    existing_processor: dict[str, Any] | None = Field(default=None, alias="existingProcessor")


class PatchBusinessResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int


class ApplicationMetaView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: ApplicationStatus
    version: int
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    applicant_complete: bool = Field(alias="applicantComplete")
    business_complete: bool = Field(alias="businessComplete")


class PersonView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

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


class BusinessView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    legal_name: str = Field(alias="legalName")
    dba: str | None = None
    entity_type: str = Field(alias="entityType")
    registration_id: str = Field(alias="registrationId")
    addresses: dict[str, Any]
    volume_metrics: dict[str, Any] = Field(alias="volumeMetrics")
    existing_processor: dict[str, Any] | None = Field(default=None, alias="existingProcessor")


class GetApplicationResponse(BaseModel):
    """Aggregated read across the whole partition — see spec §3 note on
    `GET /applications/{id}`. `documents`, `mcc`, and `evaluation` stay
    empty/null until the corresponding phases exist."""

    model_config = ConfigDict(populate_by_name=True)

    meta: ApplicationMetaView
    applicant: list[PersonView] = Field(default_factory=list)
    business: BusinessView | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    mcc: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
