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
- [ ] Update `CHANGELOG.md`:
	- keep `## [Unreleased]` current
	- refresh the `### Internal beta candidate` notes before each candidate build
	- only promote notes into a numbered heading when cutting a tagged semver release
- [ ] Review `docs/development/release-builds.md` so the artifact matrix still matches the repo's actual capabilities.
- [ ] Review `docs/development/internal-beta-smoke-runbook.md` so the smoke path still matches the shipped artifact set.
- [ ] Decide whether Flutter artifacts should embed `FIELD_APP_API_BASE_URL` at build time:
	- leave it blank for the default emulator/local-host smoke path
	- set it explicitly for device or hosted-gateway testing
- [ ] Keep `LANGUAGE_GATEWAY_AUTH_TOKEN` unset for packaged-app smoke verification.
	The current Flutter build supports base-URL injection, but it does **not** inject bearer tokens for write routes.

## Build and validate the candidate

- [ ] Run repository validation on a clean branch:
	- `make check`
	- `make smoke-local-demo`
- [ ] Build the local artifacts that are practical on your host:
	- `make gateway-package`
	- `make source-bundle`
	- `make flutter-release-android` (only when Flutter + Android SDK are available locally)
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
- [ ] Trigger `POST /v1/mock/live-ingest` from the host side and verify live lane/status/caption updates in the app.
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
