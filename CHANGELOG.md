# Changelog

All notable changes to this project are documented in this file.

The repository follows the versioning guidance in `docs/development/versioning.md`.

## [Unreleased]

### Internal beta candidate

Repository prep for the first internal beta release candidate based on the current `0.1.0` baseline.

#### Added

- Internal beta smoke runbook in `docs/development/internal-beta-smoke-runbook.md` covering the current supported verification path: local gateway plus Android release app plus host-triggered live ingest.
- Release manifest/checksum output in `.github/workflows/release.yml` so internal candidate runs can be tracked by artifact set, commit SHA, and workflow run.

#### Changed

- Tightened `docs/development/release-checklist.md` around the real internal-beta flow, including changelog expectations, auth/base-URL caveats, and smoke-verification steps.
- Tightened `docs/development/release-builds.md` to the current repo capabilities and host matrix: local source/gateway/Android builds, plus workflow-built iOS/macOS/Windows unsigned artifacts on matching runners.
- Updated `.github/workflows/release.yml` so manual candidate runs can be labeled as `internal-beta`, optionally inject `FIELD_APP_API_BASE_URL` into Flutter release builds, and publish a manifest/checksum bundle alongside the artifacts.

## [0.1.0] - First release

Initial public baseline for the mock-first monorepo.

### Added

- Flutter, Rust, Python, and protobuf repository structure for the live translation MVP.
- Typed Rust session, speaker, and prioritization foundations in `crates/`.
- FastAPI mock gateway endpoints for health, session control, speaker state, reset, and mock scenes.
- Flutter operator shell that renders gateway-compatible session and speaker views.
- Initial architecture, API, testing, and development documentation for contributors.
