"""Document upload models — DOC# item shape and presign/complete API schemas.

Phase 2 (GWEB_Implementation_Spec.md §2.2 DOC# row, §3 presign/complete
routes), refined by the approved Phase 2 decisions: server-only SHA-256
(no client-supplied checksum), 5-minute presign expiry, 15 MB cap
(configurable), and REQUESTED -> ACCEPTED|REJECTED as the only Phase 2
transitions (PROCESSING stays defined for later async/queued verification).
"""

from __future__ import annotations

import os
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_DOCUMENT_SIZE_BYTES = int(os.environ.get("MAX_DOCUMENT_SIZE_BYTES", 15 * 1024 * 1024))
PRESIGNED_URL_EXPIRY_SECONDS = 300

_FILENAME_MAX_LENGTH = 255
_UNSAFE_FILENAME_CHARS = re.compile(r"[/\\\x00-\x1f]")


class DocumentType(StrEnum):
    GOVERNMENT_ID = "GOVERNMENT_ID"
    BUSINESS_REGISTRATION = "BUSINESS_REGISTRATION"
    BUSINESS_LICENSE = "BUSINESS_LICENSE"
    BANK_EVIDENCE = "BANK_EVIDENCE"
    PROCESSING_STATEMENT = "PROCESSING_STATEMENT"
    ADDITIONAL_EVIDENCE = "ADDITIONAL_EVIDENCE"


class DocumentStatus(StrEnum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"  # defined for future async/queued verification; unused in Phase 2
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DocumentMimeType(StrEnum):
    PDF = "application/pdf"
    JPEG = "image/jpeg"
    PNG = "image/png"


class RejectionReason(StrEnum):
    """Safe, non-sensitive codes — never derived from file contents."""

    OBJECT_NOT_FOUND = "object_not_found"
    FILE_TOO_LARGE = "file_too_large"
    SIZE_MISMATCH = "size_mismatch"
    SIGNATURE_MISMATCH = "signature_mismatch"


# Allowed filename extensions per declared MIME type (presign-time, client-declared check).
MIME_TO_EXTENSIONS: dict[DocumentMimeType, tuple[str, ...]] = {
    DocumentMimeType.PDF: (".pdf",),
    DocumentMimeType.JPEG: (".jpg", ".jpeg"),
    DocumentMimeType.PNG: (".png",),
}

# Canonical extension used when building the S3 key — derived from the
# server-validated MIME type, never from the client's raw filename.
MIME_TO_KEY_EXTENSION: dict[DocumentMimeType, str] = {
    DocumentMimeType.PDF: ".pdf",
    DocumentMimeType.JPEG: ".jpg",
    DocumentMimeType.PNG: ".png",
}

# File-signature ("magic bytes") each MIME type must start with — checked
# server-side in /complete against the actual uploaded bytes.
MIME_TO_MAGIC_BYTES: dict[DocumentMimeType, bytes] = {
    DocumentMimeType.PDF: b"%PDF-",
    DocumentMimeType.JPEG: b"\xff\xd8\xff",
    DocumentMimeType.PNG: b"\x89PNG\r\n\x1a\n",
}


def _validate_filename(file_name: str) -> str:
    if not file_name or not file_name.strip():
        raise ValueError("fileName must not be empty")
    if len(file_name) > _FILENAME_MAX_LENGTH:
        raise ValueError(f"fileName must be at most {_FILENAME_MAX_LENGTH} characters")
    if _UNSAFE_FILENAME_CHARS.search(file_name):
        raise ValueError("fileName contains unsafe characters")
    if file_name in (".", ".."):
        raise ValueError("fileName must not be a path segment")
    return file_name


class DocumentItem(BaseModel):
    """`PK = APP#<appId>`, `SK = DOC#<documentId>`."""

    model_config = ConfigDict(populate_by_name=True)

    pk: str = Field(alias="PK")
    sk: str = Field(alias="SK")
    document_id: str = Field(alias="documentId")
    doc_type: DocumentType = Field(alias="docType")
    status: DocumentStatus = DocumentStatus.REQUESTED
    file_name: str = Field(alias="fileName")
    declared_mime_type: DocumentMimeType = Field(alias="declaredMimeType")
    declared_size_bytes: int = Field(alias="declaredSizeBytes")
    s3_key: str = Field(alias="s3Key")
    requested_at: str = Field(alias="requestedAt")
    expires_at: str = Field(alias="expiresAt")
    actual_size_bytes: int | None = Field(default=None, alias="actualSizeBytes")
    checksum_sha256: str | None = Field(default=None, alias="checksumSha256")
    verified_at: str | None = Field(default=None, alias="verifiedAt")
    rejection_reason: RejectionReason | None = Field(default=None, alias="rejectionReason")
    last_request_id: str | None = Field(default=None, alias="lastRequestId")
    last_response: dict[str, Any] | None = Field(default=None, alias="lastResponse")


class PresignDocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId", min_length=1)
    doc_type: DocumentType = Field(alias="docType")
    file_name: str = Field(alias="fileName")
    mime_type: DocumentMimeType = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes", gt=0, le=MAX_DOCUMENT_SIZE_BYTES)

    @model_validator(mode="after")
    def _check_filename(self) -> PresignDocumentRequest:
        _validate_filename(self.file_name)
        allowed = MIME_TO_EXTENSIONS[self.mime_type]
        if not self.file_name.lower().endswith(allowed):
            raise ValueError(
                f"fileName extension does not match mimeType {self.mime_type.value} "
                f"(expected one of {allowed})"
            )
        return self


class PresignDocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str = Field(alias="documentId")
    upload_url: str = Field(alias="uploadUrl")
    s3_key: str = Field(alias="s3Key")
    expires_in: int = Field(alias="expiresIn")


class CompleteDocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId", min_length=1)


class CompleteDocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str = Field(alias="documentId")
    status: DocumentStatus
    checksum_sha256: str | None = Field(default=None, alias="checksumSha256")
    rejection_reason: RejectionReason | None = Field(default=None, alias="rejectionReason")
    verified_at: str = Field(alias="verifiedAt")
