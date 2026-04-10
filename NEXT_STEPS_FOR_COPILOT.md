# Next Steps for Copilot

This file is the **single implementation handoff** for the `Donovoi/Language` repository.

The repository already contains an initial monorepo shape with:
- Rust workspace root
- `crates/audio_core`
- `crates/focus_engine`
- `services/gateway`
- `proto/session.proto`
- early product and architecture docs

Your job is to turn this into a **usable cross-platform starter template** for a multi-speaker, focus-aware live translation system.

---

# 1. High-level product target

Build an MVP-oriented monorepo for a system that:
- tracks multiple speakers
- assigns each speaker a dynamic priority
- exposes speaker state to a client UI
- supports future streaming translation and TTS backends
- works across iPhone, Android, macOS, and Windows

Do **not** try to solve full live translation in this pass.
This pass is about building a strong, production-style foundation.

---

# 2. Architectural decisions to preserve

Keep these decisions unless there is a very strong reason to change them.

## 2.1 Client shell
Use **Flutter** for the shared cross-platform client shell.

Reasons:
- one codebase for Android, iOS, macOS, and Windows
- fast UI iteration
- good enough for the first field client and desktop operator UI

## 2.2 Shared realtime core
Use **Rust** for deterministic, reusable, latency-sensitive logic.

Rust should own:
- domain types for speakers and sessions
- priority scoring primitives
- mixer-safe state transitions
- bounded queue/buffer abstractions later
- future FFI boundary for Flutter

## 2.3 Backend and ML/service integration
Use **Python** for the gateway and model-heavy service integration.

Python should own:
- API layer
- future diarization adapters
- future translation provider adapters
- future TTS provider adapters
- evaluation and experiment scripts

## 2.4 Contracts
Use **protobuf** for shared contracts.

The existing `proto/session.proto` should be expanded rather than replaced with ad-hoc JSON-only contracts.

---

# 3. Immediate objective

Finish the repository so that a developer can:
1. clone it
2. bootstrap local tooling
3. run a Python gateway locally
4. run a Flutter client locally
5. see mock speaker events rendered in the client
6. see prioritization logic applied consistently
7. run tests and lint checks from CI

This is the minimum viable starter template.

---

# 4. Work order

Follow this exact order.

## Phase 1: repository hygiene and docs

### 4.1 Rewrite the root `README.md`
Replace the current small README with a strong project overview containing:
- project purpose
- architecture summary
- current repository layout
- quickstart section
- current status section
- near-term roadmap
- contribution expectations

### 4.2 Add missing docs
Create these files:
- `docs/architecture/adrs/0001-monorepo.md`
- `docs/architecture/adrs/0002-flutter-rust-python-split.md`
- `docs/architecture/adrs/0003-mock-first-development.md`
- `docs/api/gateway.md`
- `docs/testing/strategy.md`

### 4.3 Keep docs pragmatic
Do not write vague aspirational text.
Every doc should answer:
- why this exists
- what boundary it owns
- what is intentionally deferred

---

## Phase 2: finish the monorepo structure

Create the following directories if they do not already exist:

```text
apps/
  field_app_flutter/
crates/
  audio_core/
  focus_engine/
services/
  gateway/
python/
  research/
proto/
docs/
  architecture/
    adrs/
  api/
  development/
  product/
  testing/
.github/
  workflows/
```

Also add placeholder `.gitkeep` files where needed for empty directories.

---

## Phase 3: finish the Rust workspace

The Rust workspace should compile and test cleanly.

### 5.1 `crates/audio_core`
Expand this crate to define core domain types.

Add:
- `SessionId`
- `SpeakerId`
- `LanguageCode`
- `SpeakerState`
- `SessionState`
- `PriorityScore`
- simple validation helpers

Suggested module layout:

```text
crates/audio_core/src/
  lib.rs
  ids.rs
  speaker.rs
  session.rs
  priority.rs
```

Requirements:
- use small, explicit types
- avoid premature async code here
- keep types serializable later if needed
- add unit tests for constructors and invariants

### 5.2 `crates/focus_engine`
Turn this into a policy crate for speaker prioritization.

Add:
- `FocusInputs`
- `FocusPolicy`
- `rank_speakers()`
- `top_n_active_speakers()`
- test coverage for sorting and policy weighting

The first implementation can be simple but structured for future extension.

Initial policy inputs should include:
- current priority base score
- active/inactive status
- optional user lock flag
- optional front-facing bias
- optional persistence bonus

Do not add DSP here yet.
This is a scoring and selection crate, not an audio processing crate.

### 5.3 Rust quality bar
Add:
- `cargo fmt`
- `cargo clippy`
- `cargo test`

Make sure the workspace can pass these in CI.

---

## Phase 4: expand protobuf contracts

Update `proto/session.proto` so it is actually useful.

Add message types such as:
- `SessionState`
- `SpeakerState`
- `SpeakerEvent`
- `PriorityUpdate`
- `ClientConfig`
- `SessionMode`

Suggested fields for `SpeakerState`:
- `speaker_id`
- `display_name`
- `language_code`
- `priority`
- `active`
- `is_locked`
- `last_updated_unix_ms`

Suggested enum for `SessionMode`:
- `SESSION_MODE_UNSPECIFIED`
- `FOCUS`
- `CROWD`
- `LOCKED`

Do not overcomplicate the schema.
It is acceptable to start with one proto file.

---

## Phase 5: finish the Python gateway

The gateway should become a small but clean FastAPI service.

### 6.1 Service structure
Refactor `services/gateway` into:

```text
services/gateway/
  pyproject.toml
  README.md
  app/
    __init__.py
    main.py
    models.py
    routes/
      __init__.py
      health.py
      sessions.py
      speakers.py
    services/
      __init__.py
      prioritizer.py
      mock_events.py
```

### 6.2 Required endpoints
Implement these endpoints:
- `GET /health`
- `GET /v1/session`
- `POST /v1/session/reset`
- `GET /v1/speakers`
- `POST /v1/speakers`
- `GET /v1/mock/scene`

### 6.3 Behavior
The gateway should:
- keep an in-memory session state
- accept a list of speaker states or events
- sort them consistently using a service-level prioritizer
- return a stable JSON shape
- expose a mock scene endpoint for the Flutter client

### 6.4 Modeling
Use Pydantic models for:
- speaker input
- session response
- mock scene response

### 6.5 Testing
Add tests using `pytest` for:
- health endpoint
- speaker sorting behavior
- reset behavior
- mock scene shape

---

## Phase 6: create the Flutter app shell

This is one of the most important next steps.

Create a new Flutter app under:
- `apps/field_app_flutter`

### 7.1 Minimal Flutter structure
Create at least:

```text
apps/field_app_flutter/
  pubspec.yaml
  analysis_options.yaml
  lib/
    main.dart
    app.dart
    models/
      speaker.dart
      session_state.dart
    services/
      api_client.dart
      mock_repository.dart
    features/
      session/
        session_screen.dart
        speaker_lane.dart
        priority_badge.dart
```

### 7.2 First screen behavior
The first screen should show:
- app title
- current session mode
- a list of speakers
- each speaker’s language code
- each speaker’s active status
- each speaker’s priority value
- a visual indication of the top speaker

### 7.3 Data source
The Flutter app can start with either:
- hardcoded mock JSON matching the gateway, or preferably
- live calls to the local gateway mock endpoints

### 7.4 State management
Use a simple state approach at first.
Recommended order of preference:
1. `ChangeNotifier` or `ValueNotifier`
2. `Riverpod` only if you keep it minimal and clean

Do **not** overengineer state management in this phase.

### 7.5 Design goals
The UI should feel like an operator/field tool, not a consumer toy.
Use:
- clear typography
- compact cards or rows
- obvious top-speaker highlight
- no unnecessary animations

---

## Phase 7: define the Rust/Flutter integration plan

Do not fully wire FFI yet unless it stays small.
But do prepare the structure for it.

### 8.1 Add an ADR
Write `docs/architecture/adrs/0002-flutter-rust-python-split.md` explaining:
- why Flutter is the client shell
- why Rust is the shared performance-sensitive core
- why Python remains the service layer
- why realtime translation logic is not in the Flutter layer

### 8.2 Add a placeholder integration note
Create:
- `docs/development/flutter-rust-bridge-plan.md`

Describe how you would later use `flutter_rust_bridge` or equivalent.
This should be a plan document, not a full implementation yet.

---

## Phase 8: CI and quality gates

Create GitHub Actions workflows under `.github/workflows/`.

### 9.1 Rust CI
Add a workflow that runs:
- `cargo fmt --check`
- `cargo clippy --all-targets --all-features -- -D warnings`
- `cargo test --workspace`

### 9.2 Python CI
Add a workflow that runs:
- install dependencies for `services/gateway`
- `ruff check`
- `pytest`

### 9.3 Flutter CI
Add a workflow that runs:
- Flutter setup
- `flutter pub get`
- `flutter analyze`
- `flutter test`

### 9.4 Combined expectations
CI should fail clearly and early.
Do not hide failing checks behind optional steps.

---

## Phase 9: better developer ergonomics

### 10.1 Improve the `Makefile`
Expand the root `Makefile` so that these commands work:
- `make bootstrap`
- `make check`
- `make rust-check`
- `make python-check`
- `make flutter-check`
- `make gateway-run`
- `make flutter-run`

These can call underlying commands without being overly fancy.

### 10.2 Add service READMEs
Create:
- `services/gateway/README.md`
- `apps/field_app_flutter/README.md`
- `crates/audio_core/README.md`
- `crates/focus_engine/README.md`

Each should say:
- what it owns
- how to run/test it
- what it deliberately does not own

---

## Phase 10: mock-first product flow

Add a clean mock path so developers can demo the system without real audio.

### 11.1 Mock speaker scene
Create a fixed or rotating mock scene in the gateway with 4–6 speakers.
Each mock speaker should include:
- `speaker_id`
- `language_code`
- `priority`
- `active`
- optional lock state

### 11.2 Example modes
Support simple mode changes:
- `FOCUS`
- `CROWD`
- `LOCKED`

### 11.3 UI reflection
The Flutter app should visibly show how priorities change when the mode changes.
This is important because it proves the product concept before real translation is wired in.

---

# 5. Coding style expectations

## Rust
- explicit, small modules
- avoid macros unless they improve clarity
- avoid unnecessary trait abstraction early
- prioritize readability and testability

## Python
- simple FastAPI layout
- clear Pydantic models
- services should be small and single-purpose
- keep business logic outside route handlers

## Flutter
- feature-oriented folders
- small widgets
- UI should read from models, not parse raw maps in widgets
- no giant `main.dart`

---

# 6. Design patterns to use

Use these patterns where appropriate.

## Recommended
- repository pattern for client-side data access
- service layer in Python for business logic
- policy object / strategy object for speaker prioritization
- value objects in Rust for core IDs and typed fields
- ADRs for architecture decisions

## Avoid for now
- event sourcing
- CQRS
- microservices split
- heavy dependency injection frameworks
- premature plugin architecture

This repository should stay understandable to a single engineer.

---

# 7. Definition of done for this pass

This pass is done when all of the following are true:

1. root README is strong and accurate
2. docs explain the architecture and next boundaries clearly
3. Rust workspace builds and tests cleanly
4. Python gateway runs and returns mock speaker data
5. Flutter app runs and renders speaker lanes from mock/gateway data
6. CI exists for Rust, Python, and Flutter
7. `make check` and the targeted check commands are useful
8. the repository feels like a real starter template, not a random file dump

---

# 8. Suggested implementation sequence inside the PR

Use this exact order in the PR if possible:

1. docs and README
2. Rust workspace cleanup
3. protobuf expansion
4. Python gateway structure and tests
5. Flutter app shell
6. CI workflows
7. Makefile improvements
8. final polish and README verification

---

# 9. Important constraints

- Keep the repository public-safe.
- Do not add secrets or real API keys.
- Do not add real surveillance, interception, or covert collection features.
- Keep the current code provider-agnostic.
- Use mock data for translation/audio until the structure is stable.

---

# 10. Final instruction

Prefer a **clean, documented, boringly maintainable foundation** over cleverness.

The real win of this pass is not advanced AI.
The real win is a repository that makes the next 10 implementation steps obvious and safe.
