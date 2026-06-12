# Research-Backed Implementation Backlog

This backlog turns the first research decisions into implementation work. Each item needs a disposable
smoke or benchmark path before it is treated as working.

## Phase 1: Audio Evaluation Harness

Initial smoke scaffold: `fixtures/audio_eval/v1/manifest.json`,
`scripts/audio_eval_harness.py`, `scripts/benchmark_diarization_fixture.py`,
`scripts/run_pyannote_diarization_fixture.py`, `scripts/audio_eval_check.sh`, and the `audio-eval`
Docker profiles. This first pass proves fixture, metric, oracle diarization scorer, and optional
pyannote adapter plumbing only; real-speech/model benchmarks still need to fill the adapter-specific
result blocks.

Current real-speech smoke: `scripts/prepare_real_speech_fixture.py` downloads two tiny LibriSpeech
dummy rows at runtime, mixes a two-speaker overlap fixture, and scores oracle diarization. This
improves the falsifying benchmark from synthetic tones to actual speech while keeping the detractor
warning: clean read English speech mixed in software is not live noisy multilingual capture.
`scripts/benchmark_chunked_diarization_fixture.py` adds a prefix-chunk proxy so adapter work must
report latency and label stability instead of only full-file DER-like scores.
`scripts/run_sortformer_real_speech_fixture.py` and
`scripts/run_sortformer_chunked_real_speech_fixture.py` add the NVIDIA/NeMo Sortformer adapter path
behind the same JSONL/report contract, plus a lightweight parser contract check for agents that do
not need to build the heavy NeMo image.
`scripts/run_sortformer_online_real_speech_fixture.py` adds the first stateful online Sortformer
check through `forward_streaming_step`, using the model-card low-latency profile and the same report
shape.
`scripts/run_sortformer_rolling_real_speech_fixture.py` feeds raw PCM fixture chunks in arrival
order, extracts features per available input buffer, calls the same stateful Sortformer step, and
records whether any future samples entered the model path.
`fixtures/audio_eval/external_corpora/catalog.json` and
`scripts/check_audio_corpus_catalog.py` add the first audited public-corpus acquisition layer for
crowd, meeting, multilingual, noise, and separation data before large downloads are introduced.
`scripts/benchmark_playback_suppression_fixture.py` adds the first playback/suppression prototype
gate: translated-playback surrogate level matching, source-residual ducking, clipping checks,
artifact hashes, and an explicit non-cancellation claim.
`scripts/benchmark_live_capture_fixture.py` adds the first capture contract scaffold by replaying
fixture audio as timestamped PCM chunks with schema, jitter, gap/reorder, streaming-boundary, level,
and hash-chain gates. It is deliberately marked `fixture_replay` and cannot satisfy live microphone
release evidence.
`scripts/run_live_microphone_capture.py` adds the host PortAudio microphone capture benchmark. The
June 12, 2026 Windows host run captured 25 chunks over 2.0 s from `Microphone Array on SoundWire D`
at 16 kHz mono with max callback interarrival jitter 0.509 ms, 18.5 ppm frame-clock drift, callback
wall-clock fallback timestamps, no callback warnings, and verified WAV/chunk hashes. The release gate
now reopens those artifacts and recomputes hash/timing/coherence checks before accepting the current
live microphone evidence for this host.

1. Create an audio-eval Docker profile with Python audio libraries, optional CUDA hooks, and fixture mounts.
2. Add versioned local fixtures for two-speaker overlap, language changes, whisper/shout volume changes, same-room playback loopback, and one catalog-backed real meeting or crowd-noise subset.
3. Add benchmark scripts for diarization, separation/TSE, translation, TTS, and playback/suppression.
4. Track model-layer latency separately from full-loop latency.

## Phase 2: Capture And Diarization Spike

Initial baseline scaffold: the pyannote Community-1 adapter can write prediction JSONL and use the
same scorer, but it is an offline/dev baseline and not a realtime capture implementation.
`scripts/run_pyannote_real_speech_fixture.py` now runs the same baseline on the tiny LibriSpeech mix
so pyannote failures on synthetic tones can be separated from failures on actual speech.
The Sortformer adapter scaffold runs the NVIDIA Streaming Sortformer candidate through real-speech,
prefix-chunk, stateful-online, and rolling-PCM reports. The rolling report removes the fixture-wide
feature-extraction shortcut, but still needs passing host microphone chunks fed into the rolling
diarizer, room noise, non-English speech, and translated playback loopback before it is product proof.
`services/gateway/app/services/diarization.py` maps prediction JSONL into gateway speaker lanes, and
`POST /v1/mock/diarization` provides the dev import boundary for offline baselines.

1. Implement a gateway adapter interface for diarization events.
2. Feed the passing host microphone chunks into the rolling diarizer and repeat with controlled
   overlap/non-English speech so live capture and diarization are proven together.
3. Keep pyannote Community-1 or 3.1 as the offline/dev baseline.
4. Add the enrolled-TSE oracle and mismatched-enrollment checks before any enrollment-aware model
   integration, so the adapter contract proves it carries speaker cue metadata and fails wrong-speaker
   cues visibly.
5. Use the oracle TSE upper-bound checks to choose and benchmark a real target-speaker extraction
   model on overlap/locked-speaker windows only.
6. Spike SpeechBrain SepFormer WHAMR as the first disposable blind-separation candidate and require it
   to beat the mixture-passthrough lower bound before any playback integration.
7. Use `scripts/run_whisper_tse_translation_fixture.py --tse-mode external` to push any new separator
   through the same downstream Whisper quality gates before accepting it.
8. Keep WeSep as the first accepted real audio-enrollment target-speaker extraction candidate only
   while it continues to beat mixture passthrough, preserve target level, and declare reference-free
   runtime postprocess.
9. Add a longer-enrollment fixture path for WeSep-class models; the current FLEURS fixture records
   enrollment duration and whether it meets the demo's more-than-5-second recommendation, but the
   current accepted run still needs non-same-window enrollment evidence.
10. Emit stable `speaker_id`, `overlapping_speaker_ids`, and input level metadata through the existing SSE contract.

## Phase 3: Cascaded Translation Runtime

1. Add streaming ASR/language-ID adapter abstraction.
2. Benchmark MMS LID plus ASR model language prediction for 1s/2s/4s windows.
3. Extend the measured Whisper source-clip and rolling mixed-audio baselines into a true streaming
   ASR plus NLLB/provider MT cascaded path.
4. Compare against SeamlessStreaming/SeamlessM4T and DiariST benchmark behavior before changing architecture.
5. Keep text captions as the fallback while audio synthesis is still uncertain.

## Phase 4: Same-Voice Output

1. Add a provider-agnostic voice/TTS adapter.
2. Require ephemeral reference handling and visible readiness states.
3. Benchmark VoxCPM2, CosyVoice 2/Fun-CosyVoice, and OpenVoice V2 locally if licensing/dependencies are acceptable.
4. Include provider personal-voice paths only when explicit consent and retention rules are implemented.
5. Always keep neutral fallback TTS. The June 12, 2026 eSpeak NG fallback benchmark now passes the
   release gate with hashed WAVs and level matching; same-voice cloning remains a separate research
   benchmark.

## Phase 5: Playback And Suppression

1. Add loudness/dBFS tracking and safe gain staging.
2. Add ITU P.56 active speech level and BS.1770/EBU R128 calibration references where useful.
3. Add WebRTC APM or equivalent echo/noise/AGC baseline.
4. Implement masking/ducking first, then benchmark source-suppression candidates.
5. Label speakerphone mode as translated overlay plus echo-controlled capture unless actual listener-position suppression is measured.
6. Fail open with honest diagnostics when suppression is unreliable.
7. Replace the synthetic ducking fixture with a real-room loopback benchmark before any product
   release claims original-voice suppression.

## Release Evidence Gate

`scripts/release_audio_gate.py` / `make release-audio-gate` is the hard product-release gate. It reads
the current report artifacts. Live microphone capture, causal diarization, target-speaker extraction
that beats mixture passthrough, and causal streaming speech translation after accepted TSE now have
passing evidence on the current host. Consent-safe fallback TTS also passes, while same-voice cloning
remains a future stronger mode. Real-room playback/suppression is the remaining release blocker. Keep exploratory model checks warning-only if useful,
and list prototypes as evidence only. The gate requires product-specific fields, independently
validates live-capture WAV/chunk artifacts, and rejects bare passing stubs, fixture capture,
self-attested microphone reports without matching artifacts, and synthetic playback reports as
release proof. Coherent local artifacts are artifact-coherence evidence, not tamper-proof provenance.
