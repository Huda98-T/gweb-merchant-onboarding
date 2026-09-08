"""Business logic for document upload (spec §3 presign/complete), refined
by the approved Phase 2 decisions: server-only SHA-256, 5-minute presign
expiry, REQUESTED -> ACCEPTED|REJECTED as the only Phase 2 transitions.

Idempotency here is scoped per-document (`DOC#` item's own `lastRequestId`/
`lastResponse`), not the application's META — matches spec §2.4's literal
"store lastRequestId on META/DOC# items" wording. Presign is a create (like
POST /applications) and is not idempotent-replayed, for the same reason
create_application isn't: there's no existing item to check against before
the new documentId is minted.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from adapters.db import dynamo_client
from adapters.storage import s3_client
from common.decimal_utils import from_decimal, to_decimal
from common.errors import ConflictError, NotFoundError, UpstreamTimeoutError
from common.timeouts import DOCUMENT_STREAM_MIN_REMAINING_MS, remaining_ms
from models.documents import (
    MAX_DOCUMENT_SIZE_BYTES,
    MIME_TO_KEY_EXTENSION,
    MIME_TO_MAGIC_BYTES,
    PRESIGNED_URL_EXPIRY_SECONDS,
    CompleteDocumentRequest,
    CompleteDocumentResponse,
    DocumentItem,
    DocumentMimeType,
    DocumentStatus,
    PresignDocumentRequest,
    PresignDocumentResponse,
    RejectionReason,
)


def _application_pk(application_id: str) -> str:
    return f"APP#{application_id}"


def _document_sk(document_id: str) -> str:
    return f"DOC#{document_id}"


def _bucket_name() -> str:
    return os.environ["DOCUMENTS_BUCKET_NAME"]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def presign_document(
    application_id: str, request: PresignDocumentRequest
) -> PresignDocumentResponse:
    pk = _application_pk(application_id)
    dynamo_client.get_item_or_404(pk, "META", not_found_message="Application not found")

    document_id = uuid.uuid4().hex
    extension = MIME_TO_KEY_EXTENSION[request.mime_type]
    s3_key = f"applications/{application_id}/documents/{document_id}{extension}"

    requested_at = _utc_now_iso()
    expires_at = (datetime.now(UTC) + timedelta(seconds=PRESIGNED_URL_EXPIRY_SECONDS)).isoformat()

    item = DocumentItem(
        pk=pk,
        sk=_document_sk(document_id),
        document_id=document_id,
        doc_type=request.doc_type,
        status=DocumentStatus.REQUESTED,
        file_name=request.file_name,
        declared_mime_type=request.mime_type,
        declared_size_bytes=request.size_bytes,
        s3_key=s3_key,
        requested_at=requested_at,
        expires_at=expires_at,
    )
    dynamo_client.put_item_if_absent(item.model_dump(by_alias=True, exclude_none=True))

    upload_url = s3_client.generate_presigned_put_url(
        bucket=_bucket_name(),
        key=s3_key,
        content_type=request.mime_type.value,
        expires_in=PRESIGNED_URL_EXPIRY_SECONDS,
    )

    return PresignDocumentResponse(
        document_id=document_id,
        upload_url=upload_url,
        s3_key=s3_key,
        expires_in=PRESIGNED_URL_EXPIRY_SECONDS,
    )


def _idempotent_replay[T: BaseModel](
    doc_item: dict, request_id: str, response_model: type[T]
) -> T | None:
    if doc_item.get("lastRequestId") == request_id and doc_item.get("lastResponse"):
        return response_model.model_validate(doc_item["lastResponse"])
    return None


def _finalize(
    *,
    pk: str,
    sk: str,
    document_id: str,
    status: DocumentStatus,
    request_id: str,
    verified_at: str,
    actual_size_bytes: int | None = None,
    checksum_sha256: str | None = None,
    rejection_reason: RejectionReason | None = None,
) -> CompleteDocumentResponse:
    response = CompleteDocumentResponse(
        document_id=document_id,
        status=status,
        checksum_sha256=checksum_sha256,
        rejection_reason=rejection_reason,
        verified_at=verified_at,
    )
    updates: dict = {
        "status": status.value,
        "verifiedAt": verified_at,
        "lastRequestId": request_id,
        "lastResponse": response.model_dump(by_alias=True, exclude_none=True),
    }
    if actual_size_bytes is not None:
        updates["actualSizeBytes"] = actual_size_bytes
    if checksum_sha256 is not None:
        updates["checksumSha256"] = checksum_sha256
    if rejection_reason is not None:
        updates["rejectionReason"] = rejection_reason.value

    dynamo_client.update_item(
        pk,
        sk,
        to_decimal(updates),
        condition_expression="#currentStatus = :requestedStatus",
        condition_names={"#currentStatus": "status"},
        condition_values={":requestedStatus": DocumentStatus.REQUESTED.value},
    )
    return response


def complete_document(
    application_id: str, document_id: str, request: CompleteDocumentRequest, context
) -> CompleteDocumentResponse:
    pk = _application_pk(application_id)
    sk = _document_sk(document_id)

    raw_item = dynamo_client.get_item(pk, sk)
    if raw_item is None:
        raise NotFoundError("Document not found")
    doc_item = from_decimal(raw_item)

    cached = _idempotent_replay(doc_item, request.request_id, CompleteDocumentResponse)
    if cached is not None:
        return cached

    if doc_item["status"] != DocumentStatus.REQUESTED.value:
        raise ConflictError("Document has already been completed")

    if remaining_ms(context) < DOCUMENT_STREAM_MIN_REMAINING_MS:
        raise UpstreamTimeoutError("Insufficient time remaining to verify the document")

    verified_at = _utc_now_iso()
    bucket = _bucket_name()
    s3_key = doc_item["s3Key"]
    declared_size = doc_item["declaredSizeBytes"]
    mime_type = doc_item["declaredMimeType"]

    head = s3_client.head_object(bucket=bucket, key=s3_key)
    if head is None:
        return _finalize(
            pk=pk,
            sk=sk,
            document_id=document_id,
            status=DocumentStatus.REJECTED,
            request_id=request.request_id,
            verified_at=verified_at,
            rejection_reason=RejectionReason.OBJECT_NOT_FOUND,
        )

    actual_size = head["size_bytes"]
    if actual_size > MAX_DOCUMENT_SIZE_BYTES:
        return _finalize(
            pk=pk,
            sk=sk,
            document_id=document_id,
            status=DocumentStatus.REJECTED,
            request_id=request.request_id,
            verified_at=verified_at,
            actual_size_bytes=actual_size,
            rejection_reason=RejectionReason.FILE_TOO_LARGE,
        )
    if actual_size != declared_size:
        return _finalize(
            pk=pk,
            sk=sk,
            document_id=document_id,
            status=DocumentStatus.REJECTED,
            request_id=request.request_id,
            verified_at=verified_at,
            actual_size_bytes=actual_size,
            rejection_reason=RejectionReason.SIZE_MISMATCH,
        )

    expected_magic = MIME_TO_MAGIC_BYTES[DocumentMimeType(mime_type)]
    verification = s3_client.verify_object_stream(
        bucket=bucket, key=s3_key, expected_magic=expected_magic
    )
    if not verification.signature_ok:
        return _finalize(
            pk=pk,
            sk=sk,
            document_id=document_id,
            status=DocumentStatus.REJECTED,
            request_id=request.request_id,
            verified_at=verified_at,
            actual_size_bytes=actual_size,
            rejection_reason=RejectionReason.SIGNATURE_MISMATCH,
        )

    return _finalize(
        pk=pk,
        sk=sk,
        document_id=document_id,
        status=DocumentStatus.ACCEPTED,
        request_id=request.request_id,
        verified_at=verified_at,
        actual_size_bytes=actual_size,
        checksum_sha256=verification.checksum_sha256,
    )
