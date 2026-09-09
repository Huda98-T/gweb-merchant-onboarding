"""Deterministic rate/fee math — the AI adapter never imports this module
and has no way to set any of these numbers. Pure functions, no I/O.
"""

from __future__ import annotations

from typing import Any

from models.evaluation import StatementMetrics


def build_statement_metrics(business_item: dict[str, Any]) -> StatementMetrics:
    """Derived from BUSINESS.volumeMetrics (Phase 1 data) — never from
    parsing statementDocId's actual bytes (no OCR in this project)."""
    volume_metrics = business_item.get("volumeMetrics") or {}
    return StatementMetrics(
        monthly_volume=float(volume_metrics.get("monthlyVolume") or 0),
        average_ticket=volume_metrics.get("averageTicket"),
        current_processing_rate=volume_metrics.get("currentProcessingRate"),
        transaction_count=volume_metrics.get("transactionCount"),
        per_transaction_fee=volume_metrics.get("perTransactionFee"),
    )


def compute_effective_rate(metrics: StatementMetrics) -> float:
    """effective rate = declared processing rate + per-transaction fees
    amortized over monthly volume. Deterministic; rounded to 4dp (bps)."""
    base_rate = metrics.current_processing_rate or 0.0
    per_tx_component = 0.0
    if metrics.monthly_volume and metrics.per_transaction_fee and metrics.transaction_count:
        per_tx_component = (
            metrics.per_transaction_fee * metrics.transaction_count
        ) / metrics.monthly_volume
    return round(base_rate + per_tx_component, 4)
