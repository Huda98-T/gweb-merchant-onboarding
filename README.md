# GWEB Merchant Onboarding

A serverless (AWS Lambda + API Gateway + DynamoDB + S3) merchant-onboarding
backend, built in six phases against [`GWEB_Implementation_Spec.md`](GWEB_Implementation_Spec.md)
— the source-of-truth architecture/data-model/API document this project
was built from. A minimal static demo UI (`ui/index.html`) exercises the
whole flow end-to-end against a local, real-code harness (no AWS account
required to try it).

See also: [SECURITY.md](SECURITY.md) (IAM, data handling, known gaps),
[AI-USAGE.md](AI-USAGE.md) (how this codebase was built),
[docs/architecture.md](docs/architecture.md) (data model, request flow,
the 45-second rule), and [docs/demo-walkthrough.md](docs/demo-walkthrough.md)
(one complete application, step by step, with real request/response bodies).

## Architecture, in one paragraph

Client → API Gateway (HTTP API) → one Lambda per route (Python 3.12,
13 functions) → a single-table DynamoDB design (`PK = APP#<id>`, item
types vary by `SK`) for all metadata, and S3 for document bytes via
**presigned URLs only** — Lambda never touches file content, the browser
uploads directly to S3. There is no real authentication; the
server-generated `applicationId` doubles as a bearer token
(`X-Application-Token` header), a documented, accepted gap for this
prototype (see SECURITY.md). AI usage inside the running system is limited
to one thing: a mock, deterministic-output adapter that writes narrative
commentary for the evaluation step — it never computes a number and every
number it's given comes from Python, not the model.

```
Browser (ui/index.html)
   │  fetch() — same contract whether pointed at a real
   │  deployed API Gateway URL or the local demo harness
   ▼
API Gateway (HTTP API)  ──or──  scripts/run_local_demo.py's
   │                             tiny HTTP router (same Lambda
   ▼                             handler code, no reimplementation)
13 Lambda functions (src/handlers/*, one per route)
   │              │
   ▼              ▼
DynamoDB       S3 (via presigned URLs; direct browser PUT)
(single table)
```

## Repository layout

```
src/
  handlers/    one thin file per route — parse, call service, respond
  services/    business logic (validation, rate calc, classification, risk flags, orchestration)
  adapters/    replaceable external-facing modules: db/ (DynamoDB), storage/ (S3), ai/ (AiProvider)
  models/      Pydantic models — every request/response and DynamoDB item shape
  common/      error handling, structured/redacting logger, timeouts, auth, response builder
  data/        packaged MCC catalog + risk policy (static JSON, no runtime GitHub dependency)
scripts/
  build_mcc_catalog.py   offline CSV -> catalog JSON build step (see src/data/MCC_PROVENANCE.md)
  run_local_demo.py      local demo harness — real handler code + moto-backed AWS emulator
ui/
  index.html    the entire demo frontend — single file, vanilla JS, no build step
tests/
  unit/         fast, isolated (pure functions, adapters against moto)
  integration/  full flows through real handlers, against moto-mocked DynamoDB/S3
template.yaml   SAM template — the actual deployable infrastructure
```

## Setup

Requires Python 3.12+ (the deployed Lambda runtime is exactly 3.12;
development/testing works on newer 3.x too) and the AWS SAM CLI (only
needed for `sam validate`/`sam build`/`sam deploy` — not for tests or the
local demo).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes runtime deps + pytest/moto/ruff
pip install aws-sam-cli               # optional, only for template validate/build/deploy
```

## Running tests

```bash
pytest -q                       # full suite (unit + integration), all against moto — no AWS account needed
ruff check src tests            # lint
ruff format --check src tests   # formatting
```

### Timeout behavior (the 45-second rule)

The two call sites that make an outbound call (`complete_document` → S3,
`evaluate` → the AI adapter) are preflight-budget-checked
(`remaining_ms(context)` against a threshold, ~10s) and, for the AI call,
additionally wrapped in a hard `ThreadPoolExecutor` deadline — see
[docs/architecture.md § The 45-second rule](docs/architecture.md#the-45-second-rule)
for the full mechanics. The test that actually *proves* this (not just
describes it) is:

```
tests/integration/test_evaluation_flow.py::test_evaluate_hanging_ai_call_times_out_within_budget_and_persists_failed
```

It simulates a genuinely hung AI dependency (a fake `AiProvider` that
`time.sleep(10)`s — a real thread, real sleep, not a mocked timer),
asserts the real wall-clock elapsed time stays under 9 seconds (the
computed ~6s deadline fires well before the provider's 10s sleep would
ever return), and confirms `EVAL#LATEST` persists `status=FAILED` with
the call surfacing as a `504`. A companion test,
`test_evaluate_low_budget_returns_processing_without_calling_ai`, proves
the other half — when remaining time is already below budget, the AI
provider is asserted **never called** at all, and the response is
`202 PROCESSING`.

## Building / deploying with SAM

```bash
sam validate --lint             # template syntax/schema check
sam build                       # packages all 13 functions + the shared dependencies layer
sam deploy --guided             # first deploy — walks you through stack name, region, parameters
```

`sam deploy --guided` will ask for `MaxDocumentSizeBytes` (default
15 MB — the one configurable parameter in the stack; everything else is
fixed by `template.yaml`). No other environment configuration is needed —
`TABLE_NAME` and `DOCUMENTS_BUCKET_NAME` are wired automatically from the
stack's own DynamoDB table / S3 bucket resources.

### Tearing down

```bash
sam delete --stack-name <your-stack-name>
```

`template.yaml` sets no `DeletionPolicy` on `DocumentsBucket`, so it
defaults to `Delete` — but CloudFormation will fail to delete a
**non-empty** S3 bucket. If any documents were uploaded, empty the bucket
first (`aws s3 rm s3://<bucket-name> --recursive`) or `sam delete` will
error out mid-teardown.

## Running the demo

There is no live AWS deployment behind this repository by default. The
demo runs against a **local harness that executes the real Lambda handler
code** (`src/handlers/*` — nothing reimplemented) against a real local AWS
emulator (moto's `ThreadedMotoServer`), not a hand-mocked UI:

```bash
pip install -r requirements-dev.txt   # if not already installed — pulls in moto[server]
python3 scripts/run_local_demo.py
# then open http://localhost:8080/ in a browser
```

This gives you: a real DynamoDB table and S3 bucket (in-memory, reset on
restart), real presigned-URL generation, and a **real direct browser → S3
PUT** for document uploads (not proxied through the demo script) — the
exact same architecture the deployed stack uses, just pointed at a local
emulator instead of AWS. If you have a real deployed stack, paste its API
Gateway URL into the "API base URL" field at the top of the page instead —
the UI's contract usage is identical either way, nothing in the frontend
assumes which backend it's talking to.

In the UI: new application → fill in one owner/controller and the
business profile → upload the three required documents (any small
PDF/JPG/PNG works — the demo's verification runs the real signature/
checksum/size checks) → enter a business activity and get MCC suggestions,
click one to select it, confirm → run the evaluation → refresh the review
panel → submit. For the full step-by-step account with actual request/
response bodies (not just the UI-click summary above), see
[docs/demo-walkthrough.md](docs/demo-walkthrough.md).

## Known limitations / assumptions

- **No real authentication** — `applicationId` is the bearer token. Anyone
  with the ID has full access. Documented, accepted gap (SECURITY.md).
- **No OCR / malware scanning / document versioning** — explicitly out of
  scope throughout (see Phase 2/3 decisions in the spec history).
- **No real AI/LLM** — the evaluation adapter is a deterministic mock by
  design (Phase 4 decision); see AI-USAGE.md for what "AI" means where.
- **No upload-time size *enforcement*** on the presigned PUT itself — a
  `ContentLength`-locking technique was tried and rejected because it
  couldn't be verified against real S3 in this environment (see Phase 2
  history / SECURITY.md). Actual size is fully enforced post-upload before
  a document is ever marked `ACCEPTED`.
- **No queue-based async pipeline** — `/evaluate`'s `PROCESSING` fallback
  is a same-Lambda pattern (spec §1.3's deliberate choice), not
  SQS/Step Functions.
- **MCC catalog is a full but historical snapshot** (981 codes,
  `src/data/MCC_PROVENANCE.md` has the exact commit/date/checksum) with no
  automatic refresh — by design (decision #7, Phase 3).
- **Local demo harness ≠ deployed stack** — same handler code, but a
  hand-written HTTP router standing in for API Gateway, and moto standing
  in for real DynamoDB/S3. It's a demo/dev convenience, not a production
  local-dev tool (see `scripts/run_local_demo.py`'s own docstring).

## API reference

Base path: `/v1`. All routes except `POST /applications` and `GET /mcc`
require `X-Application-Token: <applicationId>` matching the path `{id}`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/applications` | Create an application |
| GET | `/applications/{id}` | Aggregated read (applicant, business, documents view, MCC, evaluation) |
| PATCH | `/applications/{id}/applicant` | Upsert one owner/controller |
| PATCH | `/applications/{id}/business` | Upsert business profile |
| POST | `/applications/{id}/documents/presign` | Get a presigned S3 PUT URL |
| POST | `/applications/{id}/documents/{documentId}/complete` | Verify an uploaded document (size/signature/checksum) |
| GET | `/mcc?query=` | Search the MCC catalog (no auth — global reference data) |
| POST | `/applications/{id}/classify` | Deterministic MCC suggestions |
| POST | `/applications/{id}/mcc/confirm` | Applicant confirms/corrects the MCC |
| POST | `/applications/{id}/evaluate` | Deterministic rate/fee calc + mock AI commentary |
| GET | `/applications/{id}/evaluation` | Poll the evaluation result |
| GET | `/applications/{id}/review` | Readiness view — same computation `/submit` validates against |
| POST | `/applications/{id}/submit` | Validate + submit (DRAFT → SUBMITTED); `400` with `missingItems` if blocked |

Full request/response schemas are in [`openapi.yaml`](openapi.yaml) —
generated directly from the Pydantic models in `src/models/*.py`
(`python3 scripts/generate_openapi.py`), not hand-authored, so it can't
drift from the actual contract without a code change forcing a
regeneration. Field names are the Pydantic model aliases (camelCase,
matching the JSON wire format exactly).
