# Changelog

All notable changes to this project are documented in this file.

The repository follows the versioning guidance in `docs/development/versioning.md`.

## [Unreleased]

### Internal beta candidate

Repository prep for the first internal beta release candidate based on the current `0.1.0` baseline.

#### Added

- Internal beta smoke runbook in `docs/development/internal-beta-smoke-runbook.md` covering the current supported verification path: local gateway plus Android release app plus host-triggered live ingest.
- Release manifest/checksum output in `.github/workflows/release.yml` so internal candidate runs can be tracked by artifact set, commit SHA, and workflow run.
- Generated shared-contract bindings for the gateway and Flutter, plus the Rust `crates/session_proto` transport crate for the proto-backed session/speaker subset.
- Product-loop speaker metadata for detected language confidence, input/output dBFS levels, overlapping speaker ids, voice clone status, translated-audio stream ids, playback latency, and original-voice suppression diagnostics.
- Disposable Docker-based core test environment with build/check/shell/destroy/purge Make targets, a Windows PowerShell wrapper, and agent guidance for future environment-sensitive changes.
- Playback/suppression prototype benchmark for volume-matched translated playback, source-residual ducking, clipping/hash gates, and explicit non-cancellation diagnostics.
- Fixture-backed live PCM capture benchmark scaffold with chunk schema, timing, gap/reorder, streaming-boundary, level, and hash-chain gates.
- Host live microphone capture benchmark using `sounddevice`/PortAudio callbacks, with product-gate evidence for device identity, timing jitter, chunk order, input level, and hashed captured audio.
- Hard release audio evidence gate that writes a product-readiness report, rejects stubs/prototypes as product proof, and fails until live capture, causal diarization, real TSE/separation, streaming translation, TTS, and room loopback evidence are present.
- Live microphone release evidence now requires independently validated WAV/chunk JSONL hashes, WAV header checks, chunk continuity, timestamp monotonicity, recomputed timing drift, and an explicit local-artifact-coherence trust boundary.
- Polarity-invariant target-speaker extraction scoring, plus WeSep postprocess metadata for runtime-available mixture-correlation polarity correction and enrollment-RMS level normalization without reference stems.
- Host real-room playback/suppression loopback runner with device listing, sentinel route-probe triage, route/sample-rate/channel sweep triage, device-path qualification, bounded device sweep triage, contract self-test, hashed room WAV evidence, release-gate WAV recomputation, bounded alignment, calibration audibility/fidelity checks, and honest failing SoundWire/WASAPI evidence that remains the final audio-release blocker.
- Explicit `source_suppression_mode` session/event contract field so speaker lanes distinguish unavailable suppression, overlay ducking, headphone isolation, and measured true cancellation instead of inferring claims from a dB value.
- SpeechBrain ECAPA same-voice candidate scorer with disposable Docker/PowerShell targets, WAV hash revalidation, ASV score gates, and an explicit candidate-evidence-only release boundary.
- Manual headphone/earpiece release kit now writes `manual-recording-checklist.md` beside the JSON manifest so physical listener-ear take capture has exact filenames, setup notes, and follow-up commands.
- Manual headphone/earpiece recording doctor now writes `manual-recording-status.md` beside the JSON status so missing WAVs, label placeholders, score-ready state, and next commands are readable during physical evidence collection.
- Windows-native `scripts/smoke_local_demo.ps1` verifies the local gateway health/session/SSE smoke path without requiring `make`, Bash, or WSL.
- Windows-native `scripts/check_local.ps1` mirrors the top-level `make check` validation path, enforces the gateway's supported Python range, and labels no-Flutter host runs as partial.
- Windows-native `scripts/package_local.ps1` builds source bundles and gateway distributions without `make`, refusing dirty-tree release artifacts by default and writing a scope-specific local artifact manifest plus checksums.
- Windows-native `scripts/headphone_isolation_local.ps1` creates a small host-audio venv for headphone/earpiece virtual-lab, manual-kit, route-probe, and capture commands without relying on `make` or Docker audio device passthrough.
- Headphone/earpiece no-audio preflight writes JSON and Markdown planning reports with device classification, route candidates, recommended guided/manual path, explicit physical listener-ear input confirmation before guided capture, and a `release_proof=false` detractor verdict.
- Guided headphone/earpiece PortAudio capture now requires a passing preflight report bound to the selected route, and release scoring rejects unbound guided-capture evidence.
- The hard release audio gate now writes a Markdown operator handoff beside the JSON report so release blockers, physical-evidence hardware reminders, and guided/manual collection commands are readable without weakening the machine-checked gate.
- The release audio handoff now embeds the current headphone/earpiece manual recording status when present, including score-ready state, issue counts, and the exact release-gate rerun command without treating the status as release evidence.
- The release audio handoff now also embeds the latest headphone/earpiece preflight status when present, including the recommended path, displayed or selected route candidate, next generated command, and physical-input confirmation state as non-evidentiary operator context.
- The release audio handoff now includes the latest headphone/earpiece route-probe diagnosis when present, including opened devices, route levels, blocking reasons, and next actions while keeping route probes triage-only.
- Quiet headphone/earpiece route-probe failures now print a copy/pasteable same-route retry command in the release handoff so operators can test a cautious 6 dB gain increase without weakening release evidence gates.
- Real-room route probes now emit structured blocking reasons/next actions, and the release handoff can summarize the current laptop mic/speaker route-probe diagnosis without treating it as release evidence.
- Real-room route-probe scoring now records aligned-overlap fraction and rejects tiny edge alignments or stale reports missing that field, preventing wide lag windows from making distorted routes look artificially good.
- `collect-headphone-evidence` now wraps manual headphone/earpiece kit prep, optional raw WAV import, readiness checks, score handoff, and release-gate commands into one non-evidentiary collection plan for the remaining source-suppression release blocker.
- The release audio handoff now embeds the current headphone/earpiece evidence collection plan when present, including readiness, next actions, and the next physical-recording command while keeping it non-evidentiary.
- `collect-headphone-evidence` can now read the latest headphone/earpiece preflight report to fill concrete source/headphone output devices in the non-evidentiary `play-manual` command.
- `collect-headphone-evidence` now creates a raw listener-ear recording dropbox with exact WAV filenames and import commands so phone/USB recorder exports have a concrete landing path.
- `collect-headphone-evidence` now auto-imports the three raw listener-ear WAVs when they are present in the dropbox, while refusing implicit overwrites and keeping the wrapper non-evidentiary.

#### Changed

- Tightened `docs/development/release-checklist.md` around the real internal-beta flow, including changelog expectations, auth/base-URL caveats, and smoke-verification steps.
- Tightened `docs/development/release-builds.md` to the current repo capabilities and host matrix: local source/gateway/Android builds, plus workflow-built iOS/macOS/Windows unsigned artifacts on matching runners.
- Updated `.github/workflows/release.yml` so manual candidate runs can be labeled as `internal-beta`, optionally inject `FIELD_APP_API_BASE_URL` into Flutter release builds, and publish a manifest/checksum bundle alongside the artifacts.
- The gateway now prefers the Rust prioritization authority at runtime through `session_ranker`, with the parity-tested Python prioritizer retained as the documented fallback when the native runner is unavailable.
- Re-anchored the README, product MVP, architecture overview, gateway docs, mock scene, live ingest flow, and Flutter speaker lanes around the original realtime voice-translation goal rather than a caption-only mock console.
- Promoted WeSep enrolled target-speaker extraction from warning-only research probe into a hard component check when real-model acceptance gates pass, while keeping the oracle-windowed Whisper-after-WeSep bridge as diagnostic evidence.
- Split real-model TSE release acceptance from oracle-ceiling diagnostics so the release gate can accept a useful model that beats mixture passthrough while still exposing non-oracle-quality gaps.
- Tightened the release gate so oracle-diarization Whisper-after-TSE reports no longer satisfy product streaming speech translation proof.
- Added a causal Sortformer plus Whisper-after-WeSep translation bridge and made it the default streaming translation evidence for the release gate.
- Added a consent-safe eSpeak NG fallback TTS benchmark with hashed, level-matched WAV artifacts, disposable container targets, and release-gate artifact validation.
- Added a same-voice candidate evidence validator with disposable targets, consent-evidence bundling,
  hashed source/reference/output/similarity artifacts, non-clone checks, source-level/peak
  validation, a recomputed built-in acoustic proxy, and release-gate revalidation for
  `same_voice_candidate` reports.

## [0.1.0] - First release

Initial public baseline for the mock-first monorepo.

### Added

- Flutter, Rust, Python, and protobuf repository structure for the live translation MVP.
- Typed Rust session, speaker, and prioritization foundations in `crates/`.
- FastAPI mock gateway endpoints for health, session control, speaker state, reset, and mock scenes.
- Flutter operator shell that renders gateway-compatible session and speaker views.
- Initial architecture, API, testing, and development documentation for contributors.
