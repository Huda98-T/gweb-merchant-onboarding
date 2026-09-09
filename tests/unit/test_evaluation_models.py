from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.evaluation import AiCommentaryOutput, EvaluateRequest, RiskFlag


def test_evaluate_request_accepts_valid_payload():
    request = EvaluateRequest.model_validate({"requestId": "r1", "statementDocId": "doc-1"})
    assert request.statement_doc_id == "doc-1"


def test_evaluate_request_statement_doc_id_is_optional():
    request = EvaluateRequest.model_validate({"requestId": "r1"})
    assert request.statement_doc_id is None


def test_evaluate_request_rejects_empty_request_id():
    with pytest.raises(ValidationError):
        EvaluateRequest.model_validate({"requestId": ""})


def test_ai_commentary_output_rejects_empty_summary():
    with pytest.raises(ValidationError):
        AiCommentaryOutput.model_validate({"summary": "", "highlights": []})


def test_ai_commentary_output_has_no_numeric_fields():
    # Structural guarantee, not just a convention: AI cannot supply a
    # number through this schema even if a provider tried to.
    fields = AiCommentaryOutput.model_fields
    assert set(fields) == {"summary", "highlights"}
    assert fields["summary"].annotation is str


def test_risk_flag_requires_field_message_and_severity():
    flag = RiskFlag.model_validate(
        {
            "field": "business.volumeMetrics.monthlyVolume",
            "message": "missing",
            "severity": "MEDIUM",
        }
    )
    assert flag.severity.value == "MEDIUM"


def test_risk_flag_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        RiskFlag.model_validate({"field": "x", "message": "y", "severity": "CATASTROPHIC"})
