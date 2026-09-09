#!/usr/bin/env python3
"""Build src/data/mcc_catalog.json from a locally-downloaded copy of
greggles/mcc-codes' mcc_codes.csv.

This script does NOT fetch anything over the network itself — the
application (and this build step) must never depend on GitHub at runtime
or at build time. Download the CSV yourself first:

    curl -sS -o mcc_codes.csv \\
        https://raw.githubusercontent.com/greggles/mcc-codes/main/mcc_codes.csv

Then run:

    python3 scripts/build_mcc_catalog.py mcc_codes.csv src/data/mcc_catalog.json

See src/data/MCC_PROVENANCE.md for the source commit, retrieval date, and
verification (row count / SHA-256) recorded for the copy currently checked
into this repo.

`description` is copied verbatim from the upstream `edited_description`
column, including any upstream typos (e.g. MCC 4111 reads "Feries", not
"Ferries" — not corrected here; see MCC_PROVENANCE.md). `category` is a
self-derived range grouping (NOT sourced from upstream — greggles/mcc-codes
has no category column). `keywords` is present only for a curated subset of
high-relevance codes (see CURATED_KEYWORDS below); every other entry has no
`keywords` key, and the classification service derives fallback tokens from
`description` itself at runtime instead.
"""

from __future__ import annotations

import csv
import json
import sys

# Self-derived, non-overlapping range -> category grouping. Not sourced
# from upstream data; a display/search convenience only.
CATEGORY_RANGES: list[tuple[int, int, str]] = [
    (0, 1499, "Agricultural Services"),
    (1500, 2999, "Contracted Services"),
    (3000, 3299, "Airlines"),
    (3300, 3499, "Car Rental"),
    (3500, 3999, "Lodging"),
    (4000, 4799, "Transportation"),
    (4800, 4999, "Utilities"),
    (5000, 5599, "Retail Stores"),
    (5600, 5699, "Clothing Stores"),
    (5700, 5999, "Miscellaneous Stores"),
    (6000, 6999, "Financial Institutions and Services"),
    (7000, 7299, "Hotels and Lodging Services"),
    (7300, 7529, "Automobile Rental and Services"),
    (7530, 7799, "Repair Services"),
    (7800, 7999, "Amusement and Entertainment"),
    (8000, 8999, "Professional Services and Membership Organizations"),
    (9000, 9999, "Government Services"),
]


def derive_category(code: str) -> str:
    n = int(code)
    for low, high, label in CATEGORY_RANGES:
        if low <= n <= high:
            return label
    return "Uncategorized"


# Hand-authored keyword synonyms for a curated subset of high-relevance
# codes (common onboarding categories + the 3 assessment-mandated codes).
# Every other catalog entry falls back to description-derived tokens at
# classification time (see classification_service.py) — never invented
# here for codes not reviewed by a person.
CURATED_KEYWORDS: dict[str, list[str]] = {
    "5812": ["restaurant", "dining", "eatery", "food service", "cafe", "diner"],
    "5813": ["bar", "pub", "tavern", "nightclub", "lounge", "alcohol"],
    "5411": ["grocery", "supermarket", "market", "food store"],
    "5541": ["gas station", "fuel", "petrol", "service station"],
    "5300": ["wholesale", "club store", "bulk"],
    "5651": ["clothing", "apparel", "fashion", "garment"],
    "5732": ["electronics", "gadgets", "computer store"],
    "5912": ["pharmacy", "drugstore", "medication", "drug store"],
    "5941": ["sporting goods", "sports equipment"],
    "5944": ["jewelry", "jeweler", "watches"],
    "5977": ["cosmetics", "beauty", "makeup"],
    "7011": ["hotel", "motel", "resort", "lodging", "inn", "accommodation"],
    "4511": ["airline", "flight", "air travel", "air carrier"],
    "4121": ["taxi", "cab", "rideshare", "limousine"],
    "4899": ["cable", "satellite tv", "streaming", "pay tv"],
    "4900": ["utility", "electric", "water", "gas utility", "sanitary"],
    "6012": ["financial institution", "bank services", "debt repayment"],
    "6051": [
        "money order", "foreign currency", "currency exchange",
        "travelers cheque", "quasi cash", "cryptocurrency",
    ],
    "6211": ["broker", "brokerage", "securities", "investment", "stock trading", "dealer"],
    "6300": ["insurance", "underwriting", "policy"],
    "8011": ["doctor", "physician", "medical", "clinic"],
    "8021": ["dentist", "dental", "orthodontist"],
    "8041": ["chiropractor"],
    "8062": ["hospital", "medical center"],
    "8111": ["lawyer", "attorney", "legal services", "law firm"],
    "8220": ["college", "university", "education"],
    "8299": ["school", "education", "tutoring"],
    "8351": ["daycare", "child care", "babysitting"],
    "8398": ["charity", "nonprofit", "social service"],
    "8641": ["civic organization", "fraternal", "social club"],
    "8699": ["membership", "association", "club"],
    "8931": ["accounting", "bookkeeping", "audit", "cpa"],
    "8999": ["professional services", "consulting"],
    "7230": ["barber", "salon", "beauty shop", "hair"],
    "7298": ["spa", "wellness", "massage"],
    "7311": ["advertising", "marketing", "agency"],
    "7372": ["software", "programming", "it services", "data processing"],
    "7392": ["consulting", "management services", "public relations"],
    "7399": ["business services"],
    "7538": ["auto repair", "mechanic", "car service"],
    "5511": ["car dealer", "auto dealer", "vehicle sales"],
    "5521": ["used car dealer"],
    "5013": ["auto parts", "car parts"],
    "4814": ["telecom", "phone service", "internet service"],
    "5045": ["computer store", "software", "peripherals"],
    "5734": ["software store", "computer software"],
    "5943": ["stationery", "office supplies"],
    "5992": ["florist", "flowers"],
    "9311": ["tax payment", "government tax"],
    "9399": ["government services"],
    "9402": ["postal service", "mail", "government post"],
}


def build_catalog(csv_path: str) -> list[dict]:
    entries = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row["mcc"].strip()
            entry = {
                "code": code,
                "description": row["edited_description"].strip(),
                "category": derive_category(code),
            }
            if code in CURATED_KEYWORDS:
                entry["keywords"] = CURATED_KEYWORDS[code]
            entries.append(entry)
    entries.sort(key=lambda e: e["code"])
    return entries


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <input mcc_codes.csv> <output mcc_catalog.json>", file=sys.stderr)
        raise SystemExit(2)
    catalog = build_catalog(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write("\n")
    unmatched_curated = set(CURATED_KEYWORDS) - {e["code"] for e in catalog}
    print(f"Wrote {len(catalog)} entries to {sys.argv[2]}")
    print(f"Curated keyword entries: {sum(1 for e in catalog if 'keywords' in e)}")
    if unmatched_curated:
        print(f"WARNING: curated codes not found in source data: {sorted(unmatched_curated)}", file=sys.stderr)


if __name__ == "__main__":
    main()
