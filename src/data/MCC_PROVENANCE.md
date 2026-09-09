# MCC catalog provenance

`mcc_catalog.json` is a packaged, static file. **The application never
fetches it, or anything else, from GitHub (or any other external source) at
runtime or at build time.** It is generated once, offline, by
`scripts/build_mcc_catalog.py`, and the generated JSON is what's committed
and deployed.

## Source

- Upstream repository: [greggles/mcc-codes](https://github.com/greggles/mcc-codes) — a community-maintained,
  public-domain-ish collection of Merchant Category Codes. **This is not an
  official Visa dataset** and is not affiliated with Visa, Mastercard, or
  any card network. It is used here because it packages MCC data in a
  machine-readable format (CSV/JSON) rather than only as a PDF.
- File used: `mcc_codes.csv`
- Commit: [`df792275c567946119a8903d36dbd33e44a248bf`](https://github.com/greggles/mcc-codes/commit/df792275c567946119a8903d36dbd33e44a248bf) (2024-08-16T14:34:46Z)
- Retrieved: 2026-09-09, via direct `curl` download of
  `https://raw.githubusercontent.com/greggles/mcc-codes/main/mcc_codes.csv`
  (not through any summarization/AI-fetching tool, to avoid transcription
  risk on a data-integrity-sensitive dataset).

## Verification performed at retrieval time

- Row count: 981 data rows (via `csv.DictReader`, not a naive line count).
- Zero duplicate MCC codes.
- Code range: 0742–9950.
- SHA-256 of the downloaded `mcc_codes.csv`:
  `1870af6f01a7b5fa4f89d597f70b3f2481e063e9470549e3a16405f748cb1f9d`
- Independently re-confirmed the commit SHA via a second, separate method
  (direct `curl` to the GitHub REST API) — both methods agreed exactly.
- Individually spot-checked MCC 6012, 6051, and 6211 (see below) against a
  general web search of Visa MCC references before trusting the upstream
  file, specifically because an earlier, less careful pass had assumed 6012
  was "quasi-cash" — it is not; 6051 is.

## Fields and how each is derived

| Field | Source |
|---|---|
| `code` | Upstream `mcc` column, verbatim |
| `description` | Upstream `edited_description` column, **verbatim, including upstream typos** — see below. Not the `combined_description`, `usda_description`, or `irs_description` columns. |
| `category` | **Not from upstream** — greggles/mcc-codes has no category column. Self-derived by `scripts/build_mcc_catalog.py` from a simple, non-overlapping MCC-range grouping (e.g. 5000–5599 → "Retail Stores"). This is a display/search convenience, not a sourced classification. |
| `keywords` | **Not from upstream.** Present only on a curated subset (~50 codes) of hand-authored synonyms for common onboarding categories and the three assessment-mandated codes (6012/6051/6211). Every other entry has no `keywords` key; the classification service derives fallback tokens from `description` itself at runtime instead (stopword-stripped tokenization) — see `classification_service.py`. |

## Known upstream data issue — preserved, not corrected

MCC 4111's upstream `edited_description` reads:

> Local/Suburban Commuter Passenger Transportation – Railroads, **Feries**, Local Water Transportation.

This is an upstream typo ("Feries" instead of "Ferries"). It is preserved
**verbatim** in `mcc_catalog.json` rather than silently corrected, so the
packaged data always matches its cited source exactly and can be
independently re-verified against it. This is a deliberate choice: editing
source data without flagging it would make the provenance claim untrustworthy.

## MCC 6012 / 6051 / 6211 — verified against a Visa MCC reference

These three descriptions were checked against upstream **and** against a
general search of Visa merchant category code references before being
marked `ENHANCED_REVIEW` in `risk_policy.json`, specifically to avoid
mislabeling — 6012 is a financial-institution merchandise/services code,
**not** quasi-cash; 6051 is the actual quasi-cash code (foreign currency,
money orders, travelers cheques).

| Code | Description (verbatim, upstream) |
|---|---|
| 6012 | Financial Institutions – Merchandise and Services |
| 6051 | Non-Financial Institutions – Foreign Currency, Money Orders (not wire transfer) and Travelers Cheques |
| 6211 | Security Brokers/Dealers |

## Refreshing the catalog

1. Download a fresh copy yourself (this repo does not automate this —
   automatic catalog refresh is explicitly out of scope for this phase):
   ```
   curl -sS -o mcc_codes.csv https://raw.githubusercontent.com/greggles/mcc-codes/main/mcc_codes.csv
   ```
2. Regenerate: `python3 scripts/build_mcc_catalog.py mcc_codes.csv src/data/mcc_catalog.json`
3. Update the commit SHA, retrieval date, row count, and SHA-256 in this
   file to match the new download, and re-verify 6012/6051/6211 didn't
   change meaning before trusting the new file.

## Known limitation

Risk policy provider overrides (`risk_policy.json`'s per-provider keys) are
implemented and unit-tested, but nothing in the application currently
selects a non-`"default"` provider — `confirm_mcc` always resolves against
`"default"`. Business records carry an opaque `existingProcessor` field
(Phase 1) that could plausibly map to a provider in a future phase, but no
convention for that mapping exists yet, and inventing one now was judged
riskier than leaving it as a documented gap.
