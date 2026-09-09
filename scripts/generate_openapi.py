#!/usr/bin/env python3
"""Generates openapi.yaml directly from the Pydantic request/response
models in src/models/ — not hand-authored, so the spec can never drift
from the actual contract without a code change forcing a regeneration.

Run after any request/response model change:

    python3 scripts/generate_openapi.py

Deliberately minimal (spec §12 asks for path/method/request/response
schema per route, not exhaustive API-documentation prose): one route
table below (mirroring template.yaml exactly) drives everything else.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import yaml  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from pydantic.json_schema import models_json_schema  # noqa: E402

from models.api import (  # noqa: E402
    CreateApplicationResponse,
    GetApplicationResponse,
    PatchApplicantRequest,
    PatchApplicantResponse,
    PatchBusinessRequest,
    PatchBusinessResponse,
)
from models.documents import (  # noqa: E402
    CompleteDocumentRequest,
    CompleteDocumentResponse,
    PresignDocumentRequest,
    PresignDocumentResponse,
)
from models.evaluation import (  # noqa: E402
    EvaluateRequest,
    EvaluateResponse,
    GetEvaluationResponse,
)
from models.mcc import (  # noqa: E402
    ClassifyRequest,
    ClassifyResponse,
    ConfirmMccRequest,
    ConfirmMccResponse,
    SearchMccResponse,
)
from models.review import ReviewResponse, SubmitRequest, SubmitResponse  # noqa: E402

APP_TOKEN_PARAM = {
    "name": "X-Application-Token",
    "in": "header",
    "required": True,
    "description": "Must equal the {id} path parameter — see SECURITY.md.",
    "schema": {"type": "string"},
}
ID_PATH_PARAM = {
    "name": "id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
}
DOCUMENT_ID_PATH_PARAM = {
    "name": "documentId",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
}
QUERY_PARAM = {
    "name": "query",
    "in": "query",
    "required": True,
    "schema": {"type": "string"},
}

# Mirrors template.yaml's route table exactly (13 routes).
ROUTES: list[dict] = [
    {
        "method": "post",
        "path": "/applications",
        "tag": "Applications",
        "summary": "Create an application",
        "auth": False,
        "request": None,
        "responses": {"201": CreateApplicationResponse},
    },
    {
        "method": "get",
        "path": "/applications/{id}",
        "tag": "Applications",
        "summary": "Aggregated read across the whole application",
        "auth": True,
        "request": None,
        "responses": {"200": GetApplicationResponse},
    },
    {
        "method": "patch",
        "path": "/applications/{id}/applicant",
        "tag": "Applicant",
        "summary": "Upsert one owner/controller",
        "auth": True,
        "request": PatchApplicantRequest,
        "responses": {"200": PatchApplicantResponse},
    },
    {
        "method": "patch",
        "path": "/applications/{id}/business",
        "tag": "Business",
        "summary": "Upsert the business profile",
        "auth": True,
        "request": PatchBusinessRequest,
        "responses": {"200": PatchBusinessResponse},
    },
    {
        "method": "post",
        "path": "/applications/{id}/documents/presign",
        "tag": "Documents",
        "summary": "Get a presigned S3 upload URL",
        "auth": True,
        "request": PresignDocumentRequest,
        "responses": {"200": PresignDocumentResponse},
    },
    {
        "method": "post",
        "path": "/applications/{id}/documents/{documentId}/complete",
        "tag": "Documents",
        "summary": "Verify an uploaded document (size/signature/checksum)",
        "auth": True,
        "extra_path_params": [DOCUMENT_ID_PATH_PARAM],
        "request": CompleteDocumentRequest,
        "responses": {"200": CompleteDocumentResponse},
    },
    {
        "method": "get",
        "path": "/mcc",
        "tag": "MCC",
        "summary": "Search the packaged MCC catalog",
        "auth": False,
        "query_params": [QUERY_PARAM],
        "request": None,
        "responses": {"200": SearchMccResponse},
    },
    {
        "method": "post",
        "path": "/applications/{id}/classify",
        "tag": "MCC",
        "summary": "Deterministic MCC classification (no AI/LLM)",
        "auth": True,
        "request": ClassifyRequest,
        "responses": {"200": ClassifyResponse},
    },
    {
        "method": "post",
        "path": "/applications/{id}/mcc/confirm",
        "tag": "MCC",
        "summary": "Applicant confirms or corrects the MCC",
        "auth": True,
        "request": ConfirmMccRequest,
        "responses": {"200": ConfirmMccResponse},
    },
    {
        "method": "post",
        "path": "/applications/{id}/evaluate",
        "tag": "Evaluation",
        "summary": "Deterministic rate/fee calc + mock AI commentary",
        "auth": True,
        "request": EvaluateRequest,
        "responses": {"200": EvaluateResponse, "202": EvaluateResponse},
    },
    {
        "method": "get",
        "path": "/applications/{id}/evaluation",
        "tag": "Evaluation",
        "summary": "Poll the evaluation result",
        "auth": True,
        "request": None,
        "responses": {"200": GetEvaluationResponse},
    },
    {
        "method": "get",
        "path": "/applications/{id}/review",
        "tag": "Review & Submit",
        "summary": "Readiness view — same computation submit validates against",
        "auth": True,
        "request": None,
        "responses": {"200": ReviewResponse},
    },
    {
        "method": "post",
        "path": "/applications/{id}/submit",
        "tag": "Review & Submit",
        "summary": "Validate and submit (DRAFT -> SUBMITTED)",
        "auth": True,
        "request": SubmitRequest,
        "responses": {"200": SubmitResponse, "400": SubmitResponse},
    },
]


def _collect_models() -> list[tuple[type[BaseModel], str]]:
    seen: set[tuple[str, str]] = set()
    models: list[tuple[type[BaseModel], str]] = []
    for route in ROUTES:
        if route["request"] is not None:
            pair = (route["request"], "validation")
            if (pair[0].__name__, pair[1]) not in seen:
                seen.add((pair[0].__name__, pair[1]))
                models.append(pair)
        for model in route["responses"].values():
            pair = (model, "serialization")
            if (pair[0].__name__, pair[1]) not in seen:
                seen.add((pair[0].__name__, pair[1]))
                models.append(pair)
    return models


def build_spec() -> dict:
    models = _collect_models()
    key_map, top = models_json_schema(models, ref_template="#/components/schemas/{model}")
    schemas = top.get("$defs", {})

    paths: dict[str, dict] = {}
    for route in ROUTES:
        path_item = paths.setdefault(route["path"], {})
        # Deep-copy every shared param dict — reusing the same object across
        # routes makes pyyaml emit YAML anchors/aliases, which is valid but
        # needlessly unusual for a generated OpenAPI file.
        parameters = []
        if "{id}" in route["path"]:
            parameters.append(copy.deepcopy(ID_PATH_PARAM))
        parameters.extend(copy.deepcopy(p) for p in route.get("extra_path_params", []))
        if route["auth"]:
            parameters.append(copy.deepcopy(APP_TOKEN_PARAM))
        parameters.extend(copy.deepcopy(p) for p in route.get("query_params", []))

        operation: dict = {
            "summary": route["summary"],
            "tags": [route["tag"]],
            "parameters": parameters,
        }
        if route["request"] is not None:
            ref = key_map[(route["request"], "validation")]
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": copy.deepcopy(ref)}},
            }
        operation["responses"] = {}
        for status, model in route["responses"].items():
            ref = key_map[(model, "serialization")]
            operation["responses"][status] = {
                "description": "See SECURITY.md/README.md for auth/error semantics.",
                "content": {"application/json": {"schema": copy.deepcopy(ref)}},
            }
        if route["auth"]:
            operation["responses"].setdefault(
                "401", {"description": "Missing/invalid X-Application-Token"}
            )
        operation["responses"].setdefault(
            "404", {"description": "Application (or referenced resource) not found"}
        )

        path_item[route["method"]] = operation

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "GWEB Merchant Onboarding API",
            "version": "1.0.0",
            "description": (
                "Generated directly from src/models/*.py — do not hand-edit; "
                "run scripts/generate_openapi.py after any model change. "
                "See README.md for the full contract notes and SECURITY.md "
                "for the auth model."
            ),
        },
        "servers": [{"url": "/v1"}],
        "paths": dict(sorted(paths.items())),
        "components": {"schemas": dict(sorted(schemas.items()))},
    }


def main() -> None:
    spec = build_spec()
    out_path = REPO_ROOT / "openapi.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Generated by scripts/generate_openapi.py — do not hand-edit.\n")
        yaml.safe_dump(spec, f, sort_keys=False, allow_unicode=True, width=100)
    path_count = len(spec["paths"])
    schema_count = len(spec["components"]["schemas"])
    print(f"Wrote {out_path} ({path_count} paths, {schema_count} schemas)")


if __name__ == "__main__":
    main()
