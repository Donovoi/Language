# Testing Strategy

## Why this exists
The repository spans multiple runtimes, so the testing plan must stay simple and repeatable.
This document records the quality gates that keep the starter template deterministic.

## Boundary it owns
- Rust validates typed domain logic with formatting, linting, and unit tests.
- Python validates route behavior and ranking shape with Ruff and pytest.
- Flutter validates widget structure and analyzer health after generating local platform runners.
- Repository-level smoke coverage validates the cross-stack local demo path with automated gateway checks plus a short manual Flutter verification pass.

## Current validation commands

### Rust
```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

### Python
```bash
cd services/gateway
python -m pip install -e '.[dev]'
python -m ruff check .
python -m pytest
```

### Flutter
```bash
cd apps/field_app_flutter
flutter create . --platforms=android,ios,macos,windows
rm -f test/widget_test.dart
flutter pub get
flutter analyze
flutter test
```

### Cross-stack smoke
```bash
make smoke-local-demo
make smoke-integration-demo
```

- `make smoke-local-demo` is the fast baseline check for `GET /health`, `GET /v1/session`, and a deterministic SSE preview.
- `pwsh -NoProfile -File scripts/smoke_local_demo.ps1` is the Windows-native equivalent for hosts without `make`, Bash, or WSL, and honors the same gateway host/port/Python/timeout environment overrides.
- `pwsh -NoProfile -File scripts/check_local.ps1` is the Windows-native equivalent for the top-level `make check`; it refreshes the gateway venv by default, enforces the gateway's Python `>=3.11,<3.14` range, and `-SkipFlutter` is explicitly partial and should not be used as full release validation.
- `pwsh -NoProfile -File scripts/package_local.ps1 -Python <path-to-supported-python>` is the Windows-native source-bundle and gateway-package path; it refuses dirty-tree artifacts by default and refreshes the gateway venv/dist only when gateway packages are built.
- `make smoke-integration-demo` starts an isolated gateway on `127.0.0.1:8010`, verifies `GET /health`, streams progressive updates from `GET /v1/events/stream` while `POST /v1/mock/live-ingest` is active, then restarts the gateway and confirms the persisted session survives across `GET /v1/session` and the first SSE snapshot.
- The manual Flutter follow-up lives in `docs/development/integration-smoke-runbook.md` and verifies the visible lane updates, lock messaging, and reconnect behavior in under 10 minutes.

### Audio evaluation smoke
```bash
make audio-eval-check
make audio-eval-real-speech-check
make audio-eval-real-speech-chunked-check
make audio-eval-live-capture-contract-check
make audio-eval-live-capture-check
make audio-eval-playback-suppression-contract-check
make audio-eval-playback-suppression-check
make live-microphone-capture-check
```

- `make audio-eval-check` runs the disposable `audio-eval` Docker profile, renders deterministic
  synthetic overlap/language/volume/playback-loopback fixtures, and writes a baseline JSON report
  under `artifacts/audio_eval/`.
- The same check now includes a strict oracle diarization scorer path. Future Sortformer, pyannote,
  or provider adapters should write JSONL predictions and score them with
  `scripts/benchmark_diarization_fixture.py`.
- This is a fixture and metric-plumbing gate. It does not claim real diarization, ASR, translation,
  voice similarity, or source-suppression quality until real model adapters and licensed speech
  fixtures are added.
- `make audio-eval-real-speech-check` adds one tiny networked LibriSpeech mix with two distinct
  speakers, known overlap, and known levels. It proves the real-speech download/decode/annotation
  path and oracle scoring, but still does not prove noisy-room, multilingual, realtime, or
  suppression behavior.
- `make audio-eval-real-speech-chunked-check` scores prefix chunks and reports first speech
  detection latency, overlap detection latency, and label-set changes. Future online diarizers must
  produce this report before they are treated as realtime candidates.
- `make audio-eval-live-capture-contract-check` validates capture scorer failure modes.
  `make audio-eval-live-capture-check` replays fixture audio as timestamped PCM chunks, checks
  schema, jitter, gaps/reorders, no future samples, level fields, and a hash chain. It must stay
  `fixture_replay` prototype evidence until a microphone adapter writes the product report.
- `make live-microphone-capture-check` runs on the host with `sounddevice`/PortAudio callbacks and
  writes the product live-capture report. The June 12, 2026 host run passed with 25 chunks over
  2.0 s, 16 kHz mono capture, max callback interarrival jitter 0.509 ms, 18.5 ppm frame-clock drift,
  callback wall-clock fallback timestamps, no callback warnings, and verified WAV/chunk hashes.
- `make audio-eval-playback-suppression-contract-check` validates the conservative playback scorer.
  `make audio-eval-playback-suppression-check` writes volume-matched translated-playback surrogate
  artifacts, ducks source residuals, checks clipping and hashes, and records an explicit
  non-cancellation claim. It is prototype evidence only, not product suppression proof.
- `make audio-eval-sortformer-contract-check` validates the NVIDIA Sortformer adapter parser in the
  small audio-eval image. `audio-eval-sortformer-real-speech-check` and
  `audio-eval-sortformer-real-speech-chunked-check` run the optional NeMo profile and write the same
  JSONL/report shape as pyannote.
- `make audio-eval-sortformer-online-real-speech-check` runs the same fixture through Sortformer's
  stateful `forward_streaming_step` path, using model-card low-latency settings and latency gates
  based on the documented input buffer.
- `make audio-eval-sortformer-rolling-real-speech-check` feeds raw PCM fixture chunks in arrival
  order, extracts features per available input buffer, and reports whether future samples entered
  the model path.
- `make audio-eval-whisper-rolling-translation-check` runs faster-whisper on rolling oracle-diarized
  slices from the mixed multilingual FLEURS signal. It reports language flips, first partial latency,
  final latency, and translation token F1 before any spoken playback path is trusted.
- `make audio-eval-oracle-tse-check` and
  `make audio-eval-whisper-oracle-tse-translation-check` establish the target-speaker extraction
  upper bound. They score per-speaker extracted audio, then run Whisper on rolling oracle-TSE slices
  so real separators have a clear downstream quality target.
- `make audio-eval-mixture-passthrough-tse-check` and
  `make audio-eval-whisper-mixture-passthrough-tse-translation-check` establish the lower-bound
  negative control. They must fail separation/translation quality gates in expected ways, proving
  the scorer catches copied mixed audio before a real model is integrated.
- `make audio-eval-enrolled-oracle-tse-check` and
  `make audio-eval-enrolled-mismatch-tse-check` add speaker-enrollment metadata to the TSE contract.
  The oracle check is a same-speaker upper bound; the mismatch check must fail target-audio quality
  gates while proving enrollment files, hashes, and target/mismatch expectations are validated.
- `make audio-eval-whisper-enrolled-oracle-tse-translation-check` feeds the enrolled oracle artifacts
  through the same downstream Whisper bridge so future enrollment-conditioned models have a clear
  translation target.
- `make audio-eval-speechbrain-sepformer-check` runs the first real separator spike in its own
  disposable SpeechBrain profile. It writes the shared TSE JSONL, uses oracle stream assignment only
  for measurement, and must beat mixture passthrough before it is considered useful.
- `make audio-eval-whisper-speechbrain-sepformer-translation-check` feeds those external SepFormer
  TSE artifacts through the same rolling Whisper translation harness used by oracle and passthrough
  TSE checks.
  The June 10, 2026 run is expected to warn: SepFormer did not beat mixture passthrough on the
  FLEURS overlap fixture, and downstream Whisper reached primary-language accuracy 0.25 with mean
  translation token F1 0.088346.
- `make audio-eval-wesep-contract-check` and `make audio-eval-wesep-check` run the first real
  audio-enrollment target-speaker extraction profile. It validates enrollment paths, hashes,
  durations, same-speaker cue expectations, extracted-audio hashes, and passthrough comparison gates.
- `make audio-eval-whisper-wesep-translation-check` feeds WeSep artifacts through the older diagnostic
  Whisper bridge. The June 12, 2026 run still uses oracle diarization windows, so the release gate
  rejects it as product proof even though it passes with primary-language accuracy 1.0 and mean
  translation token F1 0.176282.
- `make audio-eval-whisper-wesep-causal-translation-check` is the current product streaming
  translation proof. It first runs the accepted WeSep component check, then drives Whisper with
  causal rolling Sortformer diarization over the FLEURS overlap fixture. The June 12, 2026 run used
  20-step chunks plus 20-step right context, recorded DER-like 0.13699, first-speech and overlap
  latency 3200 ms, causality_ok true, and downstream Whisper primary-language accuracy 1.0 with mean
  translation token F1 0.206838. The report still declares the external TSE-artifact caveat so direct
  TSE on causal windows remains a follow-up.
- `make audio-eval-fallback-tts-contract-check` and `make audio-eval-fallback-tts-check` generate
  consent-safe neutral English fallback TTS with eSpeak NG in the audio-eval container. The June 12,
  2026 run produced four hashed WAV files, declared `voice_clone_status=fallback_voice`,
  `voice_similarity_claim=not_claimed`, matched each output to the source level with max level error
  0.0 dB, and kept max peak at -5.066 dBFS.
- `make audio-eval-same-voice-candidate-contract-check` and
  `make audio-eval-same-voice-candidate-check` validate externally generated same-voice candidate
  WAVs. The scorer requires explicit consent evidence, bundled reference/output/similarity artifacts,
  non-clone audio, source-matched levels, peak headroom, and a sidecar score that matches the
  release gate's recomputed acoustic proxy. Proxy-only candidates remain validation artifacts, not
  same-voice release proof.
- `make audio-eval-speechbrain-voice-similarity-contract-check` and
  `make audio-eval-speechbrain-voice-similarity-check` add the stronger optional SpeechBrain ECAPA
  ASV pass for same-voice candidate reports. It verifies reference/output WAV hashes and speaker
  verification scores, but remains candidate evidence until calibrated against human listener
  similarity and release-safe generator outputs.
- `make release-audio-gate` is the product-release blocker, not a research convenience target. It
  reads the current report artifacts. Live microphone capture and causal diarization now pass with
  product-specific evidence on this host, WeSep satisfies the real TSE component gate, and causal
  streaming speech translation plus fallback TTS now pass. Real-room playback/suppression remains the
  only release blocker. It rejects bare passing stubs and
  prototype fixtures, and it independently validates live-capture WAV/chunk artifacts before accepting
  microphone evidence. This is not tamper-proof provenance for coherent local artifacts, so warning-only
  model checks and scaffolds should never be used as release proof.

## What is intentionally deferred
There is now one repeatable cross-stack smoke path, but there are still no device-farm,
load, or performance suites.
The live Flutter acceptance pass remains manual by design so contributors can confirm the
visible lane behavior against their target host or emulator.
