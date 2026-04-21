# Release Build Guide

## Release scope

The repository release is currently defined as:

- a source release tagged as `vMAJOR.MINOR.PATCH`
- Python gateway source and wheel packages from `services/gateway`
- unsigned Flutter build artifacts for Android, iOS, macOS, and Windows

Signed store-ready mobile or desktop packages are intentionally out of scope for this pass.

## Version alignment

Before building artifacts, keep these versions aligned:

- `CHANGELOG.md`
- `services/gateway/pyproject.toml`
- `apps/field_app_flutter/pubspec.yaml`
- `crates/audio_core/Cargo.toml`
- `crates/focus_engine/Cargo.toml`

This repository starts at `0.1.0` and tags releases as `v0.1.0`.

## Local build commands

### Source validation

```bash
cd <repository-root>
make check
```

### Gateway packages

```bash
cd <repository-root>/services/gateway
python -m pip install build
python -m build
```

Outputs in `services/gateway/dist/`:

- source distribution (`*.tar.gz`)
- wheel distribution (`*.whl`)

### Flutter Android artifacts

```bash
cd <repository-root>/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build apk --release
flutter build appbundle --release
```

### Flutter iOS artifact (unsigned)

```bash
cd <repository-root>/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build ios --release --no-codesign
```

### Flutter macOS artifact

```bash
cd <repository-root>/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build macos --release
```

### Flutter Windows artifact

```bash
cd <repository-root>/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build windows --release
```

## Automated release workflow

`.github/workflows/release.yml` is the release workflow.
It:

1. verifies version alignment
2. reruns Rust, Python, and Flutter validation
3. builds gateway packages
4. builds unsigned Flutter release artifacts on matching runners
5. uploads all artifacts to the workflow run
6. attaches artifacts to the GitHub release when triggered from a `v*` tag

## Deferred release work

The workflow does not yet handle:

- Android signing keys or Play Store metadata
- iOS provisioning profiles, notarization, or App Store delivery
- macOS signing or notarization
- Windows signing or installer generation
- production gateway deployment packaging or runtime secrets

Those remain manual follow-up work before shipping a production release.
