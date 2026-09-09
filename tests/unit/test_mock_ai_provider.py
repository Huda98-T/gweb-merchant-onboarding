from __future__ import annotations

from adapters.ai.mock_provider import MockAiProvider
from models.evaluation import AiCommentaryContext, AiCommentaryOutput

CONTEXT = AiCommentaryContext(
    mcc_code="5812",
    mcc_description="Eating places and Restaurants",
    risk_tier="STANDARD",
    effective_rate=0.03,
    monthly_volume=50000,
    risk_flag_messages=["Some flag message."],
)


def test_generate_commentary_returns_dict_validating_against_strict_schema():
    raw = MockAiProvider().generate_commentary(CONTEXT)
    validated = AiCommentaryOutput.model_validate(raw)
    assert validated.summary


def test_generate_commentary_is_deterministic():
    first = MockAiProvider().generate_commentary(CONTEXT)
    second = MockAiProvider().generate_commentary(CONTEXT)
    assert first == second


def test_generate_commentary_never_invents_a_number_not_in_context():
    raw = MockAiProvider().generate_commentary(CONTEXT)
    assert "3.00%" in raw["summary"]  # echoes context.effective_rate, doesn't compute its own
    assert "50,000" in raw["summary"]


def test_generate_commentary_highlights_are_exactly_the_provided_risk_flag_messages():
    raw = MockAiProvider().generate_commentary(CONTEXT)
    assert raw["highlights"] == ["Some flag message."]


def test_generate_commentary_handles_no_confirmed_mcc():
    context = CONTEXT.model_copy(update={"mcc_code": None, "mcc_description": None})
    raw = MockAiProvider().generate_commentary(context)
    assert "no confirmed MCC" in raw["summary"]
