# Release Checklist

Use this checklist for both supported release paths:

- **Internal beta candidate** — manual artifact run for controlled testers
- **Tagged repository release** — annotated `vMAJOR.MINOR.PATCH` tag plus GitHub release publication

The first internal beta candidate is still based on the current aligned `0.1.0` package metadata.
Until a new semver tag is cut, identify the candidate by **version + commit SHA + workflow run** rather
than by inventing a second package version line.

## Before building artifacts

- [ ] Confirm which path you are taking: internal beta candidate or tagged release.
- [ ] Confirm the candidate commit/branch and intended tester audience.
- [ ] Keep versions aligned across:
	- `CHANGELOG.md`
	- `services/gateway/pyproject.toml`
	- `apps/field_app_flutter/pubspec.yaml`
	- `crates/audio_core/Cargo.toml`
	- `crates/focus_engine/Cargo.toml`
	- `crates/session_proto/Cargo.toml`
- [ ] Update `CHANGELOG.md`:
	- keep `## [Unreleased]` current
	- refresh the `### Internal beta candidate` notes before each candidate build
	- only promote notes into a numbered heading when cutting a tagged semver release
- [ ] Review `docs/development/release-builds.md` so the artifact matrix still matches the repo's actual capabilities.
- [ ] Review `docs/development/internal-beta-smoke-runbook.md` so the smoke path still matches the shipped artifact set.
- [ ] Decide which Flutter runtime values should be embedded at build time:
	- leave it blank for the default emulator/local-host smoke path
	- set `FIELD_APP_API_BASE_URL` explicitly for device or hosted-gateway testing
	- leave `FIELD_APP_AUTH_TOKEN` blank when gateway auth is unset
	- set `FIELD_APP_AUTH_TOKEN` only for controlled internal smoke gateways, then rotate the matching gateway token after the run

## Build and validate the candidate

- [ ] Run repository validation on a clean branch:
	- `make check`
	- Windows without `make`: `pwsh -NoProfile -File scripts/check_local.ps1`
	- `make smoke-local-demo`
	- Windows without Bash/WSL: `pwsh -NoProfile -File scripts/smoke_local_demo.ps1`
- [ ] For a product release that claims the realtime audio-loop goal, run the hard audio evidence gate:
	- `make live-microphone-capture-check` on the release host or target capture device
	- `make release-audio-gate`
	- Treat any missing, warning-only, or failing audio report as a release blocker.
	- Review `artifacts/release/audio-gate-report.md` for the operator handoff, but keep
	  `artifacts/release/audio-gate-report.json` as the authoritative pass/fail artifact.
	- Confirm live microphone evidence has matching WAV/chunk JSONL artifacts that the gate validates.
	- Confirm prototype-only evidence is listed separately and is not being used to satisfy live
	  microphone capture, causal diarization, real TSE/separation, streaming speech translation,
	  same-voice/fallback TTS, or playback source-suppression gates.
	- Confirm headphone/earpiece evidence, if used, is labeled
	  `headphone_isolated_not_true_cancellation` and is not described as true room cancellation.
	- Confirm fallback TTS reports contain hashed WAV artifacts, level matching, and no same-voice
	  claim unless a same-speaker benchmark has passed.
	- Confirm the gate rejects bare `summary.passed=true` reports and requires product-specific
	  evidence fields for each release-blocking subsystem.
- [ ] Build the local artifacts that are practical on your host:
	- `make gateway-package`
	- `make source-bundle`
	- Windows without `make`: `pwsh -NoProfile -File scripts/package_local.ps1 -Python <path-to-supported-python>`
	- `make flutter-release-android` (only when Flutter + Android SDK are available locally)
	- For local Windows source/gateway handoff, verify `dist/local-release-artifacts/manifest.md` and
	  `dist/local-release-artifacts/SHA256SUMS.txt`; releasable handoffs must show `dirty_tree: false`.
- [ ] Use `.github/workflows/release.yml` for the complete artifact matrix:
	- `workflow_dispatch` with `channel=internal-beta` for internal candidate builds
	- `push` of an annotated `vX.Y.Z` tag for a publishable repository release
- [ ] Confirm the workflow uploads the expected artifact groups:
	- source bundle
	- gateway packages
	- Android artifacts
	- iOS/macOS/Windows artifacts from matching runners
	- manifest + `SHA256SUMS.txt`
- [ ] Confirm any unsigned Flutter artifacts are acceptable for the intended audience.

## Smoke-verify the internal beta candidate

- [ ] Follow `docs/development/internal-beta-smoke-runbook.md` end to end.
- [ ] Verify the gateway responds on `/livez`, `/readyz`, and `/v1/session`.
- [ ] Verify the app shows `Live updates connected` after launch.
- [ ] Verify mode switching, session reset, and speaker lock/unlock from the app.
- [ ] Trigger the mock live-ingest demo from the app and verify live lane/status/caption updates.
- [ ] Record the tested commit SHA, workflow run URL, artifact names, and any known caveats.

## Promote or publish

- [ ] For another internal beta candidate, keep the notes in `## [Unreleased]`, refresh the internal-beta bullets, and rerun the workflow from the next candidate commit.
- [ ] For a tagged release, move the release notes into `## [X.Y.Z]`, create an annotated tag `vX.Y.Z`, and push it.
- [ ] Confirm the GitHub release picked up every workflow artifact, including the manifest/checksum bundle.
- [ ] Point testers or consumers at the updated runbook/docs that match the release.

## After the run

- [ ] Refresh `## [Unreleased]` once new work starts.
- [ ] Capture release follow-ups before planning the next version.
- [ ] Track remaining productionization items explicitly: signing, notarization, installer generation, auth injection, and broader device smoke coverage.
