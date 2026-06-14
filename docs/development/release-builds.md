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
- `crates/session_proto/Cargo.toml`

Use the guidance in `docs/development/versioning.md` and the checklist in `docs/development/release-checklist.md`.

## Current artifact matrix

| Artifact | Primary build path | Output | Smoke-verification status | Notes |
| --- | --- | --- | --- | --- |
| Source bundle | `make source-bundle` or workflow `source-bundle` job | `dist/language-<version>-source.tar.gz`, `dist/language-<version>-source.zip` | Supported | Easiest way to hand a reviewer the exact candidate source. |
| Gateway packages | `make gateway-package` or workflow `gateway-package` job | Local build dir: `services/gateway/dist/*.tar.gz`, `services/gateway/dist/*.whl`; local handoff/workflow artifact: `language-gateway-<version>.tar.gz` plus wheel | Packaging verified | Installed packages expose `language-gateway` for source-free smoke runs. |
| Android release app | `make flutter-release-android` or workflow `flutter-android` job | release APK + AAB | **Primary smoke path** | Default Android build targets the emulator/local-host path. Set `FIELD_APP_API_BASE_URL` at workflow-dispatch time for device or hosted-gateway testing. Set the `FIELD_APP_AUTH_TOKEN` GitHub secret only for controlled auth-enabled smoke builds. |
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

After installing the gateway wheel or sdist in a virtualenv, run the packaged server with:

```bash
language-gateway --host 127.0.0.1 --port 8000
```

On Windows hosts without `make`, Bash, or WSL, use the native host smoke equivalent:

```powershell
pwsh -NoProfile -File scripts/smoke_local_demo.ps1
```

It honors the same `GATEWAY_HOST`, `GATEWAY_PORT`, `GATEWAY_PYTHON`, `REQUEST_TIMEOUT_SECONDS`, and
`SMOKE_START_TIMEOUT_SECONDS` environment overrides as `make smoke-local-demo`.
The matching Windows-native repository validation command is:

```powershell
pwsh -NoProfile -File scripts/check_local.ps1
```

Pass `-SkipFlutter` only to document a partial host run when Flutter is not available. Full release
validation still requires Flutter checks to pass locally or in `.github/workflows/release.yml`.
The plain PowerShell command refreshes `services/gateway/.venv` like the Make target; pass
`-UseExistingGatewayVenv` only for a deliberate fast local reuse run.
The gateway currently supports Python `>=3.11,<3.14`; pass `-Python <path-to-supported-python>` if
the host's default `python` is outside that range.
To build the local source bundle and gateway packages on Windows without `make`, run:

```powershell
pwsh -NoProfile -File scripts/package_local.ps1 -Python <path-to-supported-python>
```

The packaging script refuses a dirty tree by default because the source bundle is built from
`HEAD`. Pass `-AllowDirty` only for a deliberate local throwaway artifact.
When building gateway packages, the script deletes and recreates `services/gateway/dist/` and
refreshes `services/gateway/.venv`. Use `-Action source-bundle` when you only need source archives and
do not want Python or gateway venv changes. Every successful run also writes a scope-specific local
artifact handoff folder at `dist/local-release-artifacts/` with `manifest.md` and `SHA256SUMS.txt`;
gateway sdists are copied there with the same `language-gateway-<version>.tar.gz` name used by the
workflow. This is a subset of the workflow manifest and does not include Flutter artifacts or
workflow run metadata. If `-AllowDirty` is used, the manifest records `dirty_tree: true` and
`allow_dirty: true` so the handoff cannot be mistaken for a clean release build.

For a release that claims the full realtime audio product goal, add the strict evidence gate after
the relevant audio-eval reports have been generated:

```bash
make live-microphone-capture-check
make release-audio-gate
```

The host live-microphone check writes the capture report consumed by the gate. The gate independently
validates the referenced WAV and chunk JSONL artifacts before accepting that report. On the current
June 12, 2026 evidence, live capture, causal diarization, real TSE, causal translation, and fallback
TTS pass; the gate is still expected to fail until playback source-suppression has passing evidence:
either true real-room cancellation or a measured headphone/earpiece mode explicitly labeled as not
true room cancellation.

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

## Flutter runtime injection

The current Flutter client supports build-time runtime injection with:

- `FIELD_APP_API_BASE_URL`
- `FIELD_APP_AUTH_TOKEN`

The release workflow accepts the base URL as an optional `workflow_dispatch` input and forwards it to
every Flutter release build. It reads `FIELD_APP_AUTH_TOKEN` from a GitHub secret, not a visible
workflow input, and forwards it only when the secret is configured.

- Leave it blank for the default local smoke path:
	- Android emulator uses `http://10.0.2.2:8000`
	- other platforms use `http://127.0.0.1:8000`
- Set it explicitly when the candidate should point at a hosted or device-reachable gateway.
- Leave `FIELD_APP_AUTH_TOKEN` unset when `LANGUAGE_GATEWAY_AUTH_TOKEN` is unset.
- Set `FIELD_APP_AUTH_TOKEN` only for controlled internal smoke gateways; app-embedded tokens are not
  production secret storage, so rotate the matching gateway token after the smoke run.

## Automated release workflow

`.github/workflows/release.yml` is the repository artifact workflow.

### Internal beta candidate flow

Run the workflow manually with:

- `channel=internal-beta`
- optional `field_app_api_base_url=<url>` when the artifacts should point at a non-default gateway
- optional repository secret `FIELD_APP_AUTH_TOKEN` when the app artifacts need authenticated write controls

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
4. trigger the live-ingest demo from the app and watch live lane updates

## Deferred release work

The workflow still does **not** handle:

- Android signing keys or Play Store metadata
- iOS provisioning profiles, signing, notarization, or App Store delivery
- macOS signing or notarization
- Windows signing or installer generation
- packaged gateway service management beyond the current `language-gateway` foreground command
- production gateway deployment packaging or runtime secret management

Those remain manual follow-up work before a production release.
