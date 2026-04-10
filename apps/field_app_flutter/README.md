# Flutter field app

## What it owns

This app owns the shared mobile and desktop operator UI for viewing session mode, ranked speakers, and mock scene changes.

## How to run and test it

```bash
cd apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
flutter pub get
flutter analyze
flutter test
flutter run
```

## What it deliberately does not own

The Flutter layer does not yet own translation providers, audio capture pipelines, or the final Rust FFI integration. It consumes session state and presents it to operators.
