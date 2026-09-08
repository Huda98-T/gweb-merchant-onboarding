"""Confirms presigned URLs and other sensitive fields never reach a log
line — the redaction requirement for /presign and /complete (spec plan §"Do
not log the presigned URL or sensitive data")."""

from __future__ import annotations

from common.logger import REDACTED_FIELDS, REDACTED_PLACEHOLDER, _redact


def test_redacted_fields_include_upload_url_variants():
    assert {"uploadUrl", "upload_url", "presignedUrl", "presigned_url"} <= REDACTED_FIELDS


def test_redact_replaces_upload_url_value():
    payload = {
        "documentId": "doc-1",
        "uploadUrl": "https://bucket.s3.amazonaws.com/secret-key?X-Amz-Signature=abc",
    }
    redacted = _redact(payload)
    assert redacted["uploadUrl"] == REDACTED_PLACEHOLDER
    assert redacted["documentId"] == "doc-1"  # non-sensitive fields pass through


def test_redact_handles_upload_url_nested_in_a_list_of_dicts():
    payload = [{"uploadUrl": "https://example.com/should-not-appear"}]
    redacted = _redact(payload)
    assert redacted[0]["uploadUrl"] == REDACTED_PLACEHOLDER
