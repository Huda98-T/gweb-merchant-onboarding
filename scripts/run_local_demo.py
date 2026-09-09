#!/usr/bin/env python3
"""Local demo harness for the UI in ui/index.html.

Runs the REAL Lambda handler code (src/handlers/*) against a real local
AWS emulator — moto's ThreadedMotoServer, a genuine HTTP server backing
DynamoDB and S3 — instead of a real AWS account. This is NOT a substitute
for `sam build` / `sam deploy` (see README.md for the real deployment
path); it exists so the demo UI can exercise the actual backend logic,
including a real direct-to-S3 presigned upload, with zero AWS account
setup. No application code is duplicated or reimplemented here — this
script only does HTTP routing + a synthetic API Gateway v2 event, then
calls the same `handler(event, context)` functions the tests call.

Usage:
    python3 scripts/run_local_demo.py
    (then open http://localhost:8080/)
"""

from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
UI_DIR = REPO_ROOT / "ui"
sys.path.insert(0, str(SRC_DIR))

# 5000 is macOS's AirPlay Receiver by default — 8080/8001 avoid that and
# other common local-dev collisions.
API_PORT = int(os.environ.get("DEMO_API_PORT", "8080"))
MOTO_PORT = int(os.environ.get("DEMO_MOTO_PORT", "8001"))
TABLE_NAME = "gweb-onboarding-local"
BUCKET_NAME = "gweb-onboarding-documents-local"
MOTO_ENDPOINT = f"http://localhost:{MOTO_PORT}"

os.environ.setdefault("AWS_ACCESS_KEY_ID", "local-demo")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local-demo")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["TABLE_NAME"] = TABLE_NAME
os.environ["DOCUMENTS_BUCKET_NAME"] = BUCKET_NAME
os.environ.setdefault("MAX_DOCUMENT_SIZE_BYTES", str(15 * 1024 * 1024))
# botocore respects this for every service unless a per-service override
# is set — routes all of the app's boto3 calls (DynamoDB, S3, presigned
# URLs) at the local moto server instead of real AWS.
os.environ["AWS_ENDPOINT_URL"] = MOTO_ENDPOINT

import boto3  # noqa: E402
from moto.server import ThreadedMotoServer  # noqa: E402

from handlers import (  # noqa: E402
    classify_mcc,
    complete_document,
    confirm_mcc,
    create_application,
    evaluate,
    get_application,
    get_evaluation,
    get_review,
    patch_applicant,
    patch_business,
    presign_document,
    search_mcc,
    submit,
)


class FakeLambdaContext:
    def get_remaining_time_in_millis(self) -> int:
        return 45_000


ROUTES: list[tuple[str, re.Pattern, object]] = [
    ("POST", re.compile(r"^/v1/applications$"), create_application),
    ("GET", re.compile(r"^/v1/applications/(?P<id>[^/]+)$"), get_application),
    ("PATCH", re.compile(r"^/v1/applications/(?P<id>[^/]+)/applicant$"), patch_applicant),
    ("PATCH", re.compile(r"^/v1/applications/(?P<id>[^/]+)/business$"), patch_business),
    (
        "POST",
        re.compile(r"^/v1/applications/(?P<id>[^/]+)/documents/presign$"),
        presign_document,
    ),
    (
        "POST",
        re.compile(r"^/v1/applications/(?P<id>[^/]+)/documents/(?P<documentId>[^/]+)/complete$"),
        complete_document,
    ),
    ("GET", re.compile(r"^/v1/mcc$"), search_mcc),
    ("POST", re.compile(r"^/v1/applications/(?P<id>[^/]+)/classify$"), classify_mcc),
    ("POST", re.compile(r"^/v1/applications/(?P<id>[^/]+)/mcc/confirm$"), confirm_mcc),
    ("POST", re.compile(r"^/v1/applications/(?P<id>[^/]+)/evaluate$"), evaluate),
    ("GET", re.compile(r"^/v1/applications/(?P<id>[^/]+)/evaluation$"), get_evaluation),
    ("GET", re.compile(r"^/v1/applications/(?P<id>[^/]+)/review$"), get_review),
    ("POST", re.compile(r"^/v1/applications/(?P<id>[^/]+)/submit$"), submit),
]


def _bootstrap_aws_resources() -> None:
    ddb = boto3.client("dynamodb", endpoint_url=MOTO_ENDPOINT)
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    s3 = boto3.client("s3", endpoint_url=MOTO_ENDPOINT)
    s3.create_bucket(Bucket=BUCKET_NAME)
    s3.put_bucket_cors(
        Bucket=BUCKET_NAME,
        CORSConfiguration={
            "CORSRules": [
                {"AllowedOrigins": ["*"], "AllowedMethods": ["PUT"], "AllowedHeaders": ["*"]}
            ]
        },
    )


class DemoRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        sys.stderr.write(f"[demo-api] {self.address_string()} {fmt % args}\n")

    def _cors_headers(self) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Application-Token",
        }

    def _send_json(self, status: int, body: dict, extra_headers: dict | None = None) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for k, v in self._cors_headers().items():
            self.send_header(k, v)
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _serve_static(self, path: str) -> None:
        file_path = UI_DIR / ("index.html" if path in ("/", "") else path.lstrip("/"))
        if not file_path.is_file():
            self._send_json(404, {"message": "Not found"})
            return
        content_type = "text/html" if file_path.suffix == ".html" else "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/v1/"):
            if method == "GET":
                self._serve_static(parsed.path)
            else:
                self._send_json(404, {"message": "Not found"})
            return

        for route_method, pattern, module in ROUTES:
            match = pattern.match(parsed.path)
            if match and route_method == method:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw_body = self.rfile.read(length).decode("utf-8") if length else None
                event = {
                    "pathParameters": match.groupdict() or None,
                    "queryStringParameters": {k: v[0] for k, v in parse_qs(parsed.query).items()}
                    or None,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": raw_body,
                }
                response = module.handler(event, FakeLambdaContext())
                headers = {
                    k: v for k, v in response.get("headers", {}).items() if k != "Content-Type"
                }
                self._send_json(response["statusCode"], json.loads(response["body"]), headers)
                return

        self._send_json(404, {"message": "No route matched"})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        for k, v in self._cors_headers().items():
            self.send_header(k, v)
        self.end_headers()


def main() -> None:
    moto_server = ThreadedMotoServer(port=MOTO_PORT, verbose=False)
    moto_server.start()
    try:
        _bootstrap_aws_resources()
        print(f"[demo] moto AWS emulator running at {MOTO_ENDPOINT}")
        print(f"[demo] API + UI running at http://localhost:{API_PORT}/  (open this in a browser)")
        ThreadingHTTPServer(("localhost", API_PORT), DemoRequestHandler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        moto_server.stop()


if __name__ == "__main__":
    main()
