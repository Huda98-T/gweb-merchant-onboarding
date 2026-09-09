# Architecture

See [GWEB_Implementation_Spec.md](../GWEB_Implementation_Spec.md) for the
original decision-by-decision rationale this was built from. This
document is the as-built picture after all six phases.

## Component map

```
Client (ui/index.html, or any HTTP client)
  │
  ├── HTTPS ──▶ API Gateway (HTTP API v2)
  │                  │
  │                  ▼
  │            13 Lambda handlers (Python 3.12, one per route)
  │                  │
  │        ┌─────────┼─────────────┐
  │        ▼         ▼             ▼
  │   DynamoDB     S3 (via      AiProvider
  │   (single       presigned    (mock, deterministic,
  │    table)       URLs)         timeout-bound)
  │
  └── PUT (direct) ──▶ S3 (document bytes never pass through Lambda)
```

## Request flow (every handler, same shape)

```
handler(event, context)
  → common.auth.require_application_token   (except POST /applications, GET /mcc)
  → <Request>.model_validate(parse_json_body(event))   (Pydantic — 400 on failure)
  → services.<x>_service.<function>(...)               (business logic, no boto3 calls)
      → adapters.db.dynamo_client / adapters.storage.s3_client / adapters.ai.*
  → build_response(status_code, response.model_dump(by_alias=True))
```

Every handler is wrapped in `common.errors.handle_errors`, which maps
`AppError` subclasses to their status code, Pydantic `ValidationError` to
400 (with the raw submitted values stripped — see SECURITY.md), and
anything unexpected to a generic 500 that never leaks internals.

## Data model (single table, `gweb-onboarding`)

`PK = APP#<applicationId>` for everything application-scoped; item type
is the `SK`:

| SK | Written by | Notes |
|---|---|---|
| `META` | create_application, then version-bumped by every applicant/business patch and submit | `status` (DRAFT→SUBMITTED), `version` (optimistic concurrency) |
| `PERSON#<personId>` | patch_applicant | one per owner/controller |
| `BUSINESS` | patch_business | single slot, full overwrite per patch |
| `DOC#<documentId>` | presign_document, then complete_document | REQUESTED → ACCEPTED\|REJECTED |
| `MCC#PROPOSED` | classify_mcc | single slot — the system's suggestion |
| `MCC#CONFIRMED` | confirm_mcc | single slot — what the applicant actually confirmed (kept separate from PROPOSED so the audit trail shows both) |
| `EVAL#LATEST` | evaluate | single slot (approved deviation from the spec's literal per-call `EVAL#<evalId>` — see spec §2.3's own listed alternative) |
| `SUBMISSION` | submit | written once, atomically with META's SUBMITTED transition; holds the cached client-facing review payload plus the richer downstream-processor payload |

Global (not `APP#`-scoped) reference data is **not** in DynamoDB at all —
`src/data/mcc_catalog.json` and `risk_policy.json` are packaged static
files, loaded once per Lambda container and cached in memory
(`mcc_catalog_service.py`), matching the spec's own recommendation that a
catalog this size doesn't need a GSI.

### Concurrency & idempotency

- **Optimistic concurrency**: `META.version`, bumped via a
  `ConditionExpression` on every applicant/business/submit write
  (`dynamo_client.put_item_with_meta_version_bump`, a `TransactWriteItems`
  call that atomically writes the child item *and* bumps `META` together —
  a concurrent conflicting write fails the whole transaction, not just
  half of it).
- **Idempotency**: every mutating item (`META`, `DOC#`, `MCC#PROPOSED`,
  `MCC#CONFIRMED`, `EVAL#LATEST`) carries its own `lastRequestId`/
  `lastResponse`. A retried call with the same `requestId` replays the
  cached response instead of reapplying the write. `submit` goes one step
  further: once `META.status` is `SUBMITTED`, *any* repeat call (any
  `requestId`) returns the persisted result — submission is a one-way
  transition, so "submit again" is a safe no-op by design, not just a
  cache hit.

## The 45-second rule

Lambda `Timeout: 45` (hard). Two call sites actually make an outbound
call and are the only places this matters:

1. **Document verification** (`complete_document` → S3 HEAD/GetObject):
   preflight-checks `remaining_ms(context)` against
   `DOCUMENT_STREAM_MIN_REMAINING_MS` (10s) before starting the stream; a
   genuine S3 timeout is caught and mapped to `504`.
2. **AI evaluation** (`evaluate` → `MockAiProvider`): same preflight
   pattern (`EVALUATION_AI_CALL_MIN_REMAINING_MS`), plus the call itself
   runs under a hard `ThreadPoolExecutor` deadline
   (`outbound_call_timeout_seconds`) — `future.result(timeout=...)`
   stops *waiting* for a hung call (Python can't forcibly kill a thread;
   the frozen/recycled Lambda environment handles actual cleanup). Both
   the preflight-too-low-budget path (`202 PROCESSING`, no call attempted)
   and the mid-call-timeout path (`504`, `EVAL#LATEST` persists `FAILED`)
   are covered by dedicated tests, including a real ~6-second wall-clock
   test against a fake provider that sleeps 10 seconds.

Every other handler only talks to DynamoDB, which has its own AWS-managed
timeout/retry behavior well inside the 45s budget for the query shapes
this system uses (single-partition `Query`/`GetItem`/`PutItem`, never a
scan).

## Replaceable adapters (spec §11)

`src/adapters/` holds every external-facing integration behind a narrow
interface, so each is independently swappable without touching a service
or handler:
- `db/dynamo_client.py` — the only module that imports boto3 for DynamoDB.
- `storage/s3_client.py` — the only module that imports boto3 for S3.
- `ai/base.py` (`AiProvider` ABC) + `ai/mock_provider.py` — a real
  provider would implement the same one-method interface; nothing else in
  the codebase would need to change.

## Local demo harness (`scripts/run_local_demo.py`)

Not a second implementation of the backend — it imports and calls the
exact `handler(event, context)` functions from `src/handlers/*`, wrapped
in: (1) a small regex-based router standing in for API Gateway's routing,
and (2) moto's `ThreadedMotoServer`, a real local HTTP server emulating
DynamoDB and S3, so presigned URLs are real, working URLs a browser can
`PUT` directly to. See README.md for how to run it.
