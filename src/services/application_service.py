"""Business logic for the Phase 1 application routes (spec §3).

Handlers stay thin; this is where request data is turned into item shapes,
optimistic concurrency + idempotency (spec §2.4) is applied, and the
aggregated read is assembled.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from adapters.db import dynamo_client
from common.decimal_utils import from_decimal, to_decimal
from common.errors import NotFoundError
from models.api import (
    ApplicationMetaView,
    BusinessView,
    CreateApplicationResponse,
    GetApplicationResponse,
    PatchApplicantRequest,
    PatchApplicantResponse,
    PatchBusinessRequest,
    PatchBusinessResponse,
    PersonView,
)
from models.items import ApplicationMetaItem, BusinessItem, PersonItem, utc_now_iso


def application_pk(application_id: str) -> str:
    return f"APP#{application_id}"


def create_application() -> CreateApplicationResponse:
    application_id = uuid.uuid4().hex
    meta = ApplicationMetaItem(pk=application_pk(application_id))
    dynamo_client.put_item_if_absent(meta.model_dump(by_alias=True, exclude_none=True))
    return CreateApplicationResponse(
        application_id=application_id, status=meta.status, version=meta.version
    )


def _get_meta_item(application_id: str) -> dict:
    item = dynamo_client.get_item_or_404(
        application_pk(application_id), "META", not_found_message="Application not found"
    )
    return from_decimal(item)


def _idempotent_replay[T: BaseModel](
    meta_item: dict, request_id: str, response_model: type[T]
) -> T | None:
    """Return the cached response for a previously-applied requestId, if any."""
    if meta_item.get("lastRequestId") == request_id and meta_item.get("lastResponse"):
        return response_model.model_validate(meta_item["lastResponse"])
    return None


def _meta_update_fields(request_id: str, response_model: BaseModel) -> dict:
    return {
        "updatedAt": utc_now_iso(),
        "lastRequestId": request_id,
        "lastResponse": to_decimal(response_model.model_dump(by_alias=True)),
    }


def get_application(application_id: str) -> GetApplicationResponse:
    raw_items = dynamo_client.query_by_pk(application_pk(application_id))
    items = [from_decimal(item) for item in raw_items]
    meta_item = next((i for i in items if i["SK"] == "META"), None)
    if meta_item is None:
        raise NotFoundError("Application not found")

    person_items = [i for i in items if i["SK"].startswith("PERSON#")]
    business_item = next((i for i in items if i["SK"] == "BUSINESS"), None)

    return GetApplicationResponse(
        meta=ApplicationMetaView.model_validate(meta_item),
        applicant=[PersonView.model_validate(p) for p in person_items],
        business=BusinessView.model_validate(business_item) if business_item else None,
    )


def patch_applicant(application_id: str, request: PatchApplicantRequest) -> PatchApplicantResponse:
    pk = application_pk(application_id)
    meta_item = _get_meta_item(application_id)

    cached = _idempotent_replay(meta_item, request.request_id, PatchApplicantResponse)
    if cached is not None:
        return cached

    person_id = request.person_id or uuid.uuid4().hex
    person = PersonItem(
        pk=pk,
        sk=f"PERSON#{person_id}",
        person_id=person_id,
        role=request.role,
        ownership_pct=request.ownership_pct,
        first_name=request.first_name,
        last_name=request.last_name,
        dob=request.dob,
        address=request.address,
        id_type=request.id_type,
        id_last4=request.id_last4,
        consent_timestamp=utc_now_iso() if request.consent_version else None,
        consent_version=request.consent_version,
    )
    item = to_decimal(person.model_dump(by_alias=True, exclude_none=True))

    response = PatchApplicantResponse(person_id=person_id, version=meta_item["version"] + 1)
    dynamo_client.put_item_with_meta_version_bump(
        item=item,
        meta_pk=pk,
        expected_version=meta_item["version"],
        meta_updates=_meta_update_fields(request.request_id, response),
    )
    return response


def patch_business(application_id: str, request: PatchBusinessRequest) -> PatchBusinessResponse:
    pk = application_pk(application_id)
    meta_item = _get_meta_item(application_id)

    cached = _idempotent_replay(meta_item, request.request_id, PatchBusinessResponse)
    if cached is not None:
        return cached

    business = BusinessItem(
        pk=pk,
        legal_name=request.legal_name,
        dba=request.dba,
        entity_type=request.entity_type,
        registration_id=request.registration_id,
        addresses=request.addresses,
        volume_metrics=request.volume_metrics,
        existing_processor=request.existing_processor,
    )
    item = to_decimal(business.model_dump(by_alias=True, exclude_none=True))

    response = PatchBusinessResponse(version=meta_item["version"] + 1)
    dynamo_client.put_item_with_meta_version_bump(
        item=item,
        meta_pk=pk,
        expected_version=meta_item["version"],
        meta_updates=_meta_update_fields(request.request_id, response),
    )
    return response
