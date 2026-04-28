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
- a FastAPI gateway with health, session, speaker, reset, speaker lock/unlock, mock-scene, and persistent SSE endpoints
- a Flutter operator shell that renders speaker lanes, mode changes, translated-caption fields, live SSE status, and speaker lock controls from gateway-compatible data
- CI workflows for Rust, Python, Flutter, and proto-backed contract-lock validation

Still intentionally deferred:

- live audio capture and diarization
- translation and TTS provider integration
- Flutter-to-Rust FFI wiring beyond planning docs
- persistence, auth, and production deployment concerns

## Near-term roadmap

1. bridge the Rust prioritization authority directly into runtime call paths if the current mirrored gateway layer becomes too costly
2. replace deterministic mock scenes with a realistic live ingest path
3. persist session state and externalize runtime configuration
4. extend the contract-lock strategy into generated bindings once the runtime boundaries settle
5. add translation and synthesis provider adapters behind the gateway

For the detailed, time-bound execution plan, see `docs/development/smart-implementation-plan.md`.
For the prioritization ownership record, see `docs/development/prioritization-authority.md`.

## Contribution expectations

- keep changes explicit and maintainable
- update ADRs or interface docs when boundaries move
- add tests whenever behavior could silently drift
- prefer mock-safe, deterministic defaults over clever abstractions

See `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/development/release-builds.md`, `docs/development/release-checklist.md`, and `docs/development/versioning.md` for contribution and release details.
