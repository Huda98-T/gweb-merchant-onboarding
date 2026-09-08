"""Validation behavior of the Phase 2 document request models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.documents import (
    MAX_DOCUMENT_SIZE_BYTES,
    CompleteDocumentRequest,
    DocumentType,
    PresignDocumentRequest,
)


def _valid_presign_payload(**overrides) -> dict:
    payload = {
        "requestId": "req-1",
        "docType": "BANK_EVIDENCE",
        "fileName": "statement.pdf",
        "mimeType": "application/pdf",
        "sizeBytes": 1024,
    }
    payload.update(overrides)
    return payload


def test_presign_request_accepts_valid_payload():
    request = PresignDocumentRequest.model_validate(_valid_presign_payload())
    assert request.doc_type == DocumentType.BANK_EVIDENCE
    assert request.size_bytes == 1024


@pytest.mark.parametrize(
    "doc_type",
    [
        "GOVERNMENT_ID",
        "BUSINESS_REGISTRATION",
        "BUSINESS_LICENSE",
        "BANK_EVIDENCE",
        "PROCESSING_STATEMENT",
        "ADDITIONAL_EVIDENCE",
    ],
)
def test_presign_request_accepts_every_approved_doc_type(doc_type):
    request = PresignDocumentRequest.model_validate(_valid_presign_payload(docType=doc_type))
    assert request.doc_type.value == doc_type


def test_presign_request_rejects_invalid_doc_type():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(_valid_presign_payload(docType="PASSPORT_SCAN"))


def test_presign_request_rejects_invalid_mime_type():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(
            _valid_presign_payload(mimeType="application/octet-stream")
        )


def test_presign_request_rejects_extension_mismatched_with_mime_type():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(
            _valid_presign_payload(fileName="statement.png", mimeType="application/pdf")
        )


def test_presign_request_accepts_jpg_and_jpeg_extensions_for_jpeg_mime_type():
    for name in ("photo.jpg", "photo.jpeg", "photo.JPG"):
        PresignDocumentRequest.model_validate(
            _valid_presign_payload(fileName=name, mimeType="image/jpeg")
        )


def test_presign_request_rejects_empty_filename():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(_valid_presign_payload(fileName=""))


def test_presign_request_rejects_filename_with_path_separator():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(
            _valid_presign_payload(fileName="../../etc/passwd.pdf")
        )


def test_presign_request_rejects_oversized_declared_size():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(
            _valid_presign_payload(sizeBytes=MAX_DOCUMENT_SIZE_BYTES + 1)
        )


def test_presign_request_accepts_size_at_the_exact_limit():
    request = PresignDocumentRequest.model_validate(
        _valid_presign_payload(sizeBytes=MAX_DOCUMENT_SIZE_BYTES)
    )
    assert request.size_bytes == MAX_DOCUMENT_SIZE_BYTES


def test_presign_request_rejects_zero_or_negative_size():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(_valid_presign_payload(sizeBytes=0))


def test_presign_request_rejects_empty_request_id():
    with pytest.raises(ValidationError):
        PresignDocumentRequest.model_validate(_valid_presign_payload(requestId=""))


def test_complete_document_request_accepts_valid_payload():
    request = CompleteDocumentRequest.model_validate({"requestId": "req-1"})
    assert request.request_id == "req-1"


def test_complete_document_request_rejects_empty_request_id():
    with pytest.raises(ValidationError):
        CompleteDocumentRequest.model_validate({"requestId": ""})
