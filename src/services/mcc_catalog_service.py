"""Loads and searches the packaged MCC catalog and risk policy.

Both are static files under src/data/ (see MCC_PROVENANCE.md) — loaded
once per Lambda container (module-level cache) and never fetched over the
network, matching decision #3/#5. No DynamoDB access here at all.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from models.mcc import CatalogSearchResult, RiskTier

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CATALOG_PATH = _DATA_DIR / "mcc_catalog.json"
_RISK_POLICY_PATH = _DATA_DIR / "risk_policy.json"

_DEFAULT_PROVIDER = "default"
_MAX_SEARCH_RESULTS = 25


@lru_cache(maxsize=1)
def all_entries() -> list[dict]:
    """The full loaded catalog, in file order — e.g. for classification_service."""
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _catalog_by_code() -> dict[str, dict]:
    return {entry["code"]: entry for entry in all_entries()}


@lru_cache(maxsize=1)
def _risk_policy() -> dict[str, dict]:
    with open(_RISK_POLICY_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_entry(code: str) -> dict | None:
    return _catalog_by_code().get(code)


def search(query: str) -> list[CatalogSearchResult]:
    """Exact code match first, then description-substring position, then
    the rest by catalog order. Deterministic — no fuzzy matching here
    (that's classification_service's job); this is a literal search."""
    normalized = query.strip().lower()
    if not normalized:
        return []

    exact_code = _catalog_by_code().get(query.strip())
    scored: list[tuple[int, dict]] = []
    for entry in all_entries():
        if exact_code is not None and entry["code"] == exact_code["code"]:
            continue
        position = entry["description"].lower().find(normalized)
        if position >= 0:
            scored.append((position, entry))
    scored.sort(key=lambda pair: (pair[0], pair[1]["code"]))

    ordered = ([exact_code] if exact_code is not None else []) + [e for _, e in scored]
    return [
        CatalogSearchResult(code=e["code"], description=e["description"], category=e["category"])
        for e in ordered[:_MAX_SEARCH_RESULTS]
    ]


def resolve_risk_tier(code: str, provider: str = _DEFAULT_PROVIDER) -> tuple[RiskTier, str]:
    """Provider-specific override wins over `default`; codes with no entry
    in either resolve to the implicit STANDARD tier."""
    policy = _risk_policy()
    override = policy.get(provider, {}).get(code)
    if override is not None:
        return RiskTier(override["tier"]), override["reason"]

    default_entry = policy.get(_DEFAULT_PROVIDER, {}).get(code)
    if default_entry is not None:
        return RiskTier(default_entry["tier"]), default_entry["reason"]

    return RiskTier.STANDARD, "No enhanced policy on file for this MCC."
