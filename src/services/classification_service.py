"""Deterministic MCC classification (decision #2 — no AI/LLM/embeddings).

Scores every catalog entry with a fixed, documented formula — same input
always produces the same output. Policy-agnostic on purpose (decision #5):
this module knows nothing about risk tiers; mcc_service.py combines its
output with mcc_catalog_service.resolve_risk_tier() to decide
requiresManualReview.

Two distinct signal sources feed the keyword component, and the `reason`
string always says which one fired, so a hand-tuned match and an automatic
one never look identical to a reviewer:
- a curated entry (entry["keywords"] present): matched against a small,
  hand-authored synonym list — reason says "Matched curated keywords: ...".
- an uncurated entry (no "keywords" key): matched against tokens derived
  from the entry's own description (stopword-stripped) — reason says
  "Matched description tokens: ...".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from models.mcc import MccCandidate

_WORD_RE = re.compile(r"[a-z0-9]+")

# Standard English stopwords plus MCC-description boilerplate that would
# otherwise pollute auto-derived tokens (nearly every description contains
# some of these).
_STOPWORDS = {
    "the",
    "and",
    "of",
    "for",
    "a",
    "an",
    "in",
    "on",
    "at",
    "to",
    "is",
    "are",
    "or",
    "not",
    "with",
    "by",
    "this",
    "that",
    "other",
    "elsewhere",
    "classified",
    "nec",
    "services",
    "service",
    "including",
    "only",
    "etc",
}

_KEYWORD_WEIGHT = 0.45
_FUZZY_WEIGHT = 0.35
_EXACT_WEIGHT = 0.20
_DEFAULT_TOP_N = 3


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _normalize(text: str) -> str:
    return " ".join(_tokenize(text))


def _content_tokens(text: str) -> list[str]:
    return [t for t in _tokenize(text) if t not in _STOPWORDS and len(t) > 2]


@dataclass(frozen=True)
class _Scored:
    code: str
    description: str
    confidence: float
    reason: str


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _keyword_match(
    normalized_input: str, input_tokens: set[str], entry: dict
) -> tuple[float, list[str], str]:
    curated = entry.get("keywords")
    if curated:
        hits = [kw for kw in curated if _normalize(kw) in normalized_input]
        score = len(hits) / len(curated) if curated else 0.0
        return score, hits, "curated"

    description_tokens = _content_tokens(entry["description"])
    hits = _dedupe([tok for tok in description_tokens if tok in input_tokens])
    score = len(hits) / len(description_tokens) if description_tokens else 0.0
    return score, hits, "auto"


def _build_reason(
    exact_bonus: float, keyword_hits: list[str], keyword_source: str, fuzzy_score: float
) -> str:
    parts: list[str] = []
    if exact_bonus >= 1.0:
        parts.append("Self-selected activity exactly matches the catalog description")
    elif exact_bonus > 0:
        parts.append("Self-selected activity closely overlaps the catalog description")
    if keyword_hits:
        label = "curated keywords" if keyword_source == "curated" else "description tokens"
        parts.append(f"Matched {label}: {', '.join(keyword_hits)}")
    if not parts:
        parts.append(f"Weak text similarity only (similarity {fuzzy_score:.2f})")
    return "; ".join(parts)


def _score_entry(
    normalized_input: str, input_tokens: set[str], normalized_activity: str, entry: dict
) -> _Scored:
    normalized_description = _normalize(entry["description"])

    keyword_score, keyword_hits, keyword_source = _keyword_match(
        normalized_input, input_tokens, entry
    )
    fuzzy_score = SequenceMatcher(None, normalized_input, normalized_description).ratio()

    if normalized_activity and normalized_activity == normalized_description:
        exact_bonus = 1.0
    elif normalized_activity and (
        normalized_activity in normalized_description
        or normalized_description in normalized_activity
    ):
        exact_bonus = 0.5
    else:
        exact_bonus = 0.0

    raw_score = (
        _KEYWORD_WEIGHT * keyword_score + _FUZZY_WEIGHT * fuzzy_score + _EXACT_WEIGHT * exact_bonus
    )
    confidence = round(min(raw_score, 1.0), 2)
    reason = _build_reason(exact_bonus, keyword_hits, keyword_source, fuzzy_score)
    return _Scored(
        code=entry["code"], description=entry["description"], confidence=confidence, reason=reason
    )


def classify(
    self_selected_activity: str,
    business_description: str | None,
    catalog: list[dict],
    top_n: int = _DEFAULT_TOP_N,
) -> list[MccCandidate]:
    """Deterministic: identical inputs (and an unchanged catalog) always
    produce identical output — no randomness, no external calls."""
    combined = f"{self_selected_activity} {business_description or ''}"
    normalized_input = _normalize(combined)
    input_tokens = set(_tokenize(combined))
    normalized_activity = _normalize(self_selected_activity)

    scored = [
        _score_entry(normalized_input, input_tokens, normalized_activity, entry)
        for entry in catalog
    ]
    scored.sort(key=lambda s: (-s.confidence, s.code))

    top = [s for s in scored if s.confidence > 0][:top_n] or scored[:1]
    return [
        MccCandidate(
            code=s.code, description=s.description, confidence=s.confidence, reason=s.reason
        )
        for s in top
    ]
