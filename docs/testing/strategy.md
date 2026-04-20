# Testing Strategy

## Why this exists
The repository spans multiple runtimes, so the testing plan must stay simple and repeatable.
This document records the quality gates that keep the starter template deterministic.

## Boundary it owns
- Rust validates typed domain logic with formatting, linting, and unit tests.
- Python validates route behavior and ranking shape with Ruff and pytest.
- Flutter validates widget structure and analyzer health after generating local platform runners.

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

## What is intentionally deferred
There are no integration, performance, or device-farm tests yet.
Those should land after the proto bindings and live event pipeline exist.
