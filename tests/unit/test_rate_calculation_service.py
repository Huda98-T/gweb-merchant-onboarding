from __future__ import annotations

from models.evaluation import StatementMetrics
from services import rate_calculation_service


def test_build_statement_metrics_reads_volume_metrics_fields():
    business = {
        "volumeMetrics": {
            "monthlyVolume": 50000,
            "averageTicket": 40,
            "currentProcessingRate": 0.029,
            "transactionCount": 500,
            "perTransactionFee": 0.10,
        }
    }
    metrics = rate_calculation_service.build_statement_metrics(business)
    assert metrics.monthly_volume == 50000
    assert metrics.current_processing_rate == 0.029
    assert metrics.transaction_count == 500


def test_build_statement_metrics_defaults_when_volume_metrics_missing():
    metrics = rate_calculation_service.build_statement_metrics({})
    assert metrics.monthly_volume == 0
    assert metrics.current_processing_rate is None


def test_compute_effective_rate_combines_base_rate_and_per_transaction_fees():
    metrics = StatementMetrics(
        monthly_volume=50000,
        current_processing_rate=0.029,
        transaction_count=500,
        per_transaction_fee=0.10,
    )
    # 0.029 + (0.10 * 500 / 50000) = 0.029 + 0.001 = 0.03
    assert rate_calculation_service.compute_effective_rate(metrics) == 0.03


def test_compute_effective_rate_ignores_per_transaction_component_when_volume_zero():
    metrics = StatementMetrics(
        monthly_volume=0,
        current_processing_rate=0.025,
        transaction_count=10,
        per_transaction_fee=0.10,
    )
    assert rate_calculation_service.compute_effective_rate(metrics) == 0.025


def test_compute_effective_rate_defaults_to_zero_when_no_rate_declared():
    metrics = StatementMetrics(monthly_volume=1000)
    assert rate_calculation_service.compute_effective_rate(metrics) == 0.0


def test_compute_effective_rate_is_deterministic():
    metrics = StatementMetrics(
        monthly_volume=12345,
        current_processing_rate=0.031,
        transaction_count=77,
        per_transaction_fee=0.15,
    )
    first = rate_calculation_service.compute_effective_rate(metrics)
    second = rate_calculation_service.compute_effective_rate(metrics)
    assert first == second
