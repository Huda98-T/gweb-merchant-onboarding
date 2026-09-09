from __future__ import annotations

from models.evaluation import StatementMetrics
from services import risk_flag_service

BASE_METRICS = StatementMetrics(monthly_volume=50000, current_processing_rate=0.025)


def test_flags_missing_monthly_volume():
    metrics = StatementMetrics(monthly_volume=0, current_processing_rate=0.025)
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=metrics,
        effective_rate=0.025,
        mcc_confirmed=None,
        statement_doc_id=None,
        statement_doc=None,
    )
    fields = {f.field for f in flags}
    assert "business.volumeMetrics.monthlyVolume" in fields


def test_flags_missing_declared_rate():
    metrics = StatementMetrics(monthly_volume=50000, current_processing_rate=None)
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=metrics,
        effective_rate=0.0,
        mcc_confirmed=None,
        statement_doc_id=None,
        statement_doc=None,
    )
    fields = {f.field for f in flags}
    assert "business.volumeMetrics.currentProcessingRate" in fields


def test_flags_high_effective_rate_above_threshold():
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.05,
        mcc_confirmed=None,
        statement_doc_id=None,
        statement_doc=None,
    )
    high_rate_flags = [
        f
        for f in flags
        if f.field == "business.volumeMetrics.currentProcessingRate" and "exceeds" in f.message
    ]
    assert len(high_rate_flags) == 1
    assert high_rate_flags[0].severity.value == "HIGH"


def test_no_high_rate_flag_at_or_below_threshold():
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.04,
        mcc_confirmed=None,
        statement_doc_id=None,
        statement_doc=None,
    )
    assert not any("exceeds" in f.message for f in flags)


def test_flags_missing_confirmed_mcc():
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.025,
        mcc_confirmed=None,
        statement_doc_id=None,
        statement_doc=None,
    )
    assert any(f.field == "mcc.confirmed" for f in flags)


def test_flags_enhanced_review_mcc_and_cites_code_and_reason():
    mcc = {"code": "6211", "riskTier": "ENHANCED_REVIEW", "riskReason": "Securities brokerage"}
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.025,
        mcc_confirmed=mcc,
        statement_doc_id=None,
        statement_doc=None,
    )
    flag = next(f for f in flags if f.field == "mcc.confirmed.riskTier")
    assert "6211" in flag.message
    assert "Securities brokerage" in flag.message
    assert flag.severity.value == "HIGH"


def test_no_mcc_flag_when_confirmed_mcc_is_standard():
    mcc = {"code": "5812", "riskTier": "STANDARD", "riskReason": "No enhanced policy on file."}
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.025,
        mcc_confirmed=mcc,
        statement_doc_id=None,
        statement_doc=None,
    )
    assert not any(f.field.startswith("mcc.confirmed") for f in flags)


def test_flags_missing_statement_document():
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.025,
        mcc_confirmed=None,
        statement_doc_id="doc-1",
        statement_doc=None,
    )
    flag = next(f for f in flags if f.field == "document.doc-1")
    assert flag.severity.value == "HIGH"


def test_flags_statement_document_not_yet_accepted():
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.025,
        mcc_confirmed=None,
        statement_doc_id="doc-1",
        statement_doc={"status": "REQUESTED"},
    )
    flag = next(f for f in flags if f.field == "document.doc-1.status")
    assert "REQUESTED" in flag.message


def test_no_document_flag_when_accepted():
    flags = risk_flag_service.compute_risk_flags(
        statement_metrics=BASE_METRICS,
        effective_rate=0.025,
        mcc_confirmed=None,
        statement_doc_id="doc-1",
        statement_doc={"status": "ACCEPTED"},
    )
    assert not any(f.field.startswith("document.") for f in flags)
