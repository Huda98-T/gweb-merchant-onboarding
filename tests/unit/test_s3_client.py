"""Adapter-level tests for the S3 helper (spec §3 presign/complete, Phase 2)."""

from __future__ import annotations

import hashlib

import boto3
import pytest
from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError

from adapters.storage import s3_client
from common.errors import UpstreamTimeoutError

PDF_MAGIC = b"%PDF-"
JPEG_MAGIC = b"\xff\xd8\xff"


def test_generate_presigned_put_url_returns_an_https_url(documents_bucket):
    url = s3_client.generate_presigned_put_url(
        bucket=documents_bucket,
        key="applications/a1/documents/d1.pdf",
        content_type="application/pdf",
        expires_in=300,
    )
    assert url.startswith("https://")


def test_head_object_returns_size_and_content_type(documents_bucket):
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=documents_bucket, Key="k1", Body=b"%PDF-1.4 hello"
    )
    result = s3_client.head_object(bucket=documents_bucket, key="k1")
    assert result["size_bytes"] == len(b"%PDF-1.4 hello")


def test_head_object_returns_none_for_missing_key(documents_bucket):
    assert s3_client.head_object(bucket=documents_bucket, key="does-not-exist") is None


def test_verify_object_stream_accepts_matching_signature_and_computes_checksum(documents_bucket):
    content = PDF_MAGIC + b"1.4 " + b"x" * 100_000
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=documents_bucket, Key="k2", Body=content
    )
    result = s3_client.verify_object_stream(
        bucket=documents_bucket, key="k2", expected_magic=PDF_MAGIC
    )
    assert result.signature_ok is True
    assert result.checksum_sha256 == hashlib.sha256(content).hexdigest()


def test_verify_object_stream_rejects_mismatched_signature_without_computing_checksum(
    documents_bucket,
):
    content = JPEG_MAGIC + b"not actually a pdf" * 1000
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=documents_bucket, Key="k3", Body=content
    )
    result = s3_client.verify_object_stream(
        bucket=documents_bucket, key="k3", expected_magic=PDF_MAGIC
    )
    assert result.signature_ok is False
    assert result.checksum_sha256 is None


def test_verify_object_stream_rejects_object_smaller_than_the_signature(documents_bucket):
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=documents_bucket,
        Key="k4",
        Body=b"%P",  # shorter than PDF_MAGIC
    )
    result = s3_client.verify_object_stream(
        bucket=documents_bucket, key="k4", expected_magic=PDF_MAGIC
    )
    assert result.signature_ok is False


def test_head_object_maps_slow_s3_dependency_to_upstream_timeout_error(monkeypatch):
    class _FakeClient:
        def head_object(self, **kwargs):
            raise ReadTimeoutError(endpoint_url="https://s3.amazonaws.com/bucket/key")

    monkeypatch.setattr(s3_client, "_client", lambda: _FakeClient())
    with pytest.raises(UpstreamTimeoutError):
        s3_client.head_object(bucket="b", key="k")


def test_verify_object_stream_maps_connect_timeout_to_upstream_timeout_error(monkeypatch):
    class _FakeClient:
        def get_object(self, **kwargs):
            raise ConnectTimeoutError(endpoint_url="https://s3.amazonaws.com/bucket/key")

    monkeypatch.setattr(s3_client, "_client", lambda: _FakeClient())
    with pytest.raises(UpstreamTimeoutError):
        s3_client.verify_object_stream(bucket="b", key="k", expected_magic=PDF_MAGIC)
