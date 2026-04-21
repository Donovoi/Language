# Release Build Guide

## Release scope

The repository release is currently defined as:

- a source release tagged as `vMAJOR.MINOR.PATCH`
- Python gateway source and wheel packages from `services/gateway`
- unsigned Flutter build artifacts for Android, iOS, macOS, and Windows

Signed store-ready mobile or desktop packages are intentionally out of scope for this pass.

## Version alignment

Before building artifacts, keep these versions aligned:

- `/home/runner/work/Language/Language/CHANGELOG.md`
- `/home/runner/work/Language/Language/services/gateway/pyproject.toml`
- `/home/runner/work/Language/Language/apps/field_app_flutter/pubspec.yaml`
- `/home/runner/work/Language/Language/crates/audio_core/Cargo.toml`
- `/home/runner/work/Language/Language/crates/focus_engine/Cargo.toml`

This repository starts at `0.1.0` and tags releases as `v0.1.0`.

## Local build commands

### Source validation

```bash
cd /home/runner/work/Language/Language
make check
```

### Gateway packages

```bash
cd /home/runner/work/Language/Language/services/gateway
python -m pip install build
python -m build
```

Outputs:

- `services/gateway/dist/language_gateway-<version>.tar.gz`
- `services/gateway/dist/language_gateway-<version>-py3-none-any.whl`

### Flutter Android artifacts

```bash
cd /home/runner/work/Language/Language/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build apk --release
flutter build appbundle --release
```

### Flutter iOS artifact (unsigned)

```bash
cd /home/runner/work/Language/Language/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build ios --release --no-codesign
```

### Flutter macOS artifact

```bash
cd /home/runner/work/Language/Language/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build macos --release
```

### Flutter Windows artifact

```bash
cd /home/runner/work/Language/Language/apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter build windows --release
```

## Automated release workflow

`/home/runner/work/Language/Language/.github/workflows/release.yml` is the release workflow.
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
