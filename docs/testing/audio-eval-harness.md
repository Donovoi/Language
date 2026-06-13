# Audio Evaluation Harness

The Phase 1 harness is a model-agnostic test bed for the realtime translation loop. It creates
deterministic synthetic fixtures, renders local WAV files, checks baseline audio math, and writes a
JSON report that later model benchmarks can extend.

Run it in the disposable audio environment:

```bash
make audio-eval-build
make audio-eval-check
```

On Windows hosts without `make`:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-build
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-real-speech-chunked-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-crowd-noise-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-contract-check
```

Generated WAV files and reports are written under `artifacts/audio_eval/`, which is ignored by git.
The versioned fixture truth lives in `fixtures/audio_eval/v1/manifest.json`.

## What The First Harness Proves

- fixture generation is deterministic
- human-human overlap truth is represented
- generated WAV files have SHA-256 hashes in the annotations and report
- language labels are carried per segment
- quiet and loud source levels are preserved on rendered stems
- segment timing survives sample-rate quantization inside the configured gate
- playback loopback is represented separately from human speech
- the diarization scorer accepts model prediction JSONL with arbitrary speaker labels
- DER-like, overlap presence recall, and overlap speaker-time recall are reported for diarization
- model-layer latency and full-loop latency have separate report fields

## What It Does Not Prove Yet

The detractor objection is intentionally part of the report: synthetic tones are not speech. Passing
this harness does not prove diarization DER, ASR WER, language-ID accuracy, voice similarity, or
real room suppression. The cheapest falsifying benchmark is a small licensed real-speech overlap set
that exercises those exact measurements after the adapter layer exists.

## Tiny Real-Speech Fixture

`scripts/prepare_real_speech_fixture.py` is the first real-speech smoke layer. It downloads two
small rows from `sanchit-gandhi/librispeech_asr_dummy` through the Hugging Face Dataset Viewer API,
decodes the FLAC bytes in the disposable audio image, mixes two distinct LibriSpeech speakers with
known overlap and levels, and writes normal `annotations.json` plus an oracle diarization report.

Run it without model credentials:

```bash
make audio-eval-real-speech-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-real-speech-check
```

The source corpus is LibriSpeech/OpenSLR SLR12 under CC BY 4.0. This fixture catches broken audio
download, decode, level, overlap, annotation, and scorer plumbing on actual speech. The detractor
loop still matters: it is clean read English speech mixed by the harness, not a live noisy room,
not multilingual, and not evidence that source suppression works.

## Tiny Crowd-Noise Fixture

`scripts/prepare_crowd_noise_fixture.py` keeps the same two-speaker LibriSpeech truth, then uses
FSD50K metadata to select a clip-level CC0/CC BY Freesound crowd/chatter/applause candidate and mixes
its public preview under the spoken fixture. The default clip is FSD50K/Freesound `184833`, a CC0
crowd clip by `Gauraa`, and all downloaded audio stays under `artifacts/audio_eval/`.

Run it in the small audio image:

```bash
make audio-eval-crowd-noise-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-crowd-noise-check
```

The report records the Freesound page, preview URL, clip labels, clip license, uploader, preview hash,
noise stem hash, target dBFS, measured dBFS, and oracle diarization score against the unchanged human
speaker truth. The detractor loop remains sharp: this is real ambience, not speaker-labeled crowd
conversation, and it should be treated as a robustness gate rather than a source for voice cloning.

## Tiny Multilingual Translation Fixture

`scripts/benchmark_translation_fixture.py` is the first language-ID and into-English translation
fixture. It uses FLEURS `test` TSV metadata to pick early Spanish, French, German, and English clips,
streams only enough of each language audio archive to extract those WAV files, mixes them with overlap
and volume spread, and records English reference text from the parallel FLEURS sentence ids.

Run it in the small audio image:

```bash
make audio-eval-translation-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-translation-check
```

The report includes oracle diarization and oracle language/translation gates. Real ASR, LID, and MT
adapters should write the same `oracle_translation_predictions.jsonl` shape with their own
`adapter_id`, `detected_language_code`, `translated_text`, and partial/final latency fields. The
detractor loop is deliberate: FLEURS is multilingual read speech with parallel text, not noisy
spontaneous room translation, so passing this gate proves plumbing before model quality.

## Fixture Live-Capture Scaffold

`scripts/benchmark_live_capture_fixture.py` is the first PCM capture contract benchmark. It replays
the existing audio-eval fixture WAV files as timestamped mono PCM chunks and writes
`capture_chunks.jsonl` plus `capture-runtime-report.json`.

Run the scorer contract:

```bash
make audio-eval-live-capture-contract-check
```

Run the fixture replay:

```bash
make audio-eval-live-capture-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-check
```

The report gates `pcm_chunk_schema_valid`, `chunk_timing_jitter_within_limit`,
`no_chunk_gaps_or_reorders`, `streaming_boundary_enforced`, `level_meter_tracks_fixture`,
`capture_artifact_hash_chain_present`, and `capture_not_release_proof`. It always marks
`capture_source_kind=fixture_replay` and `release_proof=false`.
Current measured result on June 12, 2026: three fixture replay sources produced 245 PCM chunks at
16 kHz, with contiguous timestamps, no future samples, exact reassembly, and a complete source,
chunk, and reassembled-artifact hash chain.

Detractor loop: this scaffold proves capture chunk shape, virtual timing, hashability, and
reassembly only. It does not prove OS microphone permissions, audio callback jitter, device sample
rate drift, acoustic echo, noise, or live-room levels. `release-audio-gate` records it as prototype
evidence and rejects it for `live_microphone_capture_runtime`.

## Host Live Microphone Capture

`scripts/run_live_microphone_capture.py` is the first real microphone capture benchmark. It runs on
the host audio stack with `sounddevice`/PortAudio callbacks, because Docker does not reliably expose
Windows microphone devices. It writes `capture_chunks.jsonl`, `captured_microphone.wav`, and
`live-microphone-capture-report.json` under
`artifacts/audio_eval/runs/live-microphone-capture/`.

List host devices:

```bash
make live-microphone-capture-list-devices
```

Run the short capture:

```bash
make live-microphone-capture-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 live-microphone-capture-list-devices
pwsh -NoProfile -File scripts/dev_container.ps1 live-microphone-capture-check
```

The report gates `capture_source_is_microphone`, `capture_device_identity_present`,
`pcm_chunk_schema_valid`, `capture_sample_rate_stable`, `capture_duration_minimum`,
`capture_chunk_count`, `chunk_timing_jitter_within_limit`, `no_chunk_gaps_or_reorders`,
`capture_callback_status_clean`, `capture_input_not_silent`, `capture_artifact_hash_chain_present`,
`capture_timestamps_monotonic`, and `capture_release_proof`.

Current measured host result on June 12, 2026: `Microphone Array on SoundWire D` produced 25 callback
chunks over 2.0 s at 16 kHz mono, max callback interarrival jitter 0.509 ms, 18.5 ppm frame-clock
drift, callback wall-clock fallback timestamps, no callback status warnings, peak -68.725 dBFS, and
hashed WAV plus chunk JSONL artifacts. `release-audio-gate` independently verifies the WAV and JSONL
paths, SHA-256 hashes, WAV header, chunk continuity, recomputed jitter, timestamp monotonicity, and
frame-clock drift before accepting `live_microphone_capture_runtime` for the current host. This is
local artifact-coherence evidence, not tamper-proof provenance that a coherent bundle could not be
synthesized. It still does not prove mobile capture, diarization, separation, translation, TTS, or
playback suppression.

## Playback And Suppression Prototype

`scripts/benchmark_playback_suppression_fixture.py` is the first playback gain-staging and honest
suppression-metadata benchmark. It reuses the FLEURS multilingual fixture, synthesizes a deterministic
translated-playback surrogate for each human segment, matches playback dBFS to the measured source
level, ducks the original source residual while playback is active, and writes WAV artifacts plus
`playback_suppression_predictions.jsonl`.

Run the scorer contract in the small image:

```bash
make audio-eval-playback-suppression-contract-check
```

Run the fixture:

```bash
make audio-eval-playback-suppression-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-check
```

The report gates segment count, source/playback level error, source residual reduction, translated to
residual ratio, clipping, peak headroom, artifact hashes, and an explicit
`ducking_masking_simulation_not_true_cancellation` claim. Current measured fixture result on
June 12, 2026: four translated playback segments passed with max level error 0.0 dB, minimum measured
source residual reduction 10.0 dB, minimum translated-to-residual ratio 10.011 dB, zero clipped
samples, and rendered peak -9.205 dBFS.

Detractor loop: this is a synthetic ducking/masking prototype. It does not prove same-voice TTS,
listener-position cancellation, WebRTC AEC, room-device behavior, or translated speech intelligibility.
The next falsifying benchmark is a real room loopback recording that measures source residual
audibility and translated-output distortion on the target device.

## Optional Whisper Translation Baseline

`scripts/run_whisper_translation_fixture.py` is the first measured language-ID plus to-English speech
translation adapter. The contract check runs in the small base image:

```bash
make audio-eval-whisper-contract-check
```

The actual model run uses a heavier faster-whisper profile:

```bash
make audio-eval-whisper-build
make audio-eval-whisper-translation-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-translation-check
```

The runner uses oracle source clips from the FLEURS fixture, calls Whisper with `task=translate`, and
writes `whisper_translation_predictions.jsonl` using the same segment shape as the oracle translation
file. The report records primary-language accuracy, exact match, token F1, character similarity, and
first/final latency. `audio-eval-whisper-translation-check` is warning-only because tiny Whisper is a
baseline and because this is not yet live diarization, noisy-room ASR, or same-voice playback.

`scripts/run_whisper_rolling_translation_fixture.py` is the next falsifying benchmark. It still uses
oracle diarization boundaries, but it slices audio from the mixed FLEURS room signal instead of clean
source clips. That exposes Whisper to overlap, level differences, and boundary context while preserving
the same language/translation JSONL contract.

```bash
make audio-eval-whisper-rolling-contract-check
make audio-eval-whisper-rolling-translation-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-rolling-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-rolling-translation-check
```

The rolling report writes partial and final model predictions, then compares final primary-language
accuracy, translation token F1, first partial latency, final latency, and language flips. This is still
not a live app proof: the cheapest next falsifier is to replace the oracle boundaries with the rolling
diarizer output on the same multilingual mix.

## Oracle Target-Speaker Extraction Upper Bound

`scripts/benchmark_target_speaker_extraction_fixture.py` defines the first separation/TSE artifact
contract. The oracle adapter writes per-speaker clips from FLEURS fixture stems, preserving
`speaker_id`, target level, timing, extracted audio path, and hashes. Its scorer records target SNR,
interferer reduction on overlapped windows, level error, duration error, and extracted-audio hashes.
The mixture-passthrough adapter writes the same shape from mixed audio and must fail the quality gates;
it is a lower-bound negative control, not a separator.

```bash
make audio-eval-oracle-tse-contract-check
make audio-eval-oracle-tse-check
make audio-eval-mixture-passthrough-tse-contract-check
make audio-eval-mixture-passthrough-tse-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-oracle-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-oracle-tse-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-mixture-passthrough-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-mixture-passthrough-tse-check
```

`scripts/run_whisper_tse_translation_fixture.py` then feeds Whisper with rolling oracle-TSE slices
instead of rolling mixed-audio slices:

```bash
make audio-eval-whisper-oracle-tse-contract-check
make audio-eval-whisper-oracle-tse-translation-check
make audio-eval-whisper-mixture-passthrough-tse-contract-check
make audio-eval-whisper-mixture-passthrough-tse-translation-check
make audio-eval-enrolled-tse-contract-check
make audio-eval-enrolled-oracle-tse-check
make audio-eval-enrolled-mismatch-tse-check
make audio-eval-whisper-enrolled-oracle-tse-translation-check
make audio-eval-speechbrain-sepformer-contract-check
make audio-eval-speechbrain-sepformer-check
make audio-eval-speechbrain-voice-similarity-contract-check
SPEECHBRAIN_VOICE_SIMILARITY_ARGS='--candidate-report artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json --score-warning-only' make audio-eval-speechbrain-voice-similarity-check
make audio-eval-whisper-speechbrain-sepformer-translation-check
make audio-eval-wesep-contract-check
make audio-eval-wesep-check
make audio-eval-whisper-wesep-translation-check
make audio-eval-live-capture-contract-check
make audio-eval-live-capture-check
make audio-eval-playback-suppression-contract-check
make audio-eval-playback-suppression-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-oracle-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-oracle-tse-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-mixture-passthrough-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-mixture-passthrough-tse-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-enrolled-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-enrolled-oracle-tse-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-enrolled-mismatch-tse-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-enrolled-oracle-tse-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-sepformer-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-sepformer-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-voice-similarity-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-voice-similarity-check --candidate-report artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json --score-warning-only
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-speechbrain-sepformer-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-wesep-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-check
```

These checks are an upper bound, not a real separator. They answer whether good target-speaker audio
would restore language ID and translation quality after the mixed-slice failure. The next real model
adapter must write the same TSE JSONL and beat the mixed-slice Whisper baseline without adding too much
latency or target-speaker distortion.

`scripts/benchmark_enrolled_tse_fixture.py` extends that contract with explicit enrollment/reference
audio fields. `oracle-check` writes clean same-speaker enrollment clips and extracted target clips, so
it is an upper bound for an enrollment-aware model. `mismatch-check` writes valid enrollment metadata
for the wrong speaker and exits successfully only when the target-audio quality gates fail. That keeps
future adapters honest: they must use the cue, not merely separate or copy any plausible voice.

`scripts/run_wesep_enrolled_tse_fixture.py` is the first real audio-enrollment TSE adapter. It runs
WeSep's mixture-plus-enrollment API in a dedicated disposable profile, writes the same TSE JSONL
shape with enrollment metadata, and compares the result with the mixture-passthrough lower bound.
The WeSep demo recommends more than 5 seconds of enrollment audio, so the report records available
enrollment duration and whether that recommendation is met for every target speaker.

Future real model adapters can write TSE JSONL and reuse the scorer:

```bash
python3 scripts/benchmark_target_speaker_extraction_fixture.py score \
  --predictions artifacts/audio_eval/runs/<adapter>/predictions.jsonl
```

`scripts/run_speechbrain_sepformer_tse_fixture.py` is the first real separator spike. It uses
SpeechBrain SepFormer WHAMR through its own disposable profile, resamples the FLEURS mix windows to
the model's expected 8 kHz mono input, writes extracted clips back at the fixture sample rate, and
stores predictions as the same TSE JSONL shape. The benchmark maps unordered separated streams back
to stable `speaker_id` with oracle fixture stems, which is useful for measurement but not a runtime
target-speaker extraction solution. The report compares SepFormer against the mixture-passthrough
lower bound and leaves the oracle-TSE upper bound as the quality ceiling.

The downstream bridge is reusable for future separators:

```bash
python3 scripts/run_whisper_tse_translation_fixture.py \
  --tse-mode external \
  --tse-predictions artifacts/audio_eval/runs/<adapter>/predictions.jsonl \
  --score-warning-only
```

Current measured result on June 10, 2026: SepFormer wrote four extracted clips with hashes and exact
duration preservation, but it failed quality gates on this four-language overlap fixture. Its mean
target SNR was -8.654 dB, mean interferer reduction was -8.611 dB, max absolute level error was
12.007 dB, and it did not beat the mixture-passthrough mean SNR of -0.043 dB. Whisper on these
external TSE clips produced all four final speaker translations but warned with primary-language
accuracy 0.25, mean translation token F1 0.088346, and one language flip.

Current measured WeSep result on June 10, 2026: WeSep wrote four enrollment-conditioned extracted
clips with hashes, enrollment files, exact duration preservation, and zero enrollment mismatches. The
initial raw output was mostly polarity-inverted and too quiet, so the June 12, 2026 runner now applies
runtime-available mixture-correlation polarity correction and enrollment-RMS level normalization while
declaring that no reference stems are used. With that postprocess, WeSep is a real-model
release-candidate pass: mean target SNR 9.766 dB beats the -0.043 dB mixture-passthrough lower bound,
mean interferer reduction is 9.809 dB, min segment SNR is 0.186 dB, and max level error is 0.609 dB.
It still fails the oracle-quality ceiling gates, which remain intentionally strict. Whisper on the
WeSep clips still passes the older oracle-windowed downstream bridge with all four final speaker
translations, primary-language accuracy 1.0, mean translation token F1 0.176282, two recorded
language flips, max first-partial latency 4497.101 ms, and max final latency 9375.379 ms. Because
that bridge uses oracle diarization windows, it is useful fixture evidence but cannot satisfy the
product streaming translation release gate.

The current product streaming-translation proof is
`audio-eval-whisper-wesep-causal-translation-check`. It first requires the accepted WeSep component
report, then drives Whisper from causal rolling Sortformer diarization over the FLEURS overlap
fixture instead of human/oracle segment windows. The June 12, 2026 measured Sortformer run used
20-step chunks plus 20-step right context, wrote seven rolling PCM steps, recorded DER-like 0.13699,
first-speech and overlap latency 3200 ms, input-buffer latency 3.2 seconds, model RTF 0.162252, and
`causality_ok=true` with `max_future_samples_used=0`. The downstream causal Whisper report produced
four final speaker translations with primary-language accuracy 1.0, mean translation token F1
0.206838, three recorded language flips, max first-partial latency 4455.676 ms, and max final
latency 8725.643 ms. It still declares that the consumed WeSep clips are accepted external TSE
artifacts, so the next stricter benchmark should run TSE directly on each causal diarization window
with held-out enrollment.

## Fallback TTS Audio

`scripts/benchmark_fallback_tts_fixture.py` writes
`artifacts/audio_eval/runs/same-voice-tts/voice-clone-report.json`. Despite the legacy report name,
the current accepted mode is neutral fallback TTS, not voice cloning.

```bash
make audio-eval-fallback-tts-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-fallback-tts-check
```

The benchmark consumes the final causal Whisper-after-WeSep translation JSONL, synthesizes English
with eSpeak NG in the disposable audio-eval container, and matches each output WAV to the measured
source/TSE clip level. The June 12, 2026 run produced four hashed fallback WAVs with
`voice_clone_status=fallback_voice`, `voice_similarity_claim=not_claimed`, max output level error
0.0 dB, max peak -5.066 dBFS, and max synthesis wall time 207.028 ms. The release gate reopens those
WAVs, checks SHA-256 hashes and frame counts, and verifies the fallback no-similarity-claim semantics.

Detractor loop: this is safe spoken fallback output, not same-voice synthesis. It does not prove
speaker similarity, naturalness, provider consent workflows, or reference deletion for a cloning
provider. Those remain blocked on a dedicated same-speaker benchmark.

## Same-Voice Candidate Evidence

`scripts/benchmark_same_voice_candidate_fixture.py` validates candidate same-voice English audio
generated by an external local model or provider. It does not synthesize audio itself. The input is a
manifest under `artifacts/audio_eval/runs/same-voice-candidate/` that points at a consented reference
WAV, the generated English WAV, and a JSON speaker-similarity sidecar for each segment.

```bash
make audio-eval-same-voice-candidate-contract-check
SAME_VOICE_CANDIDATE_ARGS='--manifest artifacts/audio_eval/runs/same-voice-candidate/same-voice-candidate-manifest.json' make audio-eval-same-voice-candidate-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-same-voice-candidate-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-same-voice-candidate-check --manifest artifacts/audio_eval/runs/same-voice-candidate/same-voice-candidate-manifest.json
```

Minimum manifest shape:

```json
{
  "schema_version": 1,
  "adapter_id": "my_same_voice_adapter",
  "provider_or_model": "provider-or-local-model-name",
  "consent": {
    "speaker_consent": true,
    "voice_clone_reference_used": true,
    "reference_retention_policy": "ephemeral_reference_deleted",
    "consent_basis": "written or recorded consent for this test",
    "consent_evidence_path": "consent.txt",
    "speaker_ids": ["speaker_001"],
    "reference_audio_sha256s": ["reference_wav_sha256"]
  },
  "segments": [
    {
      "speaker_id": "speaker_001",
      "source_language_code": "es",
      "target_language_code": "en",
      "translated_text": "The English text spoken by the candidate WAV.",
      "reference_audio_path": "speaker_001_reference.wav",
      "source_audio_path": "speaker_001_source.wav",
      "tts_output_path": "speaker_001_english.wav",
      "voice_similarity_metric": "release_gate_acoustic_proxy_v1",
      "voice_similarity_evaluator_id": "language_release_gate_builtin_v1",
      "voice_similarity_score": 0.72,
      "voice_similarity_threshold": 0.65,
      "voice_similarity_evidence_path": "speaker_001_similarity.json"
    }
  ]
}
```

The checker copies all referenced artifacts into the run directory, hashes the manifest, consent
evidence, source WAVs, reference WAVs, output WAVs, and similarity sidecars, rejects byte-identical or
PCM-identical reference clones across all segments, recomputes output level error against the source
WAV, enforces peak headroom, and requires the sidecar score/threshold/metric/evaluator to match the
manifest. For now the required metric is the release gate's built-in acoustic proxy
`release_gate_acoustic_proxy_v1`; it is an artifact-consistency sanity check, not final human speaker
similarity. The release gate repeats the artifact reopening and rejects self-attested
`same_voice_candidate` reports with weak or unrecomputed similarity, forged level fields, missing
consent evidence, stale external artifact paths, unrelated consent speaker/reference bindings, or
cloned reference audio. Because that proxy is not a real speaker-similarity proof, proxy-only
candidate reports are deliberately not allowed to replace fallback TTS as release evidence. Human
listener similarity and stronger ASV scoring remain the next falsifying benchmark.

## SpeechBrain ECAPA Voice Similarity

`scripts/run_speechbrain_voice_similarity_fixture.py` is the stronger optional ASV pass for a same-
voice candidate report. It reopens the candidate report, verifies referenced reference/output WAV
hashes, runs SpeechBrain ECAPA-TDNN speaker verification, and writes
`artifacts/audio_eval/runs/speechbrain-ecapa-same-voice-similarity/speechbrain-voice-similarity-report.json`.

Run the contract check in the small audio image:

```bash
make audio-eval-speechbrain-voice-similarity-contract-check
```

Run the model scorer in the SpeechBrain profile after a same-voice candidate report exists:

```bash
SPEECHBRAIN_VOICE_SIMILARITY_ARGS='--candidate-report artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json --score-warning-only' make audio-eval-speechbrain-voice-similarity-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-voice-similarity-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-voice-similarity-check --candidate-report artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json --score-warning-only
```

The default verifier is `speechbrain/spkrec-ecapa-voxceleb`. Its official model card describes an
ECAPA-TDNN verifier trained on VoxCeleb1+VoxCeleb2, cosine speaker verification, mono 16 kHz input
with automatic normalization, Apache-2.0 licensing, and a reported 0.80 EER on VoxCeleb1-test
cleaned. ECAPA-TDNN itself was published at Interspeech 2020, and SpeechBrain is the peer-reviewed
toolkit behind the model. Treat this as stronger candidate evidence than the local acoustic proxy,
not product release proof: generated cross-language voice output still needs consented local speaker
tests, human similarity ratings, intelligibility scoring, and the fallback release path until that
calibration exists.

## Real-Room Playback Suppression

`scripts/run_real_room_playback_suppression.py` writes
`artifacts/audio_eval/runs/real-room-playback-suppression/room-playback-suppression-report.json`.
This runner is host-side because it must open real input and output devices through
`sounddevice`/PortAudio; it is intentionally outside the Docker audio profile.

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
```

The runner builds source and translated playback references from the accepted fallback TTS report,
plays calibration signals through the selected speaker device, records the room microphone, and
hashes the source reference, translated reference, stereo playback render, calibration recordings,
and final room loopback WAV. The release gate reopens those WAVs, verifies hashes and headers, then
recomputes calibration/reference fidelity, source residual reduction, translated-output
correlation/distortion, and calibration dBFS from the WAV artifacts before accepting any
room-suppression claim. `qualify-device` writes
`artifacts/audio_eval/runs/real-room-device-qualification/room-device-qualification-report.json` and
checks whether the selected input/output path preserves known source and translated playback
references before any cancellation measurement is attempted. It is a prerequisite diagnostic, not a
release substitute.
`probe-route` writes `artifacts/audio_eval/runs/real-room-route-probe/route-probe-report.json` with
`measurement_kind=real_room_route_probe_triage` and `release_proof=false`. It plays a chirp sentinel,
records the selected route, and reports matched-reference confidence, lag, gain, clipping, route
errors, hashes, and device fingerprint before speech qualification is attempted.
`sweep-routes` writes
`artifacts/audio_eval/runs/real-room-route-probe-sweep/route-probe-sweep-report.json` with
`measurement_kind=real_room_route_probe_sweep_triage` and `release_proof=false`. It tries bounded
device/sample-rate/input-channel/output-channel combinations, stores every child route-probe report
path/hash set, and names both a passing candidate and the best-scored failing route when no candidate
passes. It is only route triage; the release gate rejects route probes and route sweeps as room
suppression evidence.
`sweep-devices` is an even cheaper candidate finder. It writes
`artifacts/audio_eval/runs/real-room-device-sweep/device-sweep-report.json` with
`measurement_kind=real_room_device_sweep_triage`, `release_proof=false`, every attempted
input/output/sample-rate/gain configuration, failed gates, device fingerprints, actual lag, and
margin-to-threshold values. A sweep candidate must be rerun with the full room `check` command before
it can feed the release gate.

Current June 12, 2026 host evidence on the SoundWire/WASAPI devices is a useful failure, not a
release pass. The 48 kHz device qualification recorded audible calibration
(`source_calibration_dbfs=-36.423`, `translated_reference_dbfs=-37.848`) but failed reference
fidelity (`source_calibration_reference_correlation=-0.000594`,
`translated_calibration_reference_correlation=-0.000034`). The full aligned -18 dB room run recorded
83.799 dB source residual reduction, but calibration/reference fidelity failed
(`source_calibration_reference_correlation=-0.000557`,
`translated_calibration_reference_correlation=-0.000375`) and translated-output preservation failed
(`translated_output_correlation=0.000026`, distortion 91.632 dB). The release gate correctly remains
red.
The first route-probe diagnostics also failed: MME input `1` to output `3` at 16 kHz recorded the
sentinel but matched it with only `route_probe_reference_confidence=0.000215`; WASAPI input `12` to
output `10` at 48 kHz failed to open the duplex stream with PortAudio `Invalid number of channels`.
This points to a wrong or processed host route before any source-cancellation claim is meaningful.
The later 48 kHz route sweep found an apparent WASAPI candidate on input `18` and output `14` with
2 input channels, but the child route-probe WAV hash matched the generated reference hash exactly.
New route-probe reports therefore include `route_probe_recording_matches_reference`, and the
`route_probe_recording_not_reference_clone` gate rejects byte-identical "recordings" as non-room
triage false positives.

Detractor loop: this is a constrained known-reference loopback at one microphone/listener position,
not proof of arbitrary live-human cancellation. The next implementation step should improve the
hardware/DSP strategy or add an honest headphones/earpiece fail-open mode; do not lower the release
threshold or trust self-attested JSON to make this pass.

`scripts/run_headphone_isolation_check.py` is that honest headphone/earpiece path. It scores a
listener-ear source-open control recording, a source-isolated listener-ear recording, and a translated
headphone playback recording against their references. The report uses
`measurement_kind=headphone_earpiece_isolation`, `source_suppression_mode=HEADPHONE_ISOLATED`, and
`suppression_claim=headphone_isolated_not_true_cancellation`; it can support a private-listener
release mode only when the release gate recomputes the WAV metrics, hashes, and measurement identity
fingerprint. The score command requires specific headphone, measurement microphone, and physical
fixture labels and all submitted WAV artifacts must meet the minimum duration floor. It does not
satisfy the true room-cancellation gate.

```bash
make headphone-isolation-contract-check
make headphone-isolation-list-devices
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-list-devices
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-prepare-manual --sample-rate-hz 48000 --playback-gain-db -18
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-check-manual --score-warning-only
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-sweep-routes --triple LISTENER_EAR_INPUT:SOURCE_SPEAKER_OUTPUT:HEADPHONE_OUTPUT --sample-rate-hz 48000 --channel-config 1:2 --score-warning-only
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-probe-route --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT --sample-rate-hz 48000 --input-channels 1 --output-channels 2
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-capture --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT --preflight-report artifacts/audio_eval/runs/headphone-earpiece-preflight/headphone-preflight-report.json --sample-rate-hz 48000 --input-channels 1 --output-channels 2 --headphone-device-label "placeholder REPLACE_WITH_HEADPHONE_MODEL" --isolation-fixture-label "placeholder REPLACE_WITH_EARCUP_AND_MIC_POSITION" --measurement-microphone-label "placeholder REPLACE_WITH_MIC_MODEL_AND_POSITION"
```

The guided capture path uses PortAudio `playrec` for all three takes, requires a selected-route
preflight report, records source-open and source-isolated with the same source output/reference/gain/
sample-rate/channel route, records translated playback through the headphone output, and embeds
device snapshots, a device-path fingerprint, per-take levels, clipping counts, hashes, and the same
non-tamper-proof provenance
boundary as the other host audio evidence.
Route sweeps are still triage only. Their reports include `summary.failure_summary` and per-attempt
`diagnosis` entries so operators can tell whether the route failed to open, used the same output for
source and headphones, was too quiet, clipped, or heard audio that did not match the generated
reference because of processing or routing mismatch.
When PortAudio routing is the blocker, `headphone-isolation-prepare-manual` creates non-release
reference WAVs, `manual-recording-manifest.json`, and `manual-recording-checklist.md` for a
phone/USB mic/external recorder flow. The manual kit remains `release_proof=false`; use
`headphone-isolation-score-manual` after collecting real listener-ear, 16-bit PCM WAV recordings
trimmed within the 500 ms release alignment window to write the release-gated
`headphone-isolation-report.json`. The optional
`headphone-isolation-play-manual` host helper plays the manifest references through selected outputs
and writes `manual-playback-log.json` with `release_proof=false`; it is recording assistance only.
It requires explicit source/headphone output devices unless `--output-device` or
`--allow-default-output` is passed deliberately.
If recorder exports do not already use the manifest's expected filenames, run
`headphone-isolation-import-manual` with the three raw take paths. It writes
`manual-import-log.json` with `release_proof=false`, can explicitly downmix stereo WAVs, and rejects
reference clones, duplicate takes, placeholder labels supplied to import, and implicit overwrites.
Run `headphone-isolation-check-manual` after recording and before scoring; it writes
`manual-recording-status.json` and blocks until the manifest, reference hashes, WAV headers, sample
rate, minimum durations, and non-placeholder score labels are coherent.

## Release Audio Evidence Gate

`scripts/release_audio_gate.py` writes `artifacts/release/audio-gate-report.json` plus the readable
`artifacts/release/audio-gate-report.md` handoff, and exits nonzero until the product audio-loop
evidence is present. The JSON remains the authoritative gate artifact; the Markdown report is for
operator handoff, blocker triage, and physical-evidence command hints. It is intentionally stricter
than the warning-only research targets.

```bash
make release-audio-gate
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 release-audio-gate
```

Release-blocking gates are live microphone capture, causal diarization, real TSE/separation that beats
mixture passthrough, streaming speech translation after accepted TSE, same-voice or fallback TTS audio,
and playback source-suppression evidence. That final gate accepts either true real-room cancellation
or measured headphone/earpiece listener isolation that is explicitly marked as not true cancellation.
Product gates require product-specific evidence fields,
not just `summary.passed=true`; the streaming translation gate rejects oracle-diarization reports, the
voice gate verifies hashed fallback WAV artifacts and revalidates same-voice candidate consent,
similarity sidecars, non-clone reference/output WAVs, and source-level matching while keeping
proxy-only candidates out of release proof. The current accepted translation report is the causal
Sortformer plus Whisper-after-WeSep bridge. The live-capture gate also rejects self-attested
microphone JSON unless the referenced WAV and chunk JSONL artifacts exist and validate. The room gate
recomputes the claimed metrics from source-only, translated-only, source-reference, translated-reference,
and loopback WAV recordings, and it requires audible, reference-faithful calibration recordings before
a pass can count. The headphone branch separately recomputes source-open, source-isolated, and
translated-headphone recordings and rejects clone/reference artifacts, forged hashes, surrogate
translated audio, and mislabeled cancellation claims. It does not claim cryptographic
provenance for coherent local artifacts. Prototype evidence, including fixture capture and playback
ducking, is listed separately so it cannot accidentally satisfy a release claim.

## External Corpus Catalog

`fixtures/audio_eval/external_corpora/catalog.json` lists public corpora that can replace or augment
the tiny LibriSpeech smoke fixture once an adapter needs harder data. Validate the catalog with:

```bash
make audio-corpus-catalog-check
```

The first ranked sources are NOTSOFAR-1 and AMI for real distant meetings, LibriCSS/LibriMix for
overlap and separation, and FSD50K/MUSAN for crowd/noise augmentation. Common Voice and FLEURS are
kept for multilingual LID/ASR fixtures. See `docs/research/audio-corpus-catalog.md` before adding any
new dataset download path.

## Chunked Diarization Proxy

`scripts/benchmark_chunked_diarization_fixture.py` adds prefix-chunk evaluation on top of the tiny
real-speech fixture. The oracle command is credential-free:

```bash
make audio-eval-real-speech-chunked-check
```

It writes chunk-level prediction JSONL, scores each prefix against truncated truth, scores the final
prefix against full truth, and reports:

- first speech detection latency by reference speaker
- overlap detection latency
- final DER-like and overlap recall
- speaker-label set changes across chunks

This still is not a true causal streaming engine, but it prevents full-file-only adapters from being
treated as realtime without reporting latency and label stability.

## Diarization Predictions

`make audio-eval-check` writes oracle diarization predictions under
`artifacts/audio_eval/predictions/oracle_diarization.jsonl` and scores them as a strict scorer smoke
test. The report also scores empty predictions as a negative self-test, so the scorer must prove it
can count misses rather than only pass oracle data. Real adapters should write the same JSONL shape:

```json
{"schema_version":1,"fixture_id":"two_speaker_overlap_en_es","adapter_id":"sortformer_spike","segments":[{"speaker_id":"model_speaker_0","start_s":0.4,"end_s":3.8,"confidence":0.98}]}
```

The scorer also accepts one segment per line:

```json
{"fixture_id":"two_speaker_overlap_en_es","adapter_id":"sortformer_spike","speaker_label":"model_speaker_0","start_s":0.4,"end_s":3.8,"confidence":0.98}
```

Run the stable wrapper command inside the audio-eval environment:

```bash
python3 scripts/benchmark_diarization_fixture.py score \
  --predictions artifacts/audio_eval/runs/sortformer/predictions.jsonl \
  --report artifacts/audio_eval/runs/sortformer/diarization-score-report.json
```

The scorer maps arbitrary predicted labels to fixture speaker ids by maximum overlap per fixture. It
uses a boundary-union timeline with no collar for the synthetic smoke set, counts human speech only,
and treats playback leakage as interference rather than a speaker. It reports DER-like miss, false
alarm, and confusion time, plus both overlap presence recall and overlap speaker-time recall.

This is deliberately DER-like, not a replacement for full diarization evaluation on real speech.
Future real-speech benchmarks should add JER, collar policy, model decision latency, and model-specific
failure notes without weakening the Phase 1 oracle gate.

## Optional Pyannote Baseline

`scripts/run_pyannote_diarization_fixture.py` is the first optional real-model adapter. It runs
`pyannote/speaker-diarization-community-1` or a local pyannote pipeline path, writes the same
diarization JSONL schema, and scores it with `scripts/benchmark_diarization_fixture.py`.

Use the dedicated heavy profile, not the base audio-eval image:

```bash
make audio-eval-pyannote-build
HF_TOKEN=... make audio-eval-pyannote-check
HF_TOKEN=... make audio-eval-pyannote-real-speech-check
HF_TOKEN=... make audio-eval-pyannote-real-speech-chunked-check
```

On Windows:

```powershell
$env:HF_TOKEN = "..."
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-pyannote-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-pyannote-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-pyannote-real-speech-chunked-check
```

The Hugging Face model card says Community-1 requires accepting model access conditions and creating a
token before downloading model files. It also documents mono 16 kHz processing, automatic downmixing
and resampling, CPU-by-default execution, optional GPU transfer, and offline use with a local model
path: https://huggingface.co/pyannote/speaker-diarization-community-1

The profile pins CPU-only PyTorch wheels by default. Add a separate GPU/CUDA profile if a future
benchmark needs accelerator throughput; do not let the baseline profile silently pull a CUDA stack.

The check target runs with `--score-warning-only` and does not pass the truth speaker count by
default. `--num-speakers-from-truth` remains available for controlled scorer debugging, but it gives
pyannote an oracle prior that is not available in the live product. If scores fail on synthetic tones,
the adapter can still be useful once real speech fixtures exist; the score report should make that
failure visible rather than hiding it.

`audio-eval-pyannote-real-speech-check` runs the same pyannote adapter on the tiny LibriSpeech mix.
It also uses `--score-warning-only` by default so early model failures remain visible without
blocking unrelated plumbing work.
`audio-eval-pyannote-real-speech-chunked-check` runs pyannote repeatedly on growing prefixes and
uses the chunked report as a streaming proxy. It is an offline baseline, not proof that pyannote is
a causal online diarizer.

## Optional Sortformer Candidate

`scripts/run_sortformer_real_speech_fixture.py` and
`scripts/run_sortformer_chunked_real_speech_fixture.py` are the first NVIDIA Streaming Sortformer
adapter spike. They use NeMo's `SortformerEncLabelModel.diarize()` entrypoint, normalize NeMo
segments into the same diarization JSONL schema, and score the tiny real-speech fixture through the
shared DER-like harness.

Use the dedicated Sortformer profile, not the base audio-eval image:

```bash
make audio-eval-sortformer-build
make audio-eval-sortformer-contract-check
HF_TOKEN=... make audio-eval-sortformer-real-speech-check
HF_TOKEN=... make audio-eval-sortformer-real-speech-chunked-check
HF_TOKEN=... make audio-eval-sortformer-online-real-speech-check
HF_TOKEN=... make audio-eval-sortformer-rolling-real-speech-check
```

On Windows:

```powershell
$env:HF_TOKEN = "..."
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-real-speech-chunked-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-online-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-rolling-real-speech-check
```

The contract check runs in the small base image and validates parser behavior without installing
NeMo or downloading a model. The model checks use `--score-warning-only` by default so early
benchmark failures are visible without blocking unrelated plumbing work.

`audio-eval-sortformer-online-real-speech-check` uses Sortformer's stateful
`forward_streaming_step` path rather than repeatedly re-running `diarize()` on growing prefixes. Its
default `low-latency` profile follows the model-card settings: chunk size 6, right context 7, FIFO
188, update period 144, and speaker cache 188, where frames are 80 ms and the documented input-buffer
latency is 1.04 seconds.

`audio-eval-sortformer-rolling-real-speech-check` adds a stricter causality layer. It reads the
fixture mix as raw mono PCM in 80 ms arrival chunks, builds each Sortformer input buffer only from
samples available at that step, runs `process_signal()` on that rolling buffer, then calls
`forward_streaming_step()` with the same AOSC state. The report includes `max_future_samples_used`
and `causality_ok` so a future adapter cannot quietly consume samples beyond the observed input
buffer.

Primary evidence for this adapter:

- NVIDIA's model card documents `nvidia/diar_streaming_sortformer_4spk-v2.1`, a mono 16 kHz input
  contract, 4-speaker output, and both low-latency and longer-buffer settings:
  https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1
- NVIDIA NeMo docs describe Sortformer as an end-to-end diarizer with offline and online variants,
  and describe Streaming Sortformer as chunked diarization with an Arrival-Order Speaker Cache:
  https://docs.nvidia.com/nemo/speech/nightly/asr/speaker_diarization/models.html
- The Interspeech 2025 paper presents Streaming Sortformer as speaker-cache-based online diarization
  with arrival-time ordering: https://www.isca-archive.org/interspeech_2025/medennikov25_interspeech.html

Detractor loop: the prefix target repeatedly runs `diarize()` on growing prefixes, the online target
uses stateful AOSC updates but still extracts features from the whole fixture before stepping, and the
rolling target removes that shortcut by extracting features per available raw PCM input buffer. It is
still disk-backed clean LibriSpeech, not live microphone hardware, a noisy room, non-English speech,
or the translated playback/suppression loop. The next falsifying benchmark should run the rolling
path on a consented local room capture with playback loopback and compare the same report fields.

## Report Shape

`scripts/audio_eval_harness.py check` writes:

- `summary.quality_gates` for pass/fail harness gates
- `benchmarks.diarization.summary.der_like` for scorer smoke checks and future model results
- `benchmarks.diarization.summary.overlap_presence_recall` for overlap wall-clock detection
- `benchmarks.diarization.summary.overlap_speaker_time_recall` for matched speaker-time in overlap
- `latency_accounting.model_layer_latency_ms` for per-model timing
- `latency_accounting.full_loop_latency_ms` for capture-to-playback timing
- `fixtures[*].audio_hashes` for deterministic rendered audio hashes
- `fixtures[*].truth` for overlap, speaker, source, and language truth
- `fixtures[*].segments` for target and measured segment levels

Future benchmarks should append model-specific result blocks instead of replacing this base schema.
