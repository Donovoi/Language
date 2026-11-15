# Field App Flutter

## Ownership

This Flutter app owns the cross-platform operator and field UI for the Language MVP.
It renders session mode, speaker lanes, and mock-or-gateway state for Android, iOS, macOS, and Windows.

## Run and validate

Use Flutter 3.50.0 / Dart 3.14 (also pinned in Flutter CI). The app uses Flutter's standalone
`material_ui` package instead of the deprecated in-SDK Material imports.
Android uses AGP 9.3.1 / Gradle 9.5.0 and built-in Kotlin with JDK 17.

```bash
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter analyze
flutter test
flutter run
```

Use compile-time overrides when targeting a non-default gateway or an auth-enabled internal smoke
gateway:

```bash
flutter run --dart-define=FIELD_APP_API_BASE_URL=http://127.0.0.1:8000
flutter run --dart-define=FIELD_APP_AUTH_TOKEN=<internal-smoke-token>
```

## Android gateway smoke

With an Android SDK, Flutter, and the gateway Python environment installed, run from the repo root:

```bash
python scripts/smoke_android.py --device emulator-5580
```

Use the exact serial from `adb devices -l`. The runner starts an isolated, authenticated gateway,
allocates an ADB reverse tunnel, and checks connection, mode changes, speaker locking, streamed
captions, and reset on the actual Android app. It removes its tunnel and temporary gateway on exit.
It installs a debug test app on the selected device. It does not capture audio or qualify the
physical-audio release gate. Logs are written to `artifacts/android-smoke/`.

For a fresh headless Linux/KVM emulator, use `make android-vm-smoke`; see
`docs/development/disposable-test-environments.md` for prerequisites. For a physical phone, enable
USB debugging and accept the RSA authorization prompt. If testing from WSL, the phone must be
exposed to WSL's ADB server; the Windows ADB device list is separate.

The main manifest declares internet access for all builds. Debug builds allow HTTP for the
isolated local gateway; use an HTTPS gateway URL for a release deployment.

## Deliberately out of scope

This app does not own realtime translation, diarization, TTS, or priority policy logic.
Those boundaries stay in the Python gateway and Rust crates.
