"""Validation behavior of the Pydantic request/response models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.api import PatchApplicantRequest, PatchBusinessRequest
from models.items import ApplicationMetaItem, ApplicationStatus


def _valid_applicant_payload(**overrides) -> dict:
    payload = {
        "requestId": "req-1",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "dob": "1990-01-01",
        "address": {"line1": "1 Main St", "city": "London"},
        "role": "controller",
        "ownershipPct": 50,
        "idType": "passport",
        "idLast4": "1234",
        "consentVersion": "v1",
    }
    payload.update(overrides)
    return payload


def test_patch_applicant_request_accepts_valid_payload():
    request = PatchApplicantRequest.model_validate(_valid_applicant_payload())
    assert request.first_name == "Ada"
    assert request.id_last4 == "1234"


def test_patch_applicant_request_rejects_bad_id_last4_length():
    with pytest.raises(ValidationError):
        PatchApplicantRequest.model_validate(_valid_applicant_payload(idLast4="12"))


def test_patch_applicant_request_rejects_ownership_pct_over_100():
    with pytest.raises(ValidationError):
        PatchApplicantRequest.model_validate(_valid_applicant_payload(ownershipPct=150))


def test_patch_applicant_request_requires_request_id():
    payload = _valid_applicant_payload()
    del payload["requestId"]
    with pytest.raises(ValidationError):
        PatchApplicantRequest.model_validate(payload)


def test_patch_business_request_accepts_valid_payload():
    request = PatchBusinessRequest.model_validate(
        {
            "requestId": "req-1",
            "legalName": "Ada's Bakery LLC",
            "entityType": "LLC",
            "registrationId": "EIN-123",
            "addresses": {"business": {"line1": "1 Main St"}},
            "volumeMetrics": {"monthlyVolume": 10000},
        }
    )
    assert request.legal_name == "Ada's Bakery LLC"
    assert request.existing_processor is None


def test_application_meta_item_defaults():
    meta = ApplicationMetaItem(pk="APP#abc123")
    assert meta.sk == "META"
    assert meta.status == ApplicationStatus.DRAFT
    assert meta.version == 1
    assert meta.applicant_complete is False
    assert meta.business_complete is False


def test_application_meta_item_round_trips_by_alias():
    meta = ApplicationMetaItem(pk="APP#abc123")
    dumped = meta.model_dump(by_alias=True)
    assert dumped["PK"] == "APP#abc123"
    assert dumped["SK"] == "META"
    restored = ApplicationMetaItem.model_validate(dumped)
    assert restored == meta
