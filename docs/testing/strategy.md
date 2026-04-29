# Testing Strategy

## Why this exists
The repository spans multiple runtimes, so the testing plan must stay simple and repeatable.
This document records the quality gates that keep the starter template deterministic.

## Boundary it owns
- Rust validates typed domain logic with formatting, linting, and unit tests.
- Python validates route behavior and ranking shape with Ruff and pytest.
- Flutter validates widget structure and analyzer health after generating local platform runners.
- Repository-level smoke coverage validates the cross-stack local demo path with automated gateway checks plus a short manual Flutter verification pass.

## Current validation commands

### Rust
```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

### Python
```bash
cd services/gateway
python -m pip install -e '.[dev]'
python -m ruff check .
python -m pytest
```

### Flutter
```bash
cd apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter analyze
flutter test
```

### Cross-stack smoke
```bash
make smoke-local-demo
make smoke-integration-demo
```

- `make smoke-local-demo` is the fast baseline check for `GET /health`, `GET /v1/session`, and a deterministic SSE preview.
- `make smoke-integration-demo` starts an isolated gateway on `127.0.0.1:8010`, verifies `GET /health`, streams progressive updates from `GET /v1/events/stream` while `POST /v1/mock/live-ingest` is active, then restarts the gateway and confirms the persisted session survives across `GET /v1/session` and the first SSE snapshot.
- The manual Flutter follow-up lives in `docs/development/integration-smoke-runbook.md` and verifies the visible lane updates, lock messaging, and reconnect behavior in under 10 minutes.

## What is intentionally deferred
There is now one repeatable cross-stack smoke path, but there are still no device-farm,
load, or performance suites.
The live Flutter acceptance pass remains manual by design so contributors can confirm the
visible lane behavior against their target host or emulator.
