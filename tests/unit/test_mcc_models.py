from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.mcc import ClassifyRequest, ConfirmMccRequest


def test_classify_request_accepts_valid_payload():
    request = ClassifyRequest.model_validate(
        {"requestId": "r1", "selfSelectedActivity": "Restaurant", "businessDescription": "Pizza"}
    )
    assert request.self_selected_activity == "Restaurant"


def test_classify_request_business_description_is_optional():
    request = ClassifyRequest.model_validate(
        {"requestId": "r1", "selfSelectedActivity": "Restaurant"}
    )
    assert request.business_description is None


def test_classify_request_rejects_empty_request_id():
    with pytest.raises(ValidationError):
        ClassifyRequest.model_validate({"requestId": "", "selfSelectedActivity": "Restaurant"})


def test_classify_request_rejects_empty_self_selected_activity():
    with pytest.raises(ValidationError):
        ClassifyRequest.model_validate({"requestId": "r1", "selfSelectedActivity": ""})


def test_confirm_request_accepts_valid_payload():
    request = ConfirmMccRequest.model_validate({"requestId": "r1", "code": "5812"})
    assert request.code == "5812"


def test_confirm_request_rejects_empty_request_id():
    with pytest.raises(ValidationError):
        ConfirmMccRequest.model_validate({"requestId": "", "code": "5812"})


def test_confirm_request_rejects_empty_code():
    with pytest.raises(ValidationError):
        ConfirmMccRequest.model_validate({"requestId": "r1", "code": ""})
