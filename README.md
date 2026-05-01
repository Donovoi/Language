# Language

Language is a mock-first monorepo for a multi-speaker, focus-aware live translation system.
This pass delivers a production-style starter template that lets contributors validate the Rust core, run a FastAPI gateway, and launch a shared Flutter client shell for Android, iOS, macOS, and Windows.

## Architecture summary

- **Flutter** owns the cross-platform operator UI in `apps/field_app_flutter`.
- **Rust** owns typed realtime session and speaker primitives plus the authoritative prioritization policy in `crates/`.
- **Python** owns the local gateway and mock scene orchestration in `services/gateway`.
- **Protobuf** is the canonical contract ledger in `proto/session.proto`, and CI now validates the gateway models, Flutter models, and the overlapping Rust subset against it.

## Repository layout

- `apps/field_app_flutter` Flutter field console
- `crates/audio_core` typed Rust domain model for sessions and speakers
- `crates/focus_engine` Rust prioritization policy and ranking helpers
- `crates/session_proto` generated Rust protobuf bindings and transport/domain conversion helpers
- `services/gateway` FastAPI mock gateway and session API
- `proto` shared protobuf contracts
- `docs` architecture, API, testing, and development notes
- `CHANGELOG.md` release notes for shipped versions
- `python/research` reserved space for future evaluation and experiment code

## Quickstart

### Bootstrap local SDKs and dev env

```bash
bash scripts/bootstrap_dev.sh
```

This installs or reuses a local Flutter SDK in `~/.local/share/flutter`, adds a launcher at
`~/.local/bin/flutter`, and creates `services/gateway/.venv` for Python development.

### Rust checks

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

### Gateway checks and run

```bash
cd services/gateway
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest
.venv/bin/python -m uvicorn app.main:app --reload
```

### Flutter checks and run

```bash
cd apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter analyze
flutter test
flutter run
```

### Monorepo shortcuts

```bash
make rust-check
make python-check
make flutter-check
make gateway-run
make flutter-run
```

## Current status

The repository now provides:

- typed Rust session and speaker primitives with prioritization tests
- Rust `focus_engine` as the documented source of truth for mode-aware ranking, with shared parity vectors that keep the Python gateway mirror honest
- proto-derived generated contract artifacts for the gateway and Flutter model layers via `scripts/generate_contract_bindings.py`
- a generated Rust transport crate in `crates/session_proto` that compiles `proto/session.proto` and converts the overlapping session/speaker subset into `audio_core`
- a direct gateway-to-Rust prioritization bridge via `crates/session_proto/src/bin/session_ranker.rs`, with `LANGUAGE_GATEWAY_PRIORITIZER_BACKEND=auto|rust|python` controlling runtime selection
- a FastAPI gateway with health/readiness, session, speaker, reset, speaker lock/unlock, mock-scene, live-ingest, persistence, and persistent SSE endpoints
- a configurable LibreTranslate-compatible gateway adapter for real translated captions when provider credentials are available
- a Flutter operator shell that renders speaker lanes, mode changes, translated-caption fields, live SSE status, and speaker lock controls from gateway-compatible data
- local smoke and integration-smoke paths, repo-root `.env` config support, a gateway container recipe, optional bearer auth for mutating API routes, and internal beta release/runbook docs
- CI workflows for Rust, Python, Flutter, and proto-backed contract-lock validation

Still intentionally deferred:

- live audio capture and diarization
- TTS provider integration and translated-audio metadata
- Flutter-to-Rust FFI wiring beyond planning docs
- broader Rust runtime reuse beyond the new prioritization bridge and transport crate
- production-grade auth, observability, and deployment hardening

## Near-term roadmap

1. cut and smoke the first internal beta candidate using the release-prep path
2. plan the next wave for audio capture, diarization, and TTS
3. deepen auth/metrics/deployment hardening for external beta use

For the detailed, time-bound execution plan, see `docs/development/smart-implementation-plan.md`.
For the prioritization ownership record, see `docs/development/prioritization-authority.md`.

## Contribution expectations

- keep changes explicit and maintainable
- update ADRs or interface docs when boundaries move
- add tests whenever behavior could silently drift
- prefer mock-safe, deterministic defaults over clever abstractions

See `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/development/release-builds.md`, `docs/development/release-checklist.md`, and `docs/development/versioning.md` for contribution and release details.
