# Security notes

This is a graded prototype, not a production system. This document states
what's actually implemented, what's a deliberate/accepted gap, and what a
real deployment would need to add.

## Authentication / authorization

**No real auth.** The server-generated `applicationId` (a `uuid4().hex`,
122 bits of entropy) doubles as the bearer token
(`X-Application-Token` header must equal the path `{id}`,
`src/common/auth.py`). Anyone who has the ID has full read/write access to
that application. This is a deliberate, documented Phase 1 decision (not
an oversight) — building real auth (Cognito/JWT) wasn't judged worth the
budget for a prototype scored on architecture, not auth depth. Production
fix: Cognito or equivalent, with the applicationId no longer doubling as a
credential.

`GET /mcc?query=` and `POST /applications` are the only unauthenticated
routes — the former is public reference data, the latter has nothing to
authenticate against yet (see `POST /applications` idempotency note in
the spec — a create has nothing to check ownership of).

## IAM

Every one of the 13 Lambda functions has its own least-privilege policy
(`template.yaml`) — no shared broad role, no `Action: "*"` or
`Resource: "*"` anywhere in the template. Concretely:
- `SearchMccFunction` has **no IAM policy at all** — the catalog is a
  packaged file, not an AWS resource.
- Every DynamoDB-touching function gets exactly the actions it uses
  (`GetItem`/`Query`/`PutItem`/`UpdateItem` — never a blanket
  `dynamodb:*`), scoped to the one table's ARN.
- `PresignDocumentFunction`/`CompleteDocumentFunction` get `s3:PutObject`/
  `s3:GetObject` respectively, scoped to the `applications/*/documents/*`
  key prefix — never bucket-wide, never both actions on one function.

## Data at rest

- DynamoDB: AWS-owned-key encryption (the default; no `SSESpecification`
  block needed to get it). No customer-managed KMS key — documented as a
  "would use in production" tradeoff (spec §5.6), not implemented, to keep
  the prototype's setup surface small.
- S3: `SSEAlgorithm: AES256` explicitly configured, `PublicAccessBlockConfiguration`
  fully enabled (all four flags `true`), no bucket policy. The only way in
  is a presigned URL Lambda generates using its own scoped IAM permission.
- S3 bucket **does** have a `CorsConfiguration` (added Phase 6) — required
  for the direct browser→S3 presigned PUT to work cross-origin at all
  (found missing during the Phase 6 security pass; fixed). Scoped to
  `PUT` only, not the whole S3 API.

## Documents / PII

- Document **bytes never touch DynamoDB or Lambda's own execution beyond
  a streaming read for verification** — presigned PUT direct to S3,
  presigned-URL-generation-only on the way in, one `GetObject` stream
  (checksum + magic-byte check) on the way out. See
  `src/adapters/storage/s3_client.py`.
- No PAN/CVV concept exists anywhere in this system — the data model has
  no payment-card fields at all (government ID/business docs only).
- `common/logger.py` redacts a fixed field-name list (`dob`, `address`,
  `idLast4`, `firstName`, `lastName`, `checksum`, `uploadUrl`/`presignedUrl`,
  ...) out of any structured log payload before it's written.
- **Pydantic validation-error responses/logs** (Phase 6 fix): Pydantic's
  `ValidationError.errors()` includes the raw submitted value verbatim
  (`input` key) for every failing field — for PII-bearing models
  (applicant dob/address/idLast4, etc.) that meant a malformed request
  would echo the actual submitted value into both the 400 response *and*
  the log line. `common/errors.py` now strips `input`/`url` from every
  validation error before it's logged or returned; see
  `test_handle_errors_strips_raw_submitted_value_from_validation_errors`.
- AI input allowlist (`AiCommentaryContext`, Phase 4): MCC code/
  description, risk tier, computed effective rate, monthly volume, and
  risk-flag *messages* only. Never `personId`/`dob`/`address`/`idLast4`/
  checksums/raw document bytes — `AiCommentaryOutput` itself has no
  numeric fields at all, so the model literally cannot return a number.
- AI output is never trusted as-is: every adapter response is re-validated
  against a strict schema; malformed output falls back to a fixed safe
  string rather than surfacing whatever the model actually returned.
- Normalized submission payload (`SubmissionItem`, Phase 5) — persisted,
  never returned by any API response — carries document *metadata*
  (`documentId`, `s3Key`, `checksumSha256`) for downstream processor
  integration, never bytes/content.

## Input validation

Every request body is a Pydantic model with explicit constraints
(`min_length`, `max_length`, numeric ranges, enum membership) — validated
at the API boundary before any business logic runs, satisfying
defense-in-depth even though HTTP API v2 (chosen over REST API v1) has no
native gateway-level JSON-Schema validation.

## AI-specific

- Mock-only adapter (`MockAiProvider`) — no real LLM/network call exists
  in this codebase (decision #2, Phase 4).
- Every AI call is wrapped in a hard timeout
  (`concurrent.futures.ThreadPoolExecutor` + `future.result(timeout=...)`,
  `evaluation_service._call_ai_with_timeout`) so a hung/slow provider
  can't blow the 45-second Lambda budget — see
  `test_evaluate_hanging_ai_call_times_out_within_budget_and_persists_failed`.
- Deterministic numbers (rate/fee math, risk flags) are computed in plain
  Python (`rate_calculation_service.py`, `risk_flag_service.py`) *before*
  the AI adapter is ever called, and the AI's output schema has no numeric
  fields — structurally, not just by convention, AI cannot set a number.

## Secrets / credentials

No secrets, API keys, or credentials are committed anywhere in this repo
(verified by grep as part of the Phase 6 pass). `scripts/run_local_demo.py`
uses an obviously-fake local credential pair (`local-demo`/`local-demo`)
purely to satisfy boto3's "some credentials must be present" requirement
when talking to the local moto emulator — it is not a real AWS credential
and grants no access to anything real.

## Known gaps (accepted for this prototype)

- No WAF / rate limiting / usage plans (explicit HTTP-API-vs-REST-API
  tradeoff, spec §1.2).
- No customer-managed KMS key (spec §5.6).
- No queue-based retry/dead-letter handling for `/evaluate`'s async path
  (spec §1.3 — explicitly a bonus differentiator, not required).
- No upload-time size *enforcement* on the presigned PUT (Phase 2 —
  rejected an unverifiable `ContentLength`-locking technique rather than
  ship it with fake test coverage; actual size is fully enforced
  post-upload before `ACCEPTED`).
- No provider-specific risk-policy override wired to a real per-merchant
  provider field yet (`resolve_risk_tier`'s `provider` param is
  implemented and tested, but `confirm_mcc` always passes `"default"` —
  Phase 3 decision, since Phase 1's `existingProcessor` field has no
  defined shape to reliably derive a provider key from).
