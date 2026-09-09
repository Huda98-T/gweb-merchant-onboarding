# AI-USAGE.md

This document describes how AI was used to build the project, how
AI-generated output was reviewed and verified, and where AI is used in
the running application.

## Two separate things called "AI" here

1. **AI used to build this repository.** Two different tools were used,
   in two genuinely different capacities:
   - **Claude Code** (model `claude-sonnet-5`) did the implementation —
     every file under `src/`, `tests/`, `scripts/`, `ui/`, `template.yaml`,
     and this documentation set, across six build phases, in an
     interactive session with continuous human direction.
   - **Claude, chat interface** (model `claude-sonnet-5`, not Claude
     Code) was used separately by the candidate throughout the project as
     an architecture/design reviewer — proposing initial designs,
     pressure-testing Claude Code's implementation plans before they were
     sent to Claude Code, catching spec mismatches before code was
     written (e.g. an incorrectly proposed `docType` enum that didn't
     match assessment §4, and an initially wrong assumption that MCC 6012
     was "quasi-cash," both challenged during design review before any
     code existed), and approving or rejecting each phase's plan.

   **No application code, test, or piece of infrastructure-as-code in
   this repository was manually hand-typed by the candidate** — saying
   otherwise would misrepresent how this was built. The candidate's
   contribution was primarily in requirements interpretation, architecture
   and technology decisions, AI direction, review, testing, debugging,
   verification, and acceptance of the resulting implementation.
   `GWEB_Implementation_Spec.md` was produced through an extended
   architecture discussion in that chat-based Claude session (initial
   analysis, revision from TypeScript to Python, iterative updates),
   before Phase 1 implementation began.

2. **AI used inside the running application.** Exactly one place:
   `MockAiProvider` (`src/adapters/ai/mock_provider.py`), which generates
   narrative commentary text for the `/evaluate` endpoint. It is **not** a
   real LLM call — no network request, no external API, fully
   deterministic (same input → same output, always). This was an explicit
   human decision for this phase (see "Engineering decisions" below), not
   a technical limitation — the `AiProvider` interface (`base.py`) is
   designed so a real provider could be swapped in without touching any
   caller.

## What "AI-assisted" actually looked like, per phase

- **Phase 1** (core CRUD): scaffold, Pydantic models, DynamoDB adapter,
  four Lambda handlers — generated directly from the spec document, then
  reviewed handler-by-handler before any commit.
- **Phase 2** (documents): generated the presign/complete flow, then
  **found and fixed a real bug during self-testing** — `Table.meta.client`
  double-marshals data for `TransactWriteItems`, corrected before any
  human review saw it. Separately, attempted a `ContentLength`-locking
  technique for upload-time size enforcement, could not verify it against
  real S3 in this environment, and **chose not to ship it with fake test
  coverage** rather than claim an unverified security property — flagged
  explicitly for a human decision rather than silently shipped.
- **Phase 3** (MCC classification): an early planning pass **incorrectly
  assumed MCC 6012 was "quasi-cash."** During review of the initial plan,
  the classification assumptions were challenged before implementation.
  The MCC descriptions were then verified against external sources —
  before writing any code, the actual descriptions for MCC 6012/6051/6211
  were checked against a live web search and a direct `curl` download of
  the upstream dataset (with SHA-256 + row-count verification,
  cross-checked via two independent fetch methods) — this confirmed 6051,
  not 6012, is the quasi-cash code, and the risk-policy reasons were
  written to match. This is the clearest example in this project of an
  AI-generated first guess being wrong, caught by human-directed review
  and verification before it reached code.
- **Phase 4** (AI evaluation): built the mock adapter, deterministic
  rate/risk-flag services, and the timeout-wrapped adapter call. The
  hang-detection test **caught a real concurrency bug** on its first run —
  `with ThreadPoolExecutor(...) as executor:` blocks on exit until the
  hung thread actually finishes, silently defeating the intended timeout
  (the test took the full 10s instead of the expected ~6s). Fixed with an
  explicit `shutdown(wait=False)`; the test then passed and stayed in the
  suite as a permanent regression guard.
- **Phase 5** (review/submit): the spec doesn't define a rule for when a
  business license should be conditionally required, or how to split
  "applicant" from "beneficial owners/controllers" in the normalized
  payload (Phase 1's `role` field is free-text, not a taxonomy). Both were
  flagged explicitly as assumptions with a stated rationale rather than
  invented silently.
- **Phase 6** (UI, integration, hardening): building the demo UI surfaced
  a real gap — the S3 bucket had no `CorsConfiguration`, so a real browser
  would never have been able to complete the direct-to-S3 upload
  cross-origin; fixed and verified with a real CORS-preflight `curl`
  request against a live local S3 emulator (not just reasoning about it).
  The final security pass then found that Pydantic's validation-error
  output includes the raw submitted value (`input`) for every failing
  field — for PII-bearing models that meant real applicant data could
  reach a log line or a 400 response body; fixed with a redaction step and
  a regression test.

## AI-assisted implementation vs. everything else

- **Implementation** (writing code, tests, config, docs): AI-generated,
  every phase, no exceptions.
- **Engineering decisions**: made jointly. Non-obvious architectural and
  security decisions were reviewed explicitly during the build rather
  than being accepted blindly from the model — e.g. the `EVAL#LATEST`
  single-slot design (vs. spec's literal per-call `EVAL#<evalId>`), the
  mock-vs-real AI adapter choice for Phase 4, the curated-keyword-subset
  vs. full-catalog-transcription tradeoff in Phase 3, and the
  `applicationId`-as-bearer-token security tradeoff (Phase 1). Not every
  decision was caught before implementation, though — see "Debugging"
  below for one that was only caught by a test after the fact.
- **Review**: the human explicitly requested and received a standalone
  Phase 1 code review before Phase 2 began, which surfaced one
  MUST-FIX-NOW finding (a missing `min_length` constraint on `requestId`
  that could cause an idempotency-cache collision) — fixed, tested, and
  committed as its own change before continuing.
- **Testing**: every test in `tests/` was AI-written, but the pass/fail
  results reported at each phase are real `pytest` runs against real
  moto-mocked DynamoDB/S3, not narrated or assumed — including the slow/
  hanging-dependency test, which genuinely takes several seconds of
  wall-clock time because it waits out a real thread timeout.
- **Debugging**: the `ThreadPoolExecutor` bug above, a local port
  conflict with macOS's AirPlay Receiver on port 5000 (diagnosed via
  `lsof`, not guessed), and a WebFetch tool's silent truncation of a large
  CSV response (worked around by using `curl` directly instead, with
  independent verification) are all concrete instances of AI-driven
  debugging in this project, not just first-pass code generation.
- **Verification**: MCC data provenance (SHA-256, row count, dual-method
  commit-SHA confirmation), the real direct-S3-upload test via `curl`
  against a live local S3 emulator, and the CORS-preflight test above are
  all genuine external verification steps, not internal reasoning
  presented as verification.

## Representative prompts

Short, real excerpts from this project's actual session history — not
fabricated, not paraphrased into something cleaner than they were —
showing how direction was actually given, phase by phase.

**Phase 1 (implementation direction):**
> Proceed with Phase 1 exactly as described. Use GWEB_Implementation_Spec.md
> as the source of truth. Implement only: repository scaffold, SAM/IaC
> foundation, DynamoDB and S3 definitions, common utilities, Pydantic
> models, DynamoDB adapter, create/get/patch applicant/patch business,
> unit tests and the moto-backed integration test.

**Phase 3 (MCC catalog verification — after WebFetch was found to
silently truncate a large CSV response):**
> Before deciding between the curated subset and chunked transcription,
> try a third approach first. Download the raw CSV directly via a shell
> command (curl/wget) from the raw GitHub URL, bypassing WebFetch
> entirely — since WebFetch's summarization-through-a-small-model is what
> caused the truncation, a direct file download and parse with csv/pandas
> should get you the complete, unmodified dataset with zero transcription
> risk.

**Phase 4 (timeout / AI-adapter constraint):**
> Wire common/timeouts.py into this flow for real — this is the first
> outbound-call path since Phase 2's document adapter — including one
> test proving a mocked slow/hanging adapter call is caught and times out
> cleanly within budget.

**Phase 6 (final security/hardening pass):**
> Review the complete repository for: sensitive data in logs, secrets/API
> keys committed to source, public S3 access, overly broad IAM, raw
> document contents unnecessarily stored in DynamoDB, raw document
> contents unnecessarily sent to AI, PAN/CVV handling, hardcoded
> credentials, unsafe debug output, client-controlled security-sensitive
> fields. Fix only real issues found. Do not refactor unrelated code.

**Report-format constraint (Phase 4 onward):**
> Report format for every step (plan and final result): bullet list
> only — files changed (one line each), test count pass/fail, ruff/sam
> status, and any deviations/flagged decisions. I'll ask if I need more
> detail on a specific part.

## Model

- **Claude Code**, model `claude-sonnet-5` ("Claude Sonnet 5") —
  implementation, operating interactively across the six build phases.
- **Claude**, model `claude-sonnet-5`, chat interface (not Claude Code) —
  architecture design and review, used separately by the candidate to
  develop and pressure-test the specification and each phase's plan
  before it was sent to Claude Code.
