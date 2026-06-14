# Field App Flutter

## Ownership

This Flutter app owns the cross-platform operator and field UI for the Language MVP.
It renders session mode, speaker lanes, and mock-or-gateway state for Android, iOS, macOS, and Windows.

## Run and validate

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

## Deliberately out of scope

This app does not own realtime translation, diarization, TTS, or priority policy logic.
Those boundaries stay in the Python gateway and Rust crates.
