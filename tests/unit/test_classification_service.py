"""Deterministic classification algorithm (decision #2 — no AI/LLM)."""

from __future__ import annotations

from services import classification_service, mcc_catalog_service

CATALOG = mcc_catalog_service.all_entries()


def test_classify_is_deterministic_across_repeated_calls():
    first = classification_service.classify("Restaurant", "Pizza and pasta dine-in", CATALOG)
    second = classification_service.classify("Restaurant", "Pizza and pasta dine-in", CATALOG)
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]


def test_classify_always_returns_at_least_one_candidate_even_for_gibberish():
    candidates = classification_service.classify("zzxxqqxxzz asdkfjalsd", None, CATALOG)
    assert len(candidates) >= 1


def test_classify_confidence_is_always_within_zero_to_one():
    for activity in ["Restaurant", "gibberish text zzz", "Veterinary Services", ""]:
        for c in classification_service.classify(activity or "unspecified", None, CATALOG):
            assert 0.0 <= c.confidence <= 1.0


def test_classify_exact_match_yields_top_confidence_and_nonempty_reason():
    candidates = classification_service.classify("Veterinary Services", None, CATALOG)
    top = candidates[0]
    assert top.code == "0742"
    assert top.confidence == 1.0
    assert top.reason


def test_classify_curated_code_reason_says_curated_keywords():
    candidates = classification_service.classify("Restaurant serving pizza", None, CATALOG)
    top = candidates[0]
    assert top.code == "5812"
    assert "curated keywords" in top.reason


def test_classify_uncurated_code_reason_says_description_tokens_not_curated():
    # 0742 (Veterinary Services) has no curated keyword entry.
    candidates = classification_service.classify("Veterinary Services", None, CATALOG)
    top = candidates[0]
    assert top.code == "0742"
    assert "description tokens" in top.reason
    assert "curated keywords" not in top.reason


def test_classify_results_are_sorted_by_descending_confidence():
    candidates = classification_service.classify("Restaurant dining", "pizza pasta", CATALOG)
    confidences = [c.confidence for c in candidates]
    assert confidences == sorted(confidences, reverse=True)


def test_classify_returns_at_most_top_n():
    candidates = classification_service.classify("Restaurant", "food", CATALOG, top_n=2)
    assert len(candidates) <= 2


def test_classify_business_description_none_does_not_error():
    candidates = classification_service.classify("Restaurant", None, CATALOG)
    assert len(candidates) >= 1
