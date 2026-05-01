# SMART Implementation Plan

_Last reviewed: 2026-05-01_

This plan translates the current repository state into a finish roadmap with specific, measurable,
achievable, realistic, and time-bound tasks.

## Current baseline

As of 2026-04-29, the repository already supports a **runnable local mock demo**:

- `make check` passes end to end
- `make smoke-local-demo` verifies the local gateway demo path
- `make gateway-run` starts the FastAPI gateway locally
- `make flutter-run` starts the Flutter app locally
- Flutter renders live speaker lanes, consumes SSE updates, and supports lock/unlock controls
- The gateway supports health/readiness, session control, speaker replacement, speaker lock/unlock,
  mock scenes, simulated live ingest, persistence, and persistent SSE subscriptions

### What is already working

- Rust domain model and prioritization crates compile and test cleanly
- Rust `focus_engine` is the documented source of truth for prioritization, with parity checks against the gateway
- `proto/session.proto` is CI-locked against the gateway, Flutter, and the overlapping Rust subset
- the gateway and Flutter now consume generated proto-derived contract artifacts instead of hand-maintained enum/key manifests
- Rust now has a generated transport crate (`crates/session_proto`) that compiles `proto/session.proto` and converts the overlapping session/speaker subset into `audio_core`
- the gateway runtime can now call the Rust prioritization authority directly through the `session_ranker` bridge, with the Python mirror retained as a tested fallback
- Python gateway lint/tests pass
- Flutter analyze/tests pass
- Local SDK/bootstrap flow is automated by `scripts/bootstrap_dev.sh`
- Gateway config, minimal auth, structured request logging, and SQLite session recovery are all in place
- a configurable LibreTranslate-compatible gateway adapter can provide real translated captions without Flutter client changes
- cross-stack integration smoke coverage and an internal beta runbook are in place
- release prep now covers internal-beta packaging, manifest/checksum output, and smoke instructions

### What is still missing to "finish the work"

The system is still missing several capabilities needed for a realistic, durable, releasable app:

- deeper generated/shared-contract runtime use across every runtime (Rust transport bindings now exist, the gateway now reuses Rust prioritization at runtime, and fuller runtime migration is still pending)
- broader direct Rust reuse from Python/Flutter runtime paths beyond prioritization
- real audio capture, diarization, and TTS for a true field-ready workflow
- production-grade auth/roles, metrics, and deployment hardening beyond the current minimal local/beta layer

## Finish lines

To keep scope realistic, this plan uses three finish lines.

### Finish line A — Stable local demo
**Status:** Complete on 2026-04-29.

A fresh machine can bootstrap the repo, run the gateway and Flutter app locally, and exercise mode
changes, reset, live SSE updates, and speaker lock/unlock without code changes.

### Finish line B — Internal end-to-end prototype
**Status:** Complete on 2026-04-29 for the mock/live-simulated path.

The gateway can ingest a stream of realistic speaker/transcript updates, persist session state, and keep
Flutter synchronized across reconnects. This is the first milestone that feels like a usable internal
prototype rather than a mock shell.

### Finish line C — Beta candidate
**Status:** In progress.

The system has a real translation pipeline, minimal auth/observability, and reproducible release
artifacts for controlled external testing.

## Assumptions

These targets assume:

- one engineer working roughly full-time on this slice
- no major design reversal in transport (SSE remains acceptable for the near term)
- provider selection for real translation/audio work is made quickly
- local-first/internal-demo scope stays primary before public-beta scope

## SMART tasks

### Task 1 — Stabilize the local run path
**Target date:** 2026-05-01

**Status (2026-04-29):** Implemented via `scripts/smoke_local_demo.sh`, `make smoke-local-demo`,
and updated setup documentation.

**Specific**
- Add one repo-level smoke script that proves the gateway and Flutter app can connect locally without
  manual file edits.
- Move any remaining hardcoded runtime assumptions into explicit config or documented defaults.
- Update docs so the local demo path is one obvious sequence, not a scavenger hunt.

**Primary files**
- `scripts/`
- `Makefile`
- `README.md`
- `docs/development/setup.md`
- `apps/field_app_flutter/lib/services/api_client.dart`

**Measurable done criteria**
- A new smoke script exits `0` after verifying `/health`, `/v1/session`, and `/v1/events/stream`
- `make check` still passes
- A contributor can follow the docs and reach a connected Flutter UI in one pass

**Why this is realistic**
The repo is already close; this task is mainly about removing ambiguity and codifying the happy path.

---

### Task 2 — Lock down the shared contract strategy
**Target date:** 2026-05-05

**Status (2026-05-01):** Implemented in three slices: first with a proto-anchored contract-lock strategy, then with generated Python/Dart contract artifacts that feed the active gateway and Flutter model layers, and now with a Rust transport crate (`crates/session_proto`) that compiles the proto contract and converts the overlapping session/speaker subset into `audio_core`.

**Specific**
- Decide whether `proto/session.proto` becomes the real source of truth or whether the project will
  explicitly defer codegen and rely on a documented JSON contract for now.
- Implement the chosen approach across Rust, Python, and Flutter.

**Primary files**
- `proto/session.proto`
- `services/gateway/app/models.py`
- `apps/field_app_flutter/lib/models/`
- `crates/*`
- CI workflows if generated artifacts are added

**Measurable done criteria**
- Contract drift can no longer happen silently
- CI fails when shared model definitions diverge
- The decision is documented in code/docs, not only in chat history

**Why this is realistic**
This is a 3–4 day alignment task, not a full feature build, and it removes recurring maintenance risk.

---

### Task 3 — Unify prioritization authority
**Target date:** 2026-05-07

**Status (2026-05-01):** Implemented. Rust `focus_engine` owns the mode-aware
policy table, the gateway can now call that authority directly through the
`session_ranker` runtime bridge, and the Python gateway mirror remains in place
as the documented fallback. Shared parity vectors in
`crates/focus_engine/testdata/prioritization_vectors.tsv` still make drift fail
loudly.

**Specific**
- Pick one authoritative prioritization implementation: Rust or Python.
- Eliminate or explicitly validate the duplicate weighting logic so Focus/Crowd/Locked behavior is
  consistent everywhere.

**Primary files**
- `crates/focus_engine/src/lib.rs`
- `services/gateway/app/services/prioritizer.py`
- related tests/docs

**Measurable done criteria**
- The same ranking inputs produce the same outputs across the chosen authority boundary
- At least one cross-stack test vector validates ranking behavior
- The non-authoritative path is either removed, wrapped, or explicitly documented as derived

**Why this is realistic**
The logic is already small and well-contained; the main work is choosing ownership and proving parity.

---

### Task 4 — Harden SSE for real client behavior
**Target date:** 2026-05-12

**Status (2026-04-29):** Implemented with deterministic SSE ids, keep-alives, reconnect handling,
duplicate/stale event filtering, and expanded gateway/Flutter tests.

**Specific**
- Add deterministic integration coverage for keep-alives, reconnects, and event ordering.
- Ensure the Flutter repository handles dropped streams, duplicate events, and rapid updates safely.

**Primary files**
- `services/gateway/app/routes/events.py`
- `services/gateway/app/services/session_store.py`
- `apps/field_app_flutter/lib/services/mock_repository.dart`
- gateway and Flutter test suites

**Measurable done criteria**
- Gateway tests cover keep-alives and rebroadcast after reconnect
- Flutter tests cover reconnect + update application after reconnect
- No focused test relies on uncontrolled timeouts or flaky race conditions

**Why this is realistic**
The stream and reconnect scaffolding already exist; this task finishes the reliability work.

---

### Task 5 — Add a realistic ingest path for live demo data
**Target date:** 2026-05-15

**Status (2026-04-29):** Implemented via `/v1/mock/live-ingest` and the scripted `briefing`
scenario that drives 20+ timed updates through the existing SSE pipeline.

**Specific**
- Add a gateway endpoint or local simulator that can inject realistic speaker/transcript updates over
  time instead of only loading deterministic scene snapshots.
- Drive the Flutter UI from that feed without requiring manual refresh.

**Primary files**
- `services/gateway/app/routes/`
- `services/gateway/app/services/`
- `apps/field_app_flutter/lib/services/mock_repository.dart`
- `scripts/`

**Measurable done criteria**
- A local simulator can drive at least 20 events across 3 speakers
- Flutter visibly updates captions/status/locks from streamed events
- A scripted demo works without editing source code during runtime

**Why this is realistic**
This creates a much more convincing internal prototype without waiting for full audio integration.

---

### Task 6 — Persist session and lock state
**Target date:** 2026-05-21

**Status (2026-04-29):** Implemented with SQLite-backed session persistence and restart recovery.

**Specific**
- Replace purely in-memory gateway state with SQLite-backed persistence for current session, speakers,
  and lock state.
- Restore state on restart.

**Primary files**
- `services/gateway/app/services/session_store.py`
- new persistence module(s) under `services/gateway/app/services/`
- gateway tests/docs

**Measurable done criteria**
- After gateway restart, the previous session mode and speaker lock state are restored
- Tests cover save + restart + restore behavior
- The fallback mock scene is still available for reset/demo scenarios

**Why this is realistic**
SQLite is enough for the next milestone and avoids premature distributed-state complexity.

---

### Task 7 — Add minimal configuration and deployment hygiene
**Target date:** 2026-05-28

**Status (2026-04-29):** Implemented with repo-root `.env` support, `.env.example`,
`services/gateway/app/config.py`, `services/gateway/Dockerfile`, and Flutter base-URL overrides.

**Specific**
- Add environment-based config for gateway runtime values and Flutter base URL.
- Add `.env.example` or equivalent documented config template.
- Add a basic gateway container recipe and startup docs.

**Primary files**
- `services/gateway/app/config.py` (new)
- `.env.example` (new)
- `services/gateway/Dockerfile` (new)
- `README.md`
- `docs/development/setup.md`

**Measurable done criteria**
- Gateway URL/config can be changed without editing source files
- Fresh setup docs mention the supported config knobs
- Gateway can run via either local venv or container

**Why this is realistic**
This is foundational plumbing that pays off immediately for contributors and test environments.

---

### Task 8 — Add minimal auth, logging, and readiness checks
**Target date:** 2026-06-03

**Status (2026-04-29):** Implemented with optional bearer auth for mutating routes,
structured request logging, and `/livez` + `/readyz`.

**Specific**
- Add simple token-based auth for mutating gateway endpoints.
- Add structured request logging and explicit readiness/liveness endpoints.

**Primary files**
- `services/gateway/app/main.py`
- `services/gateway/app/routes/`
- new middleware/logging/config files

**Measurable done criteria**
- Mutating endpoints reject requests without a configured token
- Logs include request method/path/status and a request identifier
- Separate readiness/liveness checks exist and are documented

**Why this is realistic**
This is enough hardening for an internal or limited beta without requiring a full IAM stack.

---

### Task 9 — Ship one real translation adapter
**Target date:** 2026-05-06

**Status (2026-04-29):** Implemented with a configurable LibreTranslate-compatible adapter in the gateway.

**Specific**
- Select one translation provider and add a gateway adapter for text-in/text-out translation.
- Wire the adapter into the existing session/speaker path so live ingest or manual speaker updates can produce real translated captions.
- Keep mock mode available when credentials are absent or the provider is disabled.

**Primary files**
- `services/gateway/app/services/` (new adapter modules)
- `services/gateway/app/config.py`
- `services/gateway/app/routes/mock.py` or a dedicated adapter entry path
- gateway docs/tests

**Measurable done criteria**
- Given source caption text and a target language, the gateway returns a real translated caption through
  the existing session/speaker models
- A local developer can enable the provider with documented env vars and see real translated captions in the existing Flutter speaker lanes
- Mock mode remains available when no provider is configured
- Adapter success/failure paths are tested

**Why this is realistic**
Text translation is the smallest real-provider step and unlocks a meaningful product demo before audio/TTS.

---

### Task 10 — Add cross-stack integration smoke coverage
**Target date:** 2026-05-09

**Status (2026-04-29):** Implemented via `scripts/smoke_integration_demo.sh`, `make smoke-integration-demo`,
and `docs/development/integration-smoke-runbook.md`.

**Specific**
- Add one repeatable integration-smoke path that exercises the gateway, live ingest, persistence, and Flutter client expectations together.
- Write a short demo runbook for contributors and internal reviewers.

**Primary files**
- `docs/testing/strategy.md`
- `docs/development/setup.md`
- `scripts/`
- targeted gateway/Flutter test or smoke harness files

**Measurable done criteria**
- A contributor can follow one short runbook and validate the end-to-end demo in under 10 minutes on a fresh machine
- The smoke path proves `/v1/events/stream`, `/v1/mock/live-ingest`, and Flutter live updates all work together
- The testing docs explicitly describe what remains manual vs. automated

**Why this is realistic**
The platform pieces already exist; this task makes the working system demonstrable and repeatable.

---

### Task 11 — Build the first internal beta release candidate
**Target date:** 2026-05-13

**Status (2026-04-29):** Release prep implemented. The docs, changelog, and release workflow now support internal-beta candidate runs; cutting the actual candidate is the remaining operational step.

**Specific**
- Execute the release checklist against the new baseline.
- Produce gateway packages and Flutter release artifacts for internal testing.
- Add a short internal runbook for smoke verification.

**Primary files**
- `docs/development/release-checklist.md`
- `docs/development/release-builds.md`
- `CHANGELOG.md`
- `.github/workflows/release.yml`
- internal smoke/runbook docs

**Measurable done criteria**
- `make check`, `make gateway-package`, and `make flutter-release-android` pass
- Release artifacts are produced and documented
- The changelog reflects the implemented features since `0.1.0`
- An internal tester can follow the runbook to launch the gateway, connect the Flutter app, and exercise a live ingest demo without source edits

**Why this is realistic**
By this point the repo should be beyond “starter template” and into repeatable internal release territory.

## Longer-horizon tasks (after the internal beta candidate)

These are important, but they should not block the next finish line:

1. direct Rust reuse/bridge in Python or Flutter runtime paths
2. audio capture and diarization integration
3. TTS / translated-audio output and mix metadata
4. richer operator actions (mute, batch lock, history/timeline)
5. stronger auth/roles and multi-user coordination
6. production-grade observability and scaling
7. signed mobile/desktop distribution and store submission

## Recommended execution order

If we continue immediately, the best order is:

1. bridge the Rust prioritization authority directly into runtime call paths
2. cut and smoke an internal beta candidate using the release-prep path
3. plan the next wave for audio capture, diarization, and TTS

## Success summary

We should consider the current phase complete when:

- generated/shared contract handling no longer depends on hand-maintained strings in the active gateway/Flutter paths
- Rust authority is reused directly where it materially reduces mirrored logic
- internal release artifacts can be built and smoke-tested without source edits
