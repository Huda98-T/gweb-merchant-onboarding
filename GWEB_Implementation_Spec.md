# GWEB Merchant Onboarding — Implementation Specification

Version 1.1 — Revised to Python (from initial TypeScript draft) for auditability. Design finalized before implementation. This document is the source of truth handed to Claude Code for the build. No implementation code below — architecture, data model, API contract, and repo structure only.

---

## 1. AWS Architecture

### 1.1 Component map

```
Client (SPA)
  │
  ├── HTTPS ──▶ API Gateway (HTTP API)
  │                  │
  │                  ▼
  │            Lambda handlers (one per route, Python 3.12)
  │                  │
  │        ┌─────────┼─────────────┐
  │        ▼         ▼             ▼
  │   DynamoDB     S3 (via      AI adapter
  │   (metadata)   presigned    (mock / real,
  │                 URLs)        timeout-bound)
  │
  └── PUT (direct) ──▶ S3 (document bytes, bypasses Lambda entirely)
```

### 1.2 Key decisions

**Decision: HTTP API (API Gateway v2), not REST API (v1).**
WHY: Lower cost, lower latency, simpler request/response mapping, and this assessment needs no REST-specific features (usage plans, request validators, WAF integration). Sufficient for a prototype scored on architecture clarity, not API Gateway feature depth.
Tradeoff: Fewer built-in features (no native request validation against JSON Schema at the gateway layer — validation happens in Lambda instead). Acceptable since Lambda-side validation is required anyway for defense-in-depth.

**Decision: One Lambda function per route (not one monolith handler with internal routing).**
WHY: This is explicitly what the rubric's "Lambda discipline" and "replaceable adapters" language rewards. Each function has a single responsibility, a tight IAM policy, and is independently testable.
Tradeoff: More functions to deploy/manage (~11 Lambdas) and some duplicated boilerplate (auth check, error wrapper) across handlers. Mitigated by putting shared logic in a `common/` library layer that each handler imports — not by merging handlers.

**Decision: Presigned S3 URLs for all document uploads; Lambda never touches file bytes.**
WHY: Directly mandated by §4.1 of the spec, and it's the correct serverless pattern regardless — avoids Lambda's payload size limits (6MB sync) and keeps upload time off the 45-second clock entirely.
Tradeoff: Two round trips from the client (request URL, then confirm-upload call) instead of one. Acceptable — this is the standard, expected pattern here.

**Decision: Synchronous-first with async fallback for `/evaluate`, not a full event-driven pipeline (no SQS/EventBridge/Step Functions).**
WHY: The AI adapter call is the only realistic risk of exceeding budget. A same-Lambda pattern — try synchronously with a hard internal timeout (~25s); if it would exceed budget, write `PROCESSING` state and return immediately, client polls `GET /evaluation` — satisfies §7.1's async requirement without building infrastructure that isn't needed anywhere else in the system. It's also far cheaper to implement and test correctly within 2 days.
Tradeoff: Not a "real" event-driven architecture (no queue-based retry, no dead-letter handling). This is explicitly acceptable — §15 lists event-driven async as a *bonus differentiator*, not a requirement. State this tradeoff explicitly in the README.

**Decision: No custom auth system (Cognito/JWT). Use an unguessable, server-generated `applicationId` as the resume/bearer token.**
WHY: The spec's user journey requires resumability, not user accounts. Building real auth would consume hours the rubric doesn't reward (auth isn't a scored category). Document this as an explicit assumption.
Tradeoff: Anyone with the ID can access/edit that application — acceptable for a prototype, called out clearly as a known gap and production improvement in the security note.

**Decision: AWS SAM for IaC.**
WHY: Lowest boilerplate-to-output ratio for a Lambda/API Gateway/DynamoDB/S3 stack within a 2-day budget; native local testing via `sam local`. CDK would add TypeScript-infra complexity on top of TypeScript-app complexity for no functional benefit here; Terraform is heavier for a single-stack prototype.
Tradeoff: Less flexible than CDK for complex conditional infra — irrelevant at this scale.

**Decision: Python 3.12 runtime.**
WHY: You review and audit the code more reliably in Python than in TypeScript, and the client's cover note explicitly grades your ability to "understand, review, test, and take responsibility" for AI-generated code — that's a stronger fit than marginal cold-start or tooling differences between runtimes. Python also has a mature, well-known equivalent for every piece this project needs: Pydantic for typed schema validation (directly satisfies §11's "typed models/schema validation" requirement), boto3 as the standard AWS SDK, pytest for testing, and full first-class Lambda support.
Tradeoff: Slightly slower cold starts than Node.js for equivalent bundle size, and dependency packaging (Pydantic, boto3 extras) needs a Lambda layer or a build step instead of Node's flatter `node_modules` deployment — handled cleanly by SAM's `python3.12` runtime with a `requirements.txt`-driven layer, so this is a minor build-config difference, not an architectural one.

### 1.3 The 45-second rule, concretely

- Internal target: 30s soft deadline inside every handler (computed from Lambda's `context.getRemainingTimeInMillis()`, not a hardcoded constant — so it adapts if Lambda timeout config changes).
- Any outbound call (AI adapter, mocked third-party) gets an explicit timeout at roughly 60% of remaining budget when the call starts, leaving room to serialize a response.
- On timeout: catch, log a structured timeout event (no sensitive payload), return a `504`-style clean error with enough state (`evaluationId`, status) for the client to retry or poll.
- Async fallback specifically for `/evaluate`: if the handler estimates (or actually hits) the near-timeout point, it writes `EVAL#<id>` with `status: PROCESSING` and returns `202` immediately; `GET /evaluation` polls that record.

---

## 2. DynamoDB Data Model

### 2.1 Table strategy: single table

**Decision: Single table (`gweb-onboarding`), not one table per entity.**
WHY: All access patterns in this system pivot around one partition key — the application. A single table with `PK = APP#<applicationId>` lets every "load everything about this application" or "list this application's X" query run as one `Query` call, which is exactly the access-pattern reasoning §9 asks you to document and defend.
Tradeoff: Less intuitive to browse in the AWS console than separate tables; requires discipline in `SK` naming. Standard, well-understood tradeoff for single-table design — worth explaining briefly in the architecture doc so a reviewer sees you made it deliberately, not by default.

### 2.2 Schema

| PK | SK | Item type | Key attributes |
|---|---|---|---|
| `APP#<appId>` | `META` | Application root | `status`, `version`, `createdAt`, `updatedAt`, `applicantComplete`, `businessComplete` |
| `APP#<appId>` | `PERSON#<personId>` | Controller/owner | `role`, `ownershipPct`, `firstName`, `lastName`, `dob`, `address`, `idType`, `idLast4`, `consentTimestamp`, `consentVersion` |
| `APP#<appId>` | `BUSINESS` | Business/entity record | `legalName`, `dba`, `entityType`, `registrationId`, `addresses`, `volumeMetrics`, `existingProcessor` |
| `APP#<appId>` | `DOC#<docId>` | Document metadata | `docType`, `status` (lifecycle enum), `s3Key`, `checksum`, `uploadedAt`, `expiresAt`, `reviewStatus` |
| `APP#<appId>` | `MCC#PROPOSED` | System MCC suggestion | `candidates: [{code, description, confidence, reason}]`, `generatedAt` |
| `APP#<appId>` | `MCC#CONFIRMED` | Applicant-confirmed MCC | `code`, `confirmedAt`, `selfSelectedActivity` |
| `APP#<appId>` | `EVAL#<evalId>` | Evaluation/rate-analysis result | `status` (PENDING/PROCESSING/COMPLETE/FAILED), `statementMetrics`, `effectiveRate` (deterministic), `aiCommentary`, `riskFlags: [{field, message, severity}]` |
| `MCC#<code>` | `META` | MCC catalog entry (separate item space, not under an `APP#` partition) | `code`, `description`, `category` |
| `POLICY#<provider>#<mccCode>` | `META` | Risk policy override | `tier` (standard/enhanced-review/restricted), `reason` |

Notes:
- MCC catalog and risk policy are **not** nested under `APP#` — they're global reference data, queried independently (`GET /mcc?query=`) and joined into application records only by reference (the `code` string), which is what keeps the taxonomy and policy layers separable per §5.
- `POLICY#` uses a composite `<provider>#<mccCode>` key so a `default` provider row acts as the fallback and specific providers can override — this directly demonstrates "provider-specific overrides" cheaply, with no extra table.

### 2.3 Access patterns (documented per §9's requirement)

| Access pattern | Query |
|---|---|
| Load full application | `Query PK = APP#<id>` (returns META + all children in one call, filter by SK prefix client-side or via `begins_with`) |
| List people/owners | `Query PK = APP#<id>, SK begins_with PERSON#` |
| List documents | `Query PK = APP#<id>, SK begins_with DOC#` |
| Fetch current evaluation | `Query PK = APP#<id>, SK begins_with EVAL#`, take latest by `evalId` (ULID/timestamp-ordered) or maintain a `EVAL#LATEST` pointer item |
| Submission status | `GetItem PK = APP#<id>, SK = META` → `status` field |
| MCC catalog search | `Query` against a GSI on the `MCC#` item space (`GSI1PK = MCCSEARCH`, `GSI1SK = description` prefix) — or, if catalog is small (a few hundred rows), load once into Lambda memory/cache and search in-process rather than building a GSI. **Recommend the in-memory approach** for a 2-day build: simpler, no GSI to design/test, and MCC catalogs are small enough (~1000 rows) that this is realistic even in production-lite form. |

### 2.4 Concurrency & idempotency

**Decision: Optimistic concurrency via a `version` number on `META`, checked with a DynamoDB conditional expression on every write.**
WHY: Satisfies §9's "prevent silent overwrites" requirement with minimal code — one `ConditionExpression: version = :expectedVersion` per update, reject with a `409` on mismatch.
Tradeoff: Client must re-fetch and retry on conflict — acceptable for a low-concurrency onboarding form (one applicant editing their own application).

**Decision: Idempotent writes via a client-supplied `requestId`, stored on the item and checked before applying a write.**
WHY: Explicitly required by §9. Cheap to implement: store `lastRequestId` on `META`/`DOC#` items; if an incoming write's `requestId` matches, return the cached result instead of reapplying.
Tradeoff: Small extra attribute per item — negligible cost.

---

## 3. API Contract

Base path assumed: `/v1`. All bodies JSON. All routes except `POST /applications` require the `applicationId` to be supplied as a bearer-style header (`X-Application-Token`) matching the path `{id}` — simple ownership check, not full auth (see §1.2 assumption).

| Method & path | Purpose | Request body (key fields) | Response (key fields) | Notes |
|---|---|---|---|---|
| `POST /applications` | Create application | `{}` (empty — server generates ID) | `201 { applicationId, status: "DRAFT", version: 1 }` | Idempotency via `requestId` header optional here since it's a create |
| `GET /applications/{id}` | Retrieve normalized full state | — | `200 { meta, applicant: [...persons], business, documents: [...], mcc, evaluation }` | Single aggregated read across the partition |
| `PATCH /applications/{id}/applicant` | Upsert person(s) | `{ requestId, personId?, firstName, lastName, dob, address, role, ownershipPct, idType, idLast4, consentVersion }` | `200 { personId, version }` | `personId` omitted → create; present → update. Conditional write on `version` |
| `PATCH /applications/{id}/business` | Upsert business fields | `{ requestId, legalName, dba, entityType, registrationId, addresses, volumeMetrics, existingProcessor }` | `200 { version }` | Same conditional-write pattern |
| `POST /applications/{id}/documents/presign` | Get upload URL | `{ requestId, docType, fileName, mimeType, sizeBytes }` | `200 { docId, uploadUrl, s3Key, expiresIn }` | Validates `docType` against allowed enum and `mimeType` against PDF/JPG/PNG before issuing URL |
| `POST /applications/{id}/documents/{docId}/complete` | Confirm upload | `{ requestId, checksum }` | `200 { docId, status: "RECEIVED" }` | Server verifies checksum against S3 object (HEAD request) before flipping status; on mismatch → `422` |
| `GET /mcc?query=` | Search MCC catalog | — (query param) | `200 { results: [{ code, description, category }] }` | In-memory search, see §2.3 |
| `POST /applications/{id}/classify` | Request MCC suggestion | `{ requestId, selfSelectedActivity, businessDescription }` | `200 { candidates: [{ code, description, confidence, reason }], requiresManualReview }` | `requiresManualReview: true` for ambiguous/enhanced-review MCCs (§5) |
| `POST /applications/{id}/evaluate` | Request AI evaluation | `{ requestId, statementDocId? }` | `202 { evalId, status: "PROCESSING" }` or `200 { evalId, status: "COMPLETE", result }` | Sync if within budget, else async — see §1.3 |
| `GET /applications/{id}/evaluation` | Poll evaluation result | — | `200 { status, statementMetrics, effectiveRate, aiCommentary, riskFlags }` | Client polls until `status = COMPLETE` or `FAILED` |
| `POST /applications/{id}/submit` | Validate & lock application | `{ requestId }` | `200 { status: "SUBMITTED", reviewPayload }` or `400 { missingItems: [...] }` | Blocks on missing required fields/documents; produces the normalized internal review payload described in §2's step 8 |

**Decision: `GET /applications/{id}` returns one aggregated object, not requiring the client to call five separate endpoints.**
WHY: Matches the single-table "load application" access pattern (one `Query`), and simplifies the "Review & submit" screen, which needs the full picture anyway.
Tradeoff: Slightly larger payload than strictly necessary for screens that only need a subset — acceptable at this data scale (one applicant's onboarding record, not a bulk listing).

---

## 4. Project / Repository Structure

```
gweb-onboarding/
├── README.md                     # setup, deploy, API examples, assumptions, gaps
├── AI-USAGE.md                   # required per client's cover note
├── SECURITY.md                   # IAM approach, logging/redaction, prod improvements
├── template.yaml                 # SAM template — API Gateway, Lambdas, DynamoDB, S3, IAM, dependencies layer
├── openapi.yaml                  # API contract (§3) as OpenAPI spec
├── pyproject.toml                # project metadata, tool config (pytest, ruff/black if used)
├── requirements.txt              # runtime deps for the Lambda layer: pydantic, boto3 (boto3 is present in the Lambda runtime by default, pinned here for local/test parity)
├── requirements-dev.txt          # pytest, moto (mocked AWS for tests), local tooling
├── src/
│   ├── handlers/                 # one file per route, thin — parse event, call service, build response
│   │   ├── create_application.py
│   │   ├── get_application.py
│   │   ├── patch_applicant.py
│   │   ├── patch_business.py
│   │   ├── presign_document.py
│   │   ├── complete_document.py
│   │   ├── search_mcc.py
│   │   ├── classify_mcc.py
│   │   ├── evaluate.py
│   │   ├── get_evaluation.py
│   │   └── submit.py
│   ├── services/                 # business logic, no direct boto3 calls where avoidable
│   │   ├── application_service.py
│   │   ├── document_service.py
│   │   ├── mcc_service.py
│   │   ├── risk_policy_service.py
│   │   └── evaluation_service.py
│   ├── adapters/                 # replaceable external-facing modules
│   │   ├── ai/
│   │   │   ├── base.py           # AiProvider abstract base class (interface)
│   │   │   ├── mock_provider.py
│   │   │   └── real_provider.py  # optional, time permitting
│   │   ├── storage/
│   │   │   └── s3_client.py      # presign, checksum verification, boto3 S3 client wrapper
│   │   └── db/
│   │       └── dynamo_client.py  # table access, conditional writes, idempotency helpers, boto3 resource wrapper
│   ├── models/                   # pydantic BaseModel classes for every request/response and DynamoDB item shape
│   ├── common/                   # error wrapper/decorator, redaction-aware logger, response builder, timeout budget helper (context.get_remaining_time_in_millis)
│   └── data/
│       └── mcc_catalog.json      # seeded MCC dataset + risk-policy defaults
├── scripts/
│   └── seed_mcc.py               # documented refresh process for the MCC dataset
├── tests/
│   ├── unit/                     # validation, MCC/risk mapping, rate arithmetic, per-handler logic
│   ├── integration/              # full happy-path flow (create → ... → submit), using moto to mock DynamoDB/S3
│   └── timeout/                  # the mocked-hang / 45s-safety test
└── docs/
    └── architecture.md           # diagram + request flow + timeout/retry/failure-state explanation
```

**Decision: `handlers/` thin, `services/` and `adapters/` hold the real logic.**
WHY: This is what "storage, external providers, AI, and business policy are replaceable adapters/modules rather than embedded in one large handler" (§11) is asking for, made literal in the folder structure — and it means Claude Code can be directed at one file at a time with a clear, narrow scope per prompt, which keeps generations correct and reviewable.
Tradeoff: More files/indirection than a quick script would need — worth it here since it's explicitly a scored criterion.

**Decision: Pydantic `BaseModel` classes in `models/` for every request/response and DynamoDB item shape, not raw dict handling.**
WHY: Directly satisfies §11's typed-model requirement, gives you (as reviewer) a single readable file per data shape to check against §3 of the assessment PDF, and Pydantic raises clear validation errors at the API boundary — which is also where §10 requires input validation on every request.
Tradeoff: A small amount of boilerplate per model class versus raw dicts — worth it for both the rubric and your own ability to audit what each endpoint actually accepts/returns.

**Decision: pytest + moto for testing, not AWS-hosted integration tests.**
WHY: moto mocks DynamoDB and S3 in-process, so unit and integration tests (including the required slow-dependency/timeout test) run entirely locally, fast, and without needing a deployed stack — important given the time budget. pytest's fixture system also maps cleanly onto "set up a fake application, then test each handler against it."
Tradeoff: moto doesn't catch every real-AWS edge case (IAM permission errors, real network latency) — the README should note that a deployed smoke test is a recommended next step beyond this prototype's test suite.

---

## 5. Summary of assumptions to confirm before build

1. **Runtime**: Python 3.12 — decided, for auditability (see §1.2).
2. **No real auth** — `applicationId` + a token header is the only access control. Stated as a known gap in README/SECURITY.md.
3. **MCC catalog**: small, in-memory dataset (~hundreds of rows) loaded from a seed JSON file rather than DynamoDB-backed search — acceptable per §9 ("DynamoDB or packaged/static data is acceptable if justified").
4. **AI adapter**: mock-only by default; a real provider integration is a stretch goal only if core requirements finish early.
5. **Async evaluation**: same-Lambda PROCESSING/poll pattern, not a queue-based pipeline.
6. **KMS**: documented as a "would use in production" decision rather than implemented, to save setup time — SSE-S3 default encryption is used instead. State this explicitly in the security note.

---

## Handoff note for Claude Code

This document (sections 1–4) is the implementation specification. Build in the priority order already agreed:
IaC skeleton → core CRUD Lambdas → document upload flow → MCC catalog/classify → AI adapter/evaluate → submit → the 45s timeout test → docs → minimal UI.

Each implementation session should reference the specific section(s) of this spec relevant to that step, not the whole document at once.
