"""Full presign -> (simulated client upload) -> complete flow through the
real Phase 2 handlers, against moto (DynamoDB + S3). Spec §3, refined by
the approved Phase 2 decisions.
"""

from __future__ import annotations

import hashlib
import json

import boto3

from handlers import complete_document, create_application, presign_document
from models.documents import MAX_DOCUMENT_SIZE_BYTES
from tests.conftest import BUCKET_NAME, FakeLambdaContext

CONTEXT = FakeLambdaContext()
PDF_CONTENT = b"%PDF-1.4\n" + b"x" * 5000
PDF_SIZE = len(PDF_CONTENT)


class _NearlyExpiredContext:
    """Reports too little remaining time for /complete to safely proceed."""

    def get_remaining_time_in_millis(self) -> int:
        return 5_000


def _event(*, path_id: str, token: str, document_id: str | None = None, body: dict) -> dict:
    event: dict = {
        "pathParameters": {"id": path_id},
        "headers": {"x-application-token": token},
        "body": json.dumps(body),
    }
    if document_id is not None:
        event["pathParameters"]["documentId"] = document_id
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def _create_application() -> str:
    return _body(create_application.handler({"headers": {}}, CONTEXT))["applicationId"]


def _presign(app_id: str, *, size_bytes: int = PDF_SIZE, request_id: str = "req-presign-1") -> dict:
    response = presign_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": request_id,
                "docType": "BANK_EVIDENCE",
                "fileName": "statement.pdf",
                "mimeType": "application/pdf",
                "sizeBytes": size_bytes,
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 200, response
    return _body(response)


def _upload(s3_key: str, content: bytes) -> None:
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=BUCKET_NAME, Key=s3_key, Body=content
    )


def test_valid_presign_returns_upload_url_and_document_id(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id)
    assert presigned["documentId"]
    assert presigned["uploadUrl"].startswith("https://")
    assert presigned["s3Key"].startswith(f"applications/{app_id}/documents/")
    assert presigned["expiresIn"] == 300


def test_presign_requires_matching_application_token(documents_bucket):
    app_id = _create_application()
    response = presign_document.handler(
        _event(
            path_id=app_id,
            token="wrong-token",
            body={
                "requestId": "r1",
                "docType": "BANK_EVIDENCE",
                "fileName": "s.pdf",
                "mimeType": "application/pdf",
                "sizeBytes": 100,
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 401


def test_presign_returns_404_for_unknown_application(documents_bucket):
    response = presign_document.handler(
        _event(
            path_id="ghost",
            token="ghost",
            body={
                "requestId": "r1",
                "docType": "BANK_EVIDENCE",
                "fileName": "s.pdf",
                "mimeType": "application/pdf",
                "sizeBytes": 100,
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 404


def test_presign_rejects_invalid_mime_type(documents_bucket):
    app_id = _create_application()
    response = presign_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "r1",
                "docType": "BANK_EVIDENCE",
                "fileName": "s.pdf",
                "mimeType": "application/zip",
                "sizeBytes": 100,
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 400


def test_presign_rejects_extension_not_matching_mime_type(documents_bucket):
    app_id = _create_application()
    response = presign_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "r1",
                "docType": "BANK_EVIDENCE",
                "fileName": "s.png",
                "mimeType": "application/pdf",
                "sizeBytes": 100,
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 400


def test_presign_rejects_invalid_doc_type(documents_bucket):
    app_id = _create_application()
    response = presign_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "r1",
                "docType": "PASSPORT",
                "fileName": "s.pdf",
                "mimeType": "application/pdf",
                "sizeBytes": 100,
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 400


def test_presign_rejects_oversized_declared_file(documents_bucket):
    app_id = _create_application()
    response = presign_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            body={
                "requestId": "r1",
                "docType": "BANK_EVIDENCE",
                "fileName": "s.pdf",
                "mimeType": "application/pdf",
                "sizeBytes": MAX_DOCUMENT_SIZE_BYTES + 1,
            },
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 400


def test_valid_upload_then_complete_transitions_to_accepted(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id)
    _upload(presigned["s3Key"], PDF_CONTENT)

    response = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["status"] == "ACCEPTED"
    assert body["checksumSha256"] == hashlib.sha256(PDF_CONTENT).hexdigest()
    assert "rejectionReason" not in body


def test_complete_returns_rejected_when_s3_object_is_missing(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id)
    # no upload performed

    response = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["status"] == "REJECTED"
    assert body["rejectionReason"] == "object_not_found"


def test_complete_returns_rejected_on_signature_mismatch(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id, size_bytes=len(b"not a real pdf file"))
    _upload(presigned["s3Key"], b"not a real pdf file")

    response = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["status"] == "REJECTED"
    assert body["rejectionReason"] == "signature_mismatch"
    assert "checksumSha256" not in body


def test_complete_returns_rejected_on_size_mismatch(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id, size_bytes=999999)  # doesn't match what's actually uploaded
    _upload(presigned["s3Key"], PDF_CONTENT)

    response = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["status"] == "REJECTED"
    assert body["rejectionReason"] == "size_mismatch"


def test_complete_returns_rejected_when_actual_object_exceeds_max_size(documents_bucket):
    app_id = _create_application()
    oversized = b"%PDF-1.4\n" + b"x" * MAX_DOCUMENT_SIZE_BYTES  # actual > MAX, declared == MAX
    presigned = _presign(app_id, size_bytes=MAX_DOCUMENT_SIZE_BYTES)
    _upload(presigned["s3Key"], oversized)

    response = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["status"] == "REJECTED"
    assert body["rejectionReason"] == "file_too_large"


def test_complete_requires_matching_application_token(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id)
    _upload(presigned["s3Key"], PDF_CONTENT)

    response = complete_document.handler(
        _event(
            path_id=app_id,
            token="wrong-token",
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 401


def test_complete_returns_404_for_document_belonging_to_a_different_application(documents_bucket):
    app_id = _create_application()
    other_app_id = _create_application()
    presigned = _presign(app_id)
    _upload(presigned["s3Key"], PDF_CONTENT)

    # Correct token for other_app_id, but the documentId belongs to app_id.
    response = complete_document.handler(
        _event(
            path_id=other_app_id,
            token=other_app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert response["statusCode"] == 404


def test_complete_rejects_double_completion(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id)
    _upload(presigned["s3Key"], PDF_CONTENT)

    first = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        CONTEXT,
    )
    assert first["statusCode"] == 200

    second = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-2"},  # different requestId -> not a replay
        ),
        CONTEXT,
    )
    assert second["statusCode"] == 409


def test_complete_is_idempotent_on_repeated_request_id(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id)
    _upload(presigned["s3Key"], PDF_CONTENT)
    body = {"requestId": "req-complete-retry"}

    first = _body(
        complete_document.handler(
            _event(path_id=app_id, token=app_id, document_id=presigned["documentId"], body=body),
            CONTEXT,
        )
    )
    second = _body(
        complete_document.handler(
            _event(path_id=app_id, token=app_id, document_id=presigned["documentId"], body=body),
            CONTEXT,
        )
    )
    assert first == second


def test_complete_returns_504_when_insufficient_time_remains(documents_bucket):
    app_id = _create_application()
    presigned = _presign(app_id)
    _upload(presigned["s3Key"], PDF_CONTENT)

    response = complete_document.handler(
        _event(
            path_id=app_id,
            token=app_id,
            document_id=presigned["documentId"],
            body={"requestId": "req-complete-1"},
        ),
        _NearlyExpiredContext(),
    )
    assert response["statusCode"] == 504
