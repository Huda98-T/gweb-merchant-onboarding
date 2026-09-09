"""Catalog + risk policy loading/search/resolution (decisions #3/#4/#5).
No DynamoDB — the catalog and policy are packaged files."""

from __future__ import annotations

from models.mcc import RiskTier
from services import mcc_catalog_service


def test_catalog_loads_full_verified_dataset():
    entries = mcc_catalog_service.all_entries()
    assert len(entries) == 981
    codes = [e["code"] for e in entries]
    assert len(codes) == len(set(codes))  # no duplicates


def test_get_entry_returns_verified_descriptions_for_mandatory_codes():
    assert mcc_catalog_service.get_entry("6012")["description"] == (
        "Financial Institutions – Merchandise and Services"
    )
    assert mcc_catalog_service.get_entry("6051")["description"] == (
        "Non-Financial Institutions – Foreign Currency, Money Orders "
        "(not wire transfer) and Travelers Cheques"
    )
    assert mcc_catalog_service.get_entry("6211")["description"] == "Security Brokers/Dealers"


def test_get_entry_returns_none_for_unknown_code():
    assert mcc_catalog_service.get_entry("0000") is None


def test_upstream_typo_preserved_verbatim_not_corrected():
    # MCC 4111 — deliberately not "fixed" locally; see MCC_PROVENANCE.md.
    assert "Feries" in mcc_catalog_service.get_entry("4111")["description"]


def test_search_matches_by_description_substring_case_insensitively():
    results = mcc_catalog_service.search("RESTAURANT")
    codes = {r.code for r in results}
    assert "5812" in codes


def test_search_matches_by_exact_code():
    results = mcc_catalog_service.search("6211")
    assert results[0].code == "6211"


def test_search_returns_empty_list_for_empty_query():
    assert mcc_catalog_service.search("") == []
    assert mcc_catalog_service.search("   ") == []


def test_search_caps_results():
    # A very common substring should still be capped, not dump the catalog.
    results = mcc_catalog_service.search("services")
    assert len(results) <= 25


def test_resolve_risk_tier_marks_all_three_mandatory_codes_enhanced_review():
    for code in ("6012", "6051", "6211"):
        tier, reason = mcc_catalog_service.resolve_risk_tier(code)
        assert tier == RiskTier.ENHANCED_REVIEW
        assert reason  # non-empty, explainable


def test_resolve_risk_tier_6012_reason_does_not_mislabel_as_quasi_cash():
    _, reason = mcc_catalog_service.resolve_risk_tier("6012")
    assert "quasi" not in reason.lower()


def test_resolve_risk_tier_6051_reason_mentions_quasi_cash():
    _, reason = mcc_catalog_service.resolve_risk_tier("6051")
    assert "quasi-cash" in reason.lower()


def test_resolve_risk_tier_defaults_to_standard_for_unlisted_code():
    tier, _ = mcc_catalog_service.resolve_risk_tier("5812")
    assert tier == RiskTier.STANDARD


def test_resolve_risk_tier_provider_override_wins_over_default(monkeypatch):
    synthetic_policy = {
        "default": {"6211": {"tier": "ENHANCED_REVIEW", "reason": "default reason"}},
        "acme-processor": {"6211": {"tier": "RESTRICTED", "reason": "acme-specific reason"}},
    }
    monkeypatch.setattr(mcc_catalog_service, "_risk_policy", lambda: synthetic_policy)
    tier, reason = mcc_catalog_service.resolve_risk_tier("6211", provider="acme-processor")
    assert tier == RiskTier.RESTRICTED
    assert reason == "acme-specific reason"


def test_resolve_risk_tier_unknown_provider_falls_back_to_default(monkeypatch):
    synthetic_policy = {
        "default": {"6211": {"tier": "ENHANCED_REVIEW", "reason": "default reason"}}
    }
    monkeypatch.setattr(mcc_catalog_service, "_risk_policy", lambda: synthetic_policy)
    tier, reason = mcc_catalog_service.resolve_risk_tier("6211", provider="unknown-processor")
    assert tier == RiskTier.ENHANCED_REVIEW
    assert reason == "default reason"
