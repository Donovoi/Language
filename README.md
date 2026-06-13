# Language

Language is a realtime speech translation app for noisy, multi-speaker rooms.
The product goal is to listen to overlapping speech from multiple people, detect each source language,
translate it to English, synthesize the English audio in the same speaker voice at the same perceived
volume, and suppress the original source voice so the user hears the translated mix instead.

The repo is still mock-first, but the mock stack is now shaped around that audio loop instead of only
captions and speaker priority.

## Architecture summary

- **Flutter** owns the cross-platform operator UI in `apps/field_app_flutter`.
- **Rust** owns typed realtime session and speaker primitives plus the authoritative prioritization policy in `crates/`.
- **Python** owns the local gateway, mock scene orchestration, text translation adapter, and provider-facing audio metadata in `services/gateway`.
- **Protobuf** is the canonical contract ledger in `proto/session.proto`, and CI now validates the gateway models, Flutter models, and the overlapping Rust subset against it.

## Repository layout

- `apps/field_app_flutter` Flutter field console
- `crates/audio_core` typed Rust domain model for sessions and speakers
- `crates/focus_engine` Rust prioritization policy and ranking helpers
- `crates/session_proto` generated Rust protobuf bindings and transport/domain conversion helpers
- `services/gateway` FastAPI mock gateway and session API
- `proto` shared protobuf contracts
- `fixtures/audio_eval` versioned audio-evaluation fixture truth
- `docs` architecture, API, testing, and development notes
- `research` Robin-oriented implementation question matrix
- `CHANGELOG.md` release notes for shipped versions
- `python/research` reserved space for future evaluation and experiment code

## Quickstart

### Bootstrap local SDKs and dev env

```bash
bash scripts/bootstrap_dev.sh
```

This installs or reuses a local Flutter SDK in `~/.local/share/flutter`, adds a launcher at
`~/.local/bin/flutter`, and creates `services/gateway/.venv` for Python development.

### Rust checks

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

### Gateway checks and run

```bash
cd services/gateway
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest
.venv/bin/python -m uvicorn app.main:app --reload
```

### Flutter checks and run

```bash
cd apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter analyze
flutter test
flutter run
```

### Monorepo shortcuts

```bash
make rust-check
make python-check
make flutter-check
make gateway-run
make flutter-run
```

### Disposable core test environment

Use Docker when you want a clean, buildable, destroyable environment for the non-mobile checks:

```bash
make dev-env-build
make dev-env-check
make dev-env-destroy
make dev-env-purge
```

This runs contract, Rust, and gateway checks in the `docker/dev` core environment without depending on
host Python/Rust setup. See `docs/development/disposable-test-environments.md`.

On Windows without `make`, use `pwsh -NoProfile -File scripts/dev_container.ps1 check`.

### Disposable audio evaluation environment

Use the separate audio profile when changing capture, diarization, separation, translation audio,
voice/TTS, playback, or suppression work:

```bash
make audio-eval-build
make audio-eval-check
make audio-eval-real-speech-check
make audio-eval-real-speech-chunked-check
make audio-eval-translation-check
make audio-eval-live-capture-contract-check
make audio-eval-live-capture-check
make audio-eval-playback-suppression-contract-check
make audio-eval-playback-suppression-check
make real-room-playback-suppression-list-devices
make real-room-playback-suppression-contract-check
make real-room-playback-suppression-probe-route
make real-room-playback-suppression-sweep-routes
make real-room-playback-suppression-qualify-device
make real-room-playback-suppression-sweep-devices
make real-room-playback-suppression-check
make headphone-isolation-contract-check
make headphone-isolation-list-devices
HEADPHONE_ISOLATION_PROBE_ROUTE_ARGS='--measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT' make headphone-isolation-probe-route
make headphone-isolation-virtual-lab
make audio-eval-purge
```

On Windows without `make`, use
`pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-check`.

The check renders deterministic overlap/language/volume/playback-loopback fixtures and writes a JSON
report under `artifacts/audio_eval/`. See `docs/testing/audio-eval-harness.md`.

`audio-eval-real-speech-check` downloads two tiny LibriSpeech dummy rows at runtime, mixes a
two-speaker English overlap fixture with known levels, and runs the same oracle scorer path. It is a
licensed real-speech smoke test, not proof of live-room performance.
`audio-eval-real-speech-chunked-check` runs the same fixture through prefix chunks so future adapters
must report decision latency, overlap detection timing, and label stability.
`audio-eval-translation-check` adds a tiny FLEURS multilingual fixture with Spanish, French, German,
and English source clips plus English reference text for language-ID and translation gates.
`audio-eval-live-capture-check` replays fixture audio as timestamped mono PCM chunks and validates
chunk schema, timing, no gaps/reorders, streaming boundaries, level fields, and artifact hashes. It is
explicitly fixture evidence and cannot satisfy the product live-microphone release gate.
`audio-eval-playback-suppression-check` adds a synthetic translated-playback overlay with
source-level matching, source-residual ducking, clipping gates, artifact hashes, and an explicit
`ducking_masking_simulation_not_true_cancellation` claim. It proves playback gain staging and honest
suppression metadata only; it is not room-cancellation evidence.

The real-room playback/suppression check also runs on the host audio stack, not inside Docker:

```bash
make real-room-playback-suppression-list-devices
make real-room-playback-suppression-contract-check
make real-room-playback-suppression-probe-route
make real-room-playback-suppression-sweep-routes
make real-room-playback-suppression-qualify-device
make real-room-playback-suppression-sweep-devices
make real-room-playback-suppression-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 real-room-playback-suppression-list-devices
pwsh -NoProfile -File scripts/dev_container.ps1 real-room-playback-suppression-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 real-room-playback-suppression-probe-route
pwsh -NoProfile -File scripts/dev_container.ps1 real-room-playback-suppression-sweep-routes
pwsh -NoProfile -File scripts/dev_container.ps1 real-room-playback-suppression-qualify-device
pwsh -NoProfile -File scripts/dev_container.ps1 real-room-playback-suppression-sweep-devices
pwsh -NoProfile -File scripts/dev_container.ps1 real-room-playback-suppression-check
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-list-devices
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-probe-route --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-virtual-lab
```

The June 12, 2026 SoundWire/WASAPI measurements currently fail release: the 48 kHz device
qualification recorded audible calibration but failed reference fidelity
(`source_corr=-0.000594`, `translated_corr=-0.000034`). The full aligned -18 dB room run recorded
83.799 dB source residual reduction, but calibration/reference fidelity and translated-output
preservation both failed. The release gate recomputes room metrics from the WAV recordings and
requires audible, reference-faithful source/translated calibration. This is the right kind of red light
for the last audio-loop gate.
Run the device qualification target first on a candidate input/output pair; a failing qualification
means the room path cannot currently produce release evidence, even before cancellation is tested.
Run `probe-route` before speech qualification when the route is uncertain. It writes
`artifacts/audio_eval/runs/real-room-route-probe/route-probe-report.json` with
`release_proof=false`, a chirp sentinel reference, recording hashes, matched confidence, lag, gain,
clipping, and route errors. A passing route probe is only a prerequisite diagnostic.
For the private-listener fallback path, use the guided headphone/earpiece capture after listing
devices and probing the candidate routes. The probe plays a short chirp through the source output and
headphone output, records with the listener-ear measurement input, and writes
`artifacts/audio_eval/runs/headphone-earpiece-route-probe/headphone-route-probe-report.json` with
`release_proof=false`; it is route triage, not release evidence. Proceed to guided capture only when
the command exits successfully and the report has `summary.passed=true`. Add `--score-warning-only`
only when collecting a failure report from a known-bad route. The guided capture records the open-ear
source control, isolated source, and translated headphone playback with explicit PortAudio device
identities, then feeds those WAVs into the release-gated scorer:

Development-only virtual listener-ear lab:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-virtual-lab
python scripts/release_audio_gate.py --headphone-isolation-report artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/headphone-virtual-lab-report.json --json *> artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/release-gate-virtual-rejection.json
if ($LASTEXITCODE -eq 0) { throw "expected release gate to reject the virtual listener-ear report" }
"release gate rejected the virtual listener-ear report as expected"
```

The virtual lab should pass its own scorer gates and fail the release gate. For physical release
evidence, use real device indexes from `headphone-isolation-list-devices`, then run:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-probe-route --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-capture --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT --headphone-device-label "Sony WH-1000XM6 over-ear headphones" --isolation-fixture-label "WH-1000XM6 left earcup sealed around listener-ear microphone" --measurement-microphone-label "USB/lavalier listener-ear microphone placed inside earcup"
```

The virtual lab is development evidence only: it writes
`artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/headphone-virtual-lab-report.json` with
`release_proof=false`, and the release gate must reject it. The physical release procedure and
current-hardware setup guidance live in
`docs/development/headphone-isolation-release-runbook.md`.

Use `sweep-routes` when the host route itself is uncertain. It writes
`artifacts/audio_eval/runs/real-room-route-probe-sweep/route-probe-sweep-report.json` with
`release_proof=false`, every attempted device/sample-rate/input-channel/output-channel route, failed
gates, hashes, and best-scored route diagnostics. A route-sweep candidate still has to pass
`qualify-device`, then the full room `check`. Route-probe reports reject byte-identical
reference/recording WAV hashes because that indicates a loopback/reference clone, not an acoustic
room capture.
Use `sweep-devices` only to find a candidate device path cheaply. It writes
`artifacts/audio_eval/runs/real-room-device-sweep/device-sweep-report.json` with
`release_proof=false`, every attempted pair, lag margins, device fingerprints, and failed gates.
Any candidate from the sweep must be rerun with the full `check` command and then
`scripts/release_audio_gate.py`.

The real microphone capture check runs on the host audio stack, not inside Docker:

```bash
make live-microphone-capture-list-devices
make live-microphone-capture-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 live-microphone-capture-list-devices
pwsh -NoProfile -File scripts/dev_container.ps1 live-microphone-capture-check
```

It uses `sounddevice`/PortAudio callbacks to capture a short mono PCM stream from the selected input
device, then writes ignored evidence under `artifacts/audio_eval/runs/live-microphone-capture/`.
The June 12, 2026 host run passed with 25 chunks over 2.0 s from `Microphone Array on SoundWire D`,
16 kHz mono audio, max callback interarrival jitter 0.509 ms, 18.5 ppm frame-clock drift, callback
wall-clock fallback timestamps, no callback warnings, peak -68.725 dBFS, and hashed WAV plus chunk
JSONL artifacts. The release gate independently reopens those artifacts, verifies hashes, inspects
the WAV header, and checks chunk timing/coherence before accepting the host live-capture evidence.
This is local artifact-coherence evidence, not tamper-proof provenance that a determined local actor
could not synthesize.

The optional pyannote baseline has its own heavier profile:

```bash
HF_TOKEN=... make audio-eval-pyannote-check
HF_TOKEN=... make audio-eval-pyannote-real-speech-check
HF_TOKEN=... make audio-eval-pyannote-real-speech-chunked-check
```

It writes diarization prediction JSONL and scores it with the same DER-like harness. This is an
offline/dev baseline, not realtime product proof.

The optional Sortformer profile is the first NVIDIA/NeMo online-candidate spike:

```bash
make audio-eval-sortformer-contract-check
HF_TOKEN=... make audio-eval-sortformer-real-speech-check
HF_TOKEN=... make audio-eval-sortformer-real-speech-chunked-check
HF_TOKEN=... make audio-eval-sortformer-online-real-speech-check
HF_TOKEN=... make audio-eval-sortformer-rolling-real-speech-check
```

It writes the same diarization JSONL contract as pyannote. The chunked check uses prefix reprocessing
as a proxy. The online check uses Sortformer's `forward_streaming_step` state and low-latency model-card
profile. The rolling check feeds raw PCM windows in arrival order and extracts features per available
input buffer, but still keeps the detractor-loop warning explicit until passing host microphone chunks
are fed through the rolling diarizer and translated playback/suppression are wired.

The optional Whisper profile is the first measured speech-translation baseline:

```bash
make audio-eval-whisper-contract-check
make audio-eval-whisper-translation-check
make audio-eval-whisper-rolling-contract-check
make audio-eval-whisper-rolling-translation-check
make audio-eval-oracle-tse-contract-check
make audio-eval-oracle-tse-check
make audio-eval-mixture-passthrough-tse-contract-check
make audio-eval-mixture-passthrough-tse-check
make audio-eval-enrolled-tse-contract-check
make audio-eval-enrolled-oracle-tse-check
make audio-eval-enrolled-mismatch-tse-check
make audio-eval-whisper-oracle-tse-contract-check
make audio-eval-whisper-oracle-tse-translation-check
make audio-eval-whisper-mixture-passthrough-tse-contract-check
make audio-eval-whisper-mixture-passthrough-tse-translation-check
make audio-eval-whisper-enrolled-oracle-tse-translation-check
make audio-eval-speechbrain-sepformer-contract-check
make audio-eval-speechbrain-sepformer-check
make audio-eval-whisper-speechbrain-sepformer-translation-check
make audio-eval-wesep-contract-check
make audio-eval-wesep-check
make audio-eval-whisper-wesep-translation-check
make audio-eval-live-capture-contract-check
make audio-eval-live-capture-check
make audio-eval-playback-suppression-contract-check
make audio-eval-playback-suppression-check
make live-microphone-capture-check
make real-room-playback-suppression-contract-check
make real-room-playback-suppression-probe-route
make real-room-playback-suppression-sweep-routes
make real-room-playback-suppression-qualify-device
make real-room-playback-suppression-sweep-devices
make real-room-playback-suppression-check
make release-audio-gate
```

It runs faster-whisper on oracle FLEURS source clips and writes the same language/translation JSONL
contract used by the oracle fixture. The check is warning-only because it is a tiny baseline and does
not yet include live diarization, noisy-room capture, or same-voice playback. The rolling check keeps
oracle diarization boundaries but slices audio from the mixed FLEURS room signal, records partial
predictions, and reports language flips, first partial latency, final latency, and translation token F1.
The oracle target-speaker extraction checks write per-speaker extracted-audio artifacts from fixture
stems, score interferer reduction and target-level preservation, then run Whisper on rolling oracle-TSE
slices. This is an upper bound for deciding whether real TSE is worth integrating before spoken playback.
The mixture-passthrough checks are the lower-bound negative control: they copy the mixed audio into
the TSE artifact shape and must fail the separation-quality gates, giving real TSE models a command
to beat before they are allowed near spoken playback.
The enrolled-TSE checks add the missing speaker cue to the same artifact contract. The oracle variant
writes clean same-speaker enrollment clips as an upper-bound scaffold, while the mismatched enrollment
variant deliberately pairs each target with another speaker and must fail the target-audio gates.
The SpeechBrain SepFormer check is the first real separator spike in its own disposable profile. It
uses the public WHAMR SepFormer model as blind two-speaker separation, maps unordered streams back to
stable `speaker_id` only for benchmark scoring, and then can feed those external TSE artifacts through
the same rolling Whisper translation gates.
The WeSep check is the first real audio-enrollment target-speaker extraction spike. It runs pinned
WeSep/WeSpeaker source checkouts in a separate CPU-only profile, downloads the public ModelScope
English checkpoint into the disposable WeSep cache, records enrollment paths/hashes/durations, and
then feeds its extracted clips through downstream Whisper bridge checks. The current June 12, 2026
run is a hard component check: WeSep uses runtime-available mixture-correlation polarity
correction plus enrollment-RMS level normalization, declares that no reference stems are used, beats
mixture passthrough on mean SNR/interferer reduction, and passes both the older oracle-windowed
diagnostic bridge and the causal Sortformer-driven Whisper bridge. The causal report is the current
product streaming-translation proof, while longer non-same-window enrollment and direct TSE on each
causal diarization window remain follow-ups before we trust it broadly.
`release-audio-gate` is stricter than the research checks. Live microphone capture and causal
diarization and real target-speaker extraction now have passing product-specific/component evidence on
this host. The current causal Whisper-after-WeSep bridge is driven by non-oracle rolling Sortformer
diarization and passes the streaming speech-translation gate with primary-language accuracy 1.0 and
mean translation token F1 0.206838. Consent-safe neutral fallback TTS now passes with hashed
eSpeak NG WAVs level-matched to the source speech; same-voice cloning remains a stronger follow-up,
not a release claim. Product release remains blocked until playback source-suppression evidence
passes: either true real-room cancellation or a measured headphone/earpiece mode explicitly labeled
`headphone_isolated_not_true_cancellation`. The gate rejects bare
`summary.passed=true` stubs, self-attested live-capture reports without matching WAV/chunk artifacts,
and prototype evidence such as fixture capture and playback ducking. It does not claim cryptographic
proof that coherent local capture artifacts could not be forged.

### Robin research packs

Use the sibling Robin checkout to drive evidence-backed implementation choices before adding real
audio models or providers:

```bash
python3 scripts/prepare_robin_research_pack.py
python3 scripts/prepare_robin_research_pack.py --check
python3 scripts/check_audio_corpus_catalog.py
```

The generated pack points at `../robin` by default and covers capture, diarization, separation,
speech translation, same-voice TTS, playback mixing, source suppression, and benchmark design. See
`docs/research/robin-research-gate.md`, `docs/research/audio-corpus-catalog.md`,
`docs/research/decisions/`, and
`docs/research/research-backed-implementation-backlog.md`.

## Current status

The repository now provides:

- typed Rust session and speaker primitives with prioritization tests
- Rust `focus_engine` as the documented source of truth for mode-aware ranking, with shared parity vectors that keep the Python gateway mirror honest
- proto-derived generated contract artifacts for the gateway and Flutter model layers via `scripts/generate_contract_bindings.py`
- a generated Rust transport crate in `crates/session_proto` that compiles `proto/session.proto` and converts the overlapping session/speaker subset into `audio_core`
- a direct gateway-to-Rust prioritization bridge via `crates/session_proto/src/bin/session_ranker.rs`, with `LANGUAGE_GATEWAY_PRIORITIZER_BACKEND=auto|rust|python` controlling runtime selection
- a FastAPI gateway with health/readiness, session, speaker, reset, speaker lock/unlock, mock-scene, live-ingest, persistence, and persistent SSE endpoints
- a non-mock `/v1/ingest/diarization` adapter boundary for rolling diarizer output to update speaker lanes through the persisted session/SSE contract
- a configurable LibreTranslate-compatible gateway adapter for real translated captions when provider credentials are available
- speaker/session contracts that carry detected language confidence, input/output dBFS levels, overlapping-speaker ids, voice-clone status, translated-audio stream ids, playback latency, and original-voice suppression diagnostics
- a deterministic mock live-ingest scenario that simulates overlapping speech, volume-matched English playback metadata, voice clone readiness, and overlay-reduction diagnostics through the same SSE path the real runtime will use
- disposable audio-eval Docker profiles with deterministic synthetic fixtures, baseline level/overlap gates, a DER-like diarization scorer, optional pyannote and Sortformer adapter profiles, detractor-loop reporting, and separate model-layer versus full-loop latency fields
- a curated external audio-corpus catalog for public crowd, meeting, multilingual, noise, and separation datasets with license/terms posture before large downloads
- a tiny runtime-downloaded LibriSpeech real-speech overlap fixture and pyannote/Sortformer smoke paths for catching obvious diarization failures before larger benchmarks
- a gateway diarization import boundary plus prefix, stateful-online, and rolling-PCM Sortformer benchmarks for turning model JSONL into speaker lanes with latency, causality, and label-churn accounting
- a SpeechBrain SepFormer WHAMR blind-separation spike plus external-TSE Whisper bridge for measuring real separator artifacts against oracle and mixture-passthrough controls
- a Flutter operator shell that renders speaker lanes, mode changes, translated-caption fields, audio/voice/suppression metadata, live SSE status, and speaker lock controls from gateway-compatible data
- local smoke and integration-smoke paths, repo-root `.env` config support, a gateway container recipe, optional bearer auth for mutating API routes, and internal beta release/runbook docs
- CI workflows for Rust, Python, Flutter, and proto-backed contract-lock validation

Still intentionally missing:

- live multi-speaker capture wired through diarization and separation on real overlapping speech
- provider-backed voice cloning and same-voice English TTS/audio streaming beyond the fallback path
- active noise cancellation or source-voice suppression DSP
- Flutter-to-Rust FFI wiring beyond planning docs
- broader Rust runtime reuse beyond the new prioritization bridge and transport crate
- production-grade auth, observability, and deployment hardening

## Near-term roadmap

1. improve the real-room translated playback/suppression loopback until source reduction and translated-output preservation pass together
2. benchmark listener-position residual source audibility and translated-output distortion across more than one device/position
3. run the Robin research gate for same-voice English TTS or voice conversion
4. wire the selected cloning provider/model behind the existing fallback audio metadata contract
5. keep improving direct TSE-on-causal-windows and longer-enrollment confidence
6. cut and smoke the first internal beta candidate using the product-shaped mock/live-ingest path

For the detailed, time-bound execution plan, see `docs/development/smart-implementation-plan.md`.
For the prioritization ownership record, see `docs/development/prioritization-authority.md`.
For research-backed model/provider decisions, see `docs/research/decisions/`.

## Contribution expectations

- keep changes explicit and maintainable
- update ADRs or interface docs when boundaries move
- add tests whenever behavior could silently drift
- prefer mock-safe, deterministic defaults over clever abstractions

See `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/development/release-builds.md`, `docs/development/release-checklist.md`, and `docs/development/versioning.md` for contribution and release details.
