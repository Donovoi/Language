# Language

Language is a mock-first monorepo for a multi-speaker, focus-aware live translation system.
This pass delivers a production-style starter template that lets contributors validate the Rust core, run a FastAPI gateway, and launch a shared Flutter client shell for Android, iOS, macOS, and Windows.

## Architecture summary

- **Flutter** owns the cross-platform operator UI in `apps/field_app_flutter`.
- **Rust** owns typed realtime session and speaker primitives plus prioritization policy in `crates/`.
- **Python** owns the local gateway and mock scene orchestration in `services/gateway`.
- **Protobuf** defines the shared contract in `proto/session.proto`.

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

### Rust checks

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

### Gateway checks and run

```bash
cd services/gateway
python -m pip install -e '.[dev]'
python -m ruff check .
python -m pytest
uvicorn app.main:app --reload
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
- a FastAPI gateway with health, session, speaker, reset, and mock-scene endpoints
- a Flutter operator shell that renders speaker lanes and mode changes from gateway-compatible data
- CI workflows for Rust, Python, and Flutter validation

Still intentionally deferred:

- live audio capture and diarization
- translation and TTS provider integration
- Flutter-to-Rust FFI wiring beyond planning docs
- persistence, auth, and production deployment concerns

## Near-term roadmap

1. generate Rust and Python bindings from `proto/session.proto`
2. replace mock scene generation with realtime event ingestion
3. connect Flutter mode switching to live gateway state updates
4. add transport for streaming speaker events
5. add translation and synthesis provider adapters behind the gateway

## Contribution expectations

- keep changes explicit and maintainable
- update ADRs or interface docs when boundaries move
- add tests whenever behavior could silently drift
- prefer mock-safe, deterministic defaults over clever abstractions

See `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/development/release-checklist.md`, and `docs/development/versioning.md` for contribution and release details.
