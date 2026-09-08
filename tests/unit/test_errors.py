from __future__ import annotations

import json

from pydantic import BaseModel

from common.errors import ConflictError, NotFoundError, handle_errors


class _Model(BaseModel):
    name: str


def test_handle_errors_passes_through_success():
    @handle_errors
    def handler(event, context):
        return {"statusCode": 200, "body": "{}"}

    assert handler({}, None) == {"statusCode": 200, "body": "{}"}


def test_handle_errors_maps_not_found_error():
    @handle_errors
    def handler(event, context):
        raise NotFoundError("Application not found")

    response = handler({}, None)
    assert response["statusCode"] == 404
    assert json.loads(response["body"]) == {"message": "Application not found"}


def test_handle_errors_maps_conflict_error():
    @handle_errors
    def handler(event, context):
        raise ConflictError("version mismatch")

    response = handler({}, None)
    assert response["statusCode"] == 409


def test_handle_errors_maps_pydantic_validation_error():
    @handle_errors
    def handler(event, context):
        _Model.model_validate({})

    response = handler({}, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["message"] == "Invalid request body"
    assert body["errors"]


def test_handle_errors_maps_unexpected_exception_to_500_without_leaking_details():
    @handle_errors
    def handler(event, context):
        raise RuntimeError("boom: secret internal detail")

    response = handler({}, None)
    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert body == {"message": "Internal server error"}
    assert "secret" not in response["body"]
