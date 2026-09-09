"""Deterministic risk flags — never AI-generated (AI only narrates these
in aiCommentary.highlights, it never authors a flag). Every flag cites the
real field/document that triggered it.
"""

from __future__ import annotations

from typing import Any

from models.evaluation import RiskFlag, RiskSeverity, StatementMetrics

HIGH_EFFECTIVE_RATE_THRESHOLD = 0.04  # 4%


def compute_risk_flags(
    *,
    statement_metrics: StatementMetrics,
    effective_rate: float,
    mcc_confirmed: dict[str, Any] | None,
    statement_doc_id: str | None,
    statement_doc: dict[str, Any] | None,
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []

    if statement_metrics.monthly_volume <= 0:
        flags.append(
            RiskFlag(
                field="business.volumeMetrics.monthlyVolume",
                message="Monthly volume is missing or zero.",
                severity=RiskSeverity.MEDIUM,
            )
        )
    if statement_metrics.current_processing_rate is None:
        flags.append(
            RiskFlag(
                field="business.volumeMetrics.currentProcessingRate",
                message="Declared processing rate is missing.",
                severity=RiskSeverity.MEDIUM,
            )
        )
    if effective_rate > HIGH_EFFECTIVE_RATE_THRESHOLD:
        flags.append(
            RiskFlag(
                field="business.volumeMetrics.currentProcessingRate",
                message=(
                    f"Effective rate {effective_rate:.2%} exceeds the "
                    f"{HIGH_EFFECTIVE_RATE_THRESHOLD:.0%} review threshold."
                ),
                severity=RiskSeverity.HIGH,
            )
        )

    if mcc_confirmed is None:
        flags.append(
            RiskFlag(
                field="mcc.confirmed",
                message="No confirmed MCC on file.",
                severity=RiskSeverity.MEDIUM,
            )
        )
    elif mcc_confirmed.get("riskTier") != "STANDARD":
        flags.append(
            RiskFlag(
                field="mcc.confirmed.riskTier",
                message=(
                    f"MCC {mcc_confirmed.get('code')} is under enhanced review: "
                    f"{mcc_confirmed.get('riskReason')}"
                ),
                severity=RiskSeverity.HIGH,
            )
        )

    if statement_doc_id:
        if statement_doc is None:
            flags.append(
                RiskFlag(
                    field=f"document.{statement_doc_id}",
                    message="Referenced statement document was not found.",
                    severity=RiskSeverity.HIGH,
                )
            )
        elif statement_doc.get("status") != "ACCEPTED":
            flags.append(
                RiskFlag(
                    field=f"document.{statement_doc_id}.status",
                    message=(
                        f"Statement document status is {statement_doc.get('status')}, not ACCEPTED."
                    ),
                    severity=RiskSeverity.MEDIUM,
                )
            )

    return flags
