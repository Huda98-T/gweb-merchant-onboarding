# Demo walkthrough

A step-by-step narration of one complete merchant application, from
creation through submission. This is not setup/install instructions
(see [README.md § Running the demo](../README.md#running-the-demo) for
that) — it's an account of the journey itself, using the exact request/
response sequence proven by
[`tests/integration/test_e2e_demo_flow.py::test_full_merchant_onboarding_journey_happy_path`](../tests/integration/test_e2e_demo_flow.py),
so every value below is real and verifiable, not illustrative fiction.
The same sequence is what `ui/index.html` walks a person through by hand.

## 1. Create the application

`POST /applications` with an empty body. The response is the whole
"account" for this application:

```json
{ "applicationId": "<uuid4 hex>", "status": "DRAFT", "version": 1 }
```

`applicationId` doubles as the bearer token from here on
(`X-Application-Token` header) — see SECURITY.md for why.

## 2. Applicant information

`PATCH /applications/{id}/applicant` with one owner/controller:

```json
{
  "requestId": "req-applicant",
  "firstName": "Ada", "lastName": "Lovelace",
  "dob": "1990-01-01",
  "address": { "line1": "1 Main St", "city": "London" },
  "role": "controller", "ownershipPct": 100,
  "idType": "passport", "idLast4": "1234",
  "consentVersion": "v1"
}
```

Response: `200 { "personId": "<id>", "version": 2 }` — `META.version` just
incremented, the optimistic-concurrency counter for this application.

## 3. Business information

`PATCH /applications/{id}/business`, including the volume/rate figures
the deterministic evaluation step reads later:

```json
{
  "requestId": "req-business",
  "legalName": "Ada's Bakery LLC", "entityType": "LLC",
  "registrationId": "EIN-123456",
  "addresses": { "business": { "line1": "1 Main St" } },
  "volumeMetrics": {
    "monthlyVolume": 50000, "currentProcessingRate": 0.029,
    "transactionCount": 500, "perTransactionFee": 0.10
  }
}
```

## 4. Documents — three required types

For each of `GOVERNMENT_ID`, `BUSINESS_REGISTRATION`, `BANK_EVIDENCE`:

1. `POST /applications/{id}/documents/presign` → `{ documentId, uploadUrl, s3Key, expiresIn: 300 }`.
2. The client `PUT`s the file bytes **directly to `uploadUrl`** — this
   request never touches Lambda or API Gateway at all.
3. `POST /applications/{id}/documents/{documentId}/complete` → the server
   HEADs the object, streams it once to check the magic bytes and compute
   a real SHA-256, and responds:
   ```json
   { "documentId": "<id>", "status": "ACCEPTED", "checksumSha256": "<real sha256 hex>" }
   ```

## 5. Business activity → MCC classification

`POST /applications/{id}/classify`:

```json
{ "requestId": "req-classify", "selfSelectedActivity": "Restaurant", "businessDescription": "Neighborhood bakery and cafe" }
```

Top candidate comes back as **MCC 5812 — Eating places and Restaurants**,
deterministically (keyword + fuzzy match against the packaged catalog, no
AI/LLM anywhere in this step).

## 6. Confirm the MCC

`POST /applications/{id}/mcc/confirm` with `{ "requestId": "req-confirm", "code": "5812" }`
→ `{ "code": "5812", "riskTier": "STANDARD", "requiresManualReview": false }`.

## 7. Run the evaluation

`POST /applications/{id}/evaluate` with `{ "requestId": "req-evaluate" }`.
The response separates deterministic numbers from AI text explicitly:

```json
{
  "status": "COMPLETE",
  "effectiveRate": 0.03,
  "statementMetrics": { "monthlyVolume": 50000, ... },
  "aiCommentary": { "summary": "This business is classified as MCC 5812 ...", "highlights": [] },
  "riskFlags": []
}
```

`0.029` declared rate + `(0.10 × 500) / 50000` per-transaction component =
`0.03` — pure Python arithmetic (`rate_calculation_service.py`); the AI
adapter only narrates numbers it was handed, it never computes one.

## 8. Review

`GET /applications/{id}/review` — the same readiness computation `submit`
will use, available beforehand so nothing is a surprise:

```json
{ "ready": true, "blockingIssues": [], "mcc": { "confirmed": { "code": "5812" } }, ... }
```

## 9. Submit

`POST /applications/{id}/submit` with `{ "requestId": "req-submit" }` →
`{ "status": "SUBMITTED", "reviewPayload": { ... } }`. `META.status`
transitions `DRAFT` → `SUBMITTED` atomically with persisting the
normalized downstream payload (`SK = SUBMISSION`) — see
[docs/architecture.md](architecture.md) for the concurrency mechanics.

## 10. Confirm the final state

`GET /applications/{id}` now shows the whole picture in one call:
`meta.status = "SUBMITTED"`, `evaluation.status = "COMPLETE"`,
`mcc.confirmed.code = "5812"`.

---

**The one blocking-path variant worth knowing**: the same test file's
`test_critical_blocking_path_missing_documents_and_mcc_blocks_submission`
runs steps 1-3 only, then calls submit directly — it comes back `400`
with `missingItems` naming `DOCUMENT_MISSING`, `MCC_NOT_CONFIRMED`, and
`EVALUATION_INCOMPLETE`, and the application is confirmed to still be
`DRAFT` afterward. Submission is never partially applied.
