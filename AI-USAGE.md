# AI usage

This document distinguishes two different meanings of "AI" that both
apply to this project, and is honest about which parts of the codebase
are AI-generated (nearly all of it) versus human-directed.

## Two separate things called "AI" here

1. **AI used to build this repository.** Every file under `src/`,
   `tests/`, `scripts/`, `ui/`, `template.yaml`, and this documentation
   set was written by Claude (running as Claude Code, model
   `claude-sonnet-5`) across six build phases, in an interactive session
   with continuous human direction. **No application code, test, or piece
   of infrastructure-as-code in this repository was manually hand-typed
   by the client/candidate** — saying otherwise would misrepresent how
   this was built. `GWEB_Implementation_Spec.md` was provided to this
   session as an existing input/starting point (its own authorship is
   outside this session's visibility — it predates Phase 1).

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
  assumed MCC 6012 was "quasi-cash."** The human's decision brief for this
  phase explicitly warned against exactly this kind of unverified
  labeling. Before writing any code, the actual descriptions for
  MCC 6012/6051/6211 were verified against a live web search and a direct
  `curl` download of the upstream dataset (with SHA-256 + row-count
  verification, cross-checked via two independent fetch methods) — this
  confirmed 6051, not 6012, is the quasi-cash code, and the risk-policy
  reasons were written to match. This is the clearest example in this
  project of an AI-generated first guess being wrong, caught by
  human-directed verification before it reached code.
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
- **Engineering decisions**: made jointly, but every non-obvious one was
  surfaced explicitly for a human call before being implemented — e.g.
  the `EVAL#LATEST` single-slot design (vs. spec's literal per-call
  `EVAL#<evalId>`), the mock-vs-real AI adapter choice for Phase 4, the
  curated-keyword-subset vs. full-catalog-transcription tradeoff in
  Phase 3, and the `applicationId`-as-bearer-token security tradeoff
  (Phase 1). None of these were silently decided by the AI alone.
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

## Model

Claude Code, model `claude-sonnet-5` ("Claude Sonnet 5"), operating
interactively with a human reviewing and approving decisions at each of
the six build phases.
