"""The one clearly pure piece of review_service.py's logic — license
conditionality. Everything else in review_service is exercised via
tests/integration/test_submit_flow.py (it's a DB-orchestrating function,
same testing split Phase 1-4 already use for application_service/mcc_service)."""

from __future__ import annotations

from models.mcc import MccConfirmedView, RiskTier
from services import review_service


def _mcc(tier: RiskTier) -> MccConfirmedView:
    return MccConfirmedView(code="5812", confirmedAt="now", riskTier=tier, riskReason="x")


def test_license_not_required_when_no_confirmed_mcc():
    assert review_service._license_required(None) is False


def test_license_not_required_for_standard_tier():
    assert review_service._license_required(_mcc(RiskTier.STANDARD)) is False


def test_license_required_for_enhanced_review_tier():
    assert review_service._license_required(_mcc(RiskTier.ENHANCED_REVIEW)) is True


def test_license_required_for_restricted_tier():
    assert review_service._license_required(_mcc(RiskTier.RESTRICTED)) is True
