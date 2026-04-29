# Release Build Guide

## Current release channels

The repository currently supports two related artifact flows:

- **Internal beta candidate** — a manual run of `.github/workflows/release.yml` for controlled tester builds
- **Tagged repository release** — the same artifact matrix, plus GitHub release publication when the run is triggered from `vMAJOR.MINOR.PATCH`

For the first internal beta candidate, the aligned package metadata remains `0.1.0`.
Treat the candidate identity as **`0.1.0` + commit SHA + workflow run** until a new numbered tag is cut.

Signed, store-ready, or installer-ready packages remain intentionally out of scope for this pass.

## Version alignment

Before building artifacts, keep these files aligned:

- `CHANGELOG.md`
- `services/gateway/pyproject.toml`
- `apps/field_app_flutter/pubspec.yaml`
- `crates/audio_core/Cargo.toml`
- `crates/focus_engine/Cargo.toml`

Use the guidance in `docs/development/versioning.md` and the checklist in `docs/development/release-checklist.md`.

## Current artifact matrix

| Artifact | Primary build path | Output | Smoke-verification status | Notes |
| --- | --- | --- | --- | --- |
| Source bundle | `make source-bundle` or workflow `source-bundle` job | `dist/language-<version>-source.tar.gz`, `dist/language-<version>-source.zip` | Supported | Easiest way to hand a reviewer the exact candidate source. |
| Gateway packages | `make gateway-package` or workflow `gateway-package` job | `services/gateway/dist/*.tar.gz`, `services/gateway/dist/*.whl` | Packaging verified | The repo does not yet ship a dedicated packaged CLI wrapper; the smoke path still uses a checkout or unpacked source bundle to run the gateway. |
| Android release app | `make flutter-release-android` or workflow `flutter-android` job | release APK + AAB | **Primary smoke path** | Default Android build targets the emulator/local-host path. Set `FIELD_APP_API_BASE_URL` at workflow-dispatch time for device or hosted-gateway testing. |
| iOS unsigned app bundle | workflow `flutter-ios` job on `macos-latest` | zipped `Runner.app` | Manual follow-up | Unsigned only; build requires a macOS runner. |
| macOS app bundle | workflow `flutter-macos` job on `macos-latest` | zipped `.app` bundle | Manual follow-up | Unsigned/unnotarized. |
| Windows app bundle | workflow `flutter-windows` job on `windows-latest` | zipped runner output | Manual follow-up | Unsigned; no installer is produced yet. |
| Manifest + checksums | workflow `release-manifest` job | `manifest.md`, `SHA256SUMS.txt` | Supported | Use this to identify the exact internal beta candidate and verify artifact integrity. |

## Recommended local commands

These are the safest local validation/build steps for the current repo state:

```bash
cd <repository-root>
make check
make smoke-local-demo
make gateway-package
make source-bundle
```

If the local host also has Flutter stable plus the Android SDK configured, you can add:

```bash
cd <repository-root>
make flutter-release-android
```

### Host-specific caveats

- **Linux**: practical local release work is source bundle, gateway packaging, smoke checks, and usually Android artifacts.
- **macOS**: required for the iOS and macOS artifact jobs.
- **Windows**: required for the Windows artifact job.

Do not document iOS/macOS/Windows release builds as a generic Linux-local path; those require matching hosts or GitHub Actions runners.

## Flutter base-URL injection

The current Flutter client supports build-time base-URL injection with:

- `FIELD_APP_API_BASE_URL`

The release workflow now accepts this as an optional `workflow_dispatch` input and forwards it to every Flutter release build.

- Leave it blank for the default local smoke path:
	- Android emulator uses `http://10.0.2.2:8000`
	- other platforms use `http://127.0.0.1:8000`
- Set it explicitly when the candidate should point at a hosted or device-reachable gateway.

The current app does **not** inject a bearer token, so packaged app smoke tests should keep `LANGUAGE_GATEWAY_AUTH_TOKEN` unset when write controls need to work.

## Automated release workflow

`.github/workflows/release.yml` is the repository artifact workflow.

### Internal beta candidate flow

Run the workflow manually with:

- `channel=internal-beta`
- optional `field_app_api_base_url=<url>` when the artifacts should point at a non-default gateway

That flow:

1. verifies version alignment and changelog readiness
2. reruns Rust, Python, and Flutter validation
3. builds the source, gateway, and Flutter artifact set on matching runners
4. uploads channel-labeled artifact groups to the workflow run
5. adds a manifest and `SHA256SUMS.txt` bundle for candidate tracking and verification

### Tagged release flow

Push an annotated tag `vX.Y.Z` to run the same matrix in `release` mode.
When the tag run succeeds, the workflow also attaches the artifacts to the GitHub release.

## Smoke-verification path for the first internal beta

Use `docs/development/internal-beta-smoke-runbook.md`.

The currently documented and realistic smoke path is:

1. run the gateway locally from a checkout or unpacked source bundle
2. verify `/livez`, `/readyz`, `/v1/session`, and the repo smoke script
3. install the Android release APK on an emulator (or build with an explicit base URL for another target)
4. trigger `/v1/mock/live-ingest` from the host side and watch live lane updates in the app

## Deferred release work

The workflow still does **not** handle:

- Android signing keys or Play Store metadata
- iOS provisioning profiles, signing, notarization, or App Store delivery
- macOS signing or notarization
- Windows signing or installer generation
- packaged gateway service management/CLI ergonomics beyond the current source-first launch path
- production gateway deployment packaging or runtime secret management

Those remain manual follow-up work before a production release.
