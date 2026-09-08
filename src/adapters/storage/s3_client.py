"""S3 adapter — presigned uploads, HEAD, and streaming checksum/signature
verification. Lambda never proxies file bytes: it only mints a presigned
PUT URL (client uploads directly to S3) and later reads the object back
once, in /complete, to verify it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

from common.errors import UpstreamTimeoutError

DEFAULT_CHUNK_SIZE = 64 * 1024  # comfortably larger than any signature (<=8 bytes)

# Static, conservative socket-level timeouts — a defense-in-depth backstop
# against a truly hung connection. The budget-aware decision of whether to
# attempt the call at all lives in the service layer (common.timeouts),
# checked against the actual remaining Lambda time before each call.
_CONNECT_TIMEOUT_SECONDS = 10
_READ_TIMEOUT_SECONDS = 20


@lru_cache(maxsize=1)
def _client():
    return boto3.client(
        "s3",
        config=Config(
            signature_version="s3v4",
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            read_timeout=_READ_TIMEOUT_SECONDS,
        ),
    )


def generate_presigned_put_url(*, bucket: str, key: str, content_type: str, expires_in: int) -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def head_object(*, bucket: str, key: str) -> dict[str, object] | None:
    """Returns {"size_bytes": int, "content_type": str}, or None if missing."""
    try:
        response = _client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    except (ConnectTimeoutError, ReadTimeoutError) as exc:
        raise UpstreamTimeoutError("Timed out checking the uploaded object") from exc
    return {"size_bytes": response["ContentLength"], "content_type": response.get("ContentType")}


@dataclass(frozen=True)
class VerificationResult:
    signature_ok: bool
    checksum_sha256: str | None  # only set when signature_ok is True


def verify_object_stream(
    *, bucket: str, key: str, expected_magic: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> VerificationResult:
    """Streams the object exactly once: checks the leading bytes against
    `expected_magic` on the first chunk, and — only if that matches —
    keeps hashing every chunk (including the first) into one SHA-256.

    On a signature mismatch, the stream is closed immediately without
    reading (or hashing) the rest of the object.
    """
    try:
        body = _client().get_object(Bucket=bucket, Key=key)["Body"]
    except (ConnectTimeoutError, ReadTimeoutError) as exc:
        raise UpstreamTimeoutError("Timed out reading the uploaded object") from exc

    try:
        hasher = hashlib.sha256()
        first = True
        for chunk in body.iter_chunks(chunk_size):
            if first:
                first = False
                if not chunk.startswith(expected_magic):
                    return VerificationResult(signature_ok=False, checksum_sha256=None)
            hasher.update(chunk)
        return VerificationResult(signature_ok=True, checksum_sha256=hasher.hexdigest())
    except (ConnectTimeoutError, ReadTimeoutError) as exc:
        raise UpstreamTimeoutError("Timed out reading the uploaded object") from exc
    finally:
        body.close()
