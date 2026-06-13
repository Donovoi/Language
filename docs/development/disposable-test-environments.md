# Disposable Test Environments

This repo keeps test scaffolding disposable. When code needs a runtime that may drift across machines,
add or update a buildable environment beside the code change.

## Core Docker Environment

The lightweight core environment covers the checks that do not need a full mobile SDK:

- generated contract bindings
- Robin research-pack schema validation
- Rust format, Clippy, and workspace tests
- gateway Python lint and pytest

Use it from the repo root:

```bash
make dev-env-build
make dev-env-check
make dev-env-shell
make dev-env-destroy
make dev-env-purge
```

On Windows hosts without `make`, use the PowerShell wrapper:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 build
pwsh -NoProfile -File scripts/dev_container.ps1 check
pwsh -NoProfile -File scripts/dev_container.ps1 destroy
pwsh -NoProfile -File scripts/dev_container.ps1 purge
```

`make dev-env-check` runs in a container with the repo mounted at `/workspace`. Cargo, pip, and the
gateway virtual environment live in Docker volumes so repeated runs are fast. `make dev-env-destroy`
removes the container and those volumes. `make dev-env-purge` also removes the local
`language-core-dev:local` image.

## Audio Eval Docker Profile

The audio evaluation environment is intentionally separate from the core image. It carries Python
audio/DSP dependencies, fixture mounts, and future model-cache space without slowing the core gateway,
Rust, or research-pack checks.

Use it from the repo root:

```bash
make audio-eval-build
make audio-eval-check
make audio-eval-real-speech-check
make audio-eval-real-speech-chunked-check
make audio-eval-live-capture-contract-check
make audio-eval-live-capture-check
make audio-eval-playback-suppression-contract-check
make audio-eval-playback-suppression-check
make audio-eval-fallback-tts-contract-check
make audio-eval-fallback-tts-check
make audio-eval-same-voice-candidate-contract-check
make audio-eval-speechbrain-voice-similarity-contract-check
make audio-eval-shell
make audio-eval-purge
```

On Windows hosts without `make`, use:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-build
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-real-speech-chunked-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-fallback-tts-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-fallback-tts-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-same-voice-candidate-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-voice-similarity-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-purge
```

`make audio-eval-check` renders deterministic fixtures from
`fixtures/audio_eval/v1/manifest.json`, writes WAV files and `audio-eval-report.json` under
`artifacts/audio_eval/`, and fails if baseline fixture gates fail. The generated artifacts are ignored
by git. The Compose profile also provides a disposable model-cache volume for future Sortformer,
pyannote, Whisper, Seamless, or TTS benchmark adapters.

`make audio-eval-real-speech-check` is the first networked audio smoke. It downloads two small
LibriSpeech dummy rows through the Hugging Face Dataset Viewer API at runtime, mixes a known
two-speaker overlap fixture, writes ignored artifacts under `artifacts/audio_eval/`, and runs the
oracle diarization scorer. Use it when a change needs actual speech but not a gated model.
`make audio-eval-real-speech-chunked-check` adds prefix-chunk oracle scoring so latency and label
stability reporting can be tested without provider credentials.
`make audio-eval-live-capture-contract-check` validates the fixture capture scorer. `make
audio-eval-live-capture-check` replays fixture WAV files as timestamped mono PCM chunks, checks schema,
timing jitter, gaps/reorders, streaming boundaries, level fields, and source/chunk/reassembled hashes.
The report marks `capture_source_kind=fixture_replay` and `release_proof=false`; it is a contract
scaffold for a future microphone adapter, not product evidence.
`make audio-eval-playback-suppression-contract-check` validates the playback/suppression scorer's
pass/fail gates. `make audio-eval-playback-suppression-check` renders a FLEURS translated-playback
surrogate, matches playback level to source level, ducks the source residual, checks clipping and
artifact hashes, and records that the claim is only
`ducking_masking_simulation_not_true_cancellation`.
`make audio-eval-same-voice-candidate-contract-check` validates the candidate voice evidence
contract without a provider. `make audio-eval-same-voice-candidate-check` scores an externally
generated manifest and bundles every referenced artifact into the ignored run directory.
`make audio-eval-speechbrain-voice-similarity-contract-check` validates the stronger optional ASV
report contract without downloading a model. The full `audio-eval-speechbrain-voice-similarity-check`
target runs in the heavier SpeechBrain profile after a same-voice candidate report exists.

### Host Live Microphone Capture

The real microphone capture check intentionally runs on the host because Windows input devices are
not reliably exposed inside Docker:

```bash
make live-microphone-capture-list-devices
make live-microphone-capture-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 live-microphone-capture-list-devices
pwsh -NoProfile -File scripts/dev_container.ps1 live-microphone-capture-check
```

`scripts/run_live_microphone_capture.py` uses `sounddevice`/PortAudio callbacks to capture a short
mono PCM stream, writes `capture_chunks.jsonl`, `captured_microphone.wav`, and
`live-microphone-capture-report.json` under
`artifacts/audio_eval/runs/live-microphone-capture/`, and feeds the hard release gate. Artifacts are
ignored by git because they may contain local room audio. The release gate independently validates
the referenced WAV and chunk JSONL paths, SHA-256 hashes, WAV header, chunk continuity, timestamp
monotonicity, callback jitter, and frame-clock drift before treating the report as host microphone
evidence. This validates local artifact coherence; it is not tamper-proof provenance against a
determined local actor.

Keep provider tokens, private reference voices, and licensed speech fixtures out of committed files.
When real-speech fixtures are added, commit only the manifest and acquisition/license notes unless
the data is explicitly redistributable.

### Pyannote Audio Eval Profile

The pyannote profile is opt-in because it installs heavy ML dependencies and downloads gated model
files. It is for offline/dev diarization baselines, not the default audio-eval smoke path.
The default image pins CPU-only PyTorch wheels; add a separate GPU profile when accelerator tests are
intentional.

```bash
make audio-eval-pyannote-build
HF_TOKEN=... make audio-eval-pyannote-check
HF_TOKEN=... make audio-eval-pyannote-real-speech-check
HF_TOKEN=... make audio-eval-pyannote-real-speech-chunked-check
make audio-eval-pyannote-shell
make audio-eval-pyannote-purge
```

Windows:

```powershell
$env:HF_TOKEN = "..."
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-pyannote-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-pyannote-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-pyannote-real-speech-chunked-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-pyannote-purge
```

The profile passes Hugging Face tokens from the host environment into the container at runtime. It
does not bake secrets into the image. `dev-env-destroy` and `dev-env-purge` include the pyannote
profile so model/cache volumes are removed with the rest of the disposable stack.

### Sortformer Audio Eval Profile

The Sortformer profile is opt-in because it installs NVIDIA NeMo and downloads model files. It is
the first online-diarization candidate benchmark, with separate checks for direct full-file
diarization, prefix reprocessing, stateful Sortformer stepping, and rolling raw PCM buffers.

```bash
make audio-eval-sortformer-build
make audio-eval-sortformer-contract-check
HF_TOKEN=... make audio-eval-sortformer-real-speech-check
HF_TOKEN=... make audio-eval-sortformer-real-speech-chunked-check
HF_TOKEN=... make audio-eval-sortformer-online-real-speech-check
HF_TOKEN=... make audio-eval-sortformer-rolling-real-speech-check
make audio-eval-sortformer-shell
make audio-eval-sortformer-purge
```

Windows:

```powershell
$env:HF_TOKEN = "..."
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-real-speech-chunked-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-online-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-rolling-real-speech-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-purge
```

The profile passes Hugging Face tokens from the host environment into the container at runtime. It
does not bake secrets into the image. The rolling check records whether future samples entered any
model input buffer, which makes causal capture mistakes visible in the same report contract.
`dev-env-destroy` and `dev-env-purge` include the Sortformer profile so model/cache volumes are
removed with the rest of the disposable stack.

## Optional Whisper Translation Environment

The Whisper profile keeps CTranslate2/faster-whisper dependencies out of the small audio-eval image.
Use the source-clip check for a clean language/translation baseline and the rolling mixed check when
testing overlap and boundary damage:

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
make audio-eval-whisper-purge
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-rolling-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-rolling-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-oracle-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-oracle-tse-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-mixture-passthrough-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-mixture-passthrough-tse-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-enrolled-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-enrolled-oracle-tse-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-enrolled-mismatch-tse-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-oracle-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-oracle-tse-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-mixture-passthrough-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-mixture-passthrough-tse-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-enrolled-oracle-tse-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-sepformer-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-sepformer-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-speechbrain-sepformer-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-wesep-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-live-capture-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-playback-suppression-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-purge
```

The rolling check still uses oracle diarization boundaries, but it translates mixed-audio slices and
reports language flips, partial latency, final latency, and translation token F1. Treat warnings here
as implementation guidance for separation and real diarizer integration, not as release blockers yet.
The oracle-TSE checks use fixture stems as a best-possible target-speaker extraction upper bound; real
separation models should reuse the same JSONL/report contract rather than inventing a separate output.
The mixture-passthrough checks are expected to fail quality gates and exit successfully only when the
scorer catches that copied mixed audio is not valid extraction.
The enrolled-TSE checks run in the small audio-eval image and add explicit enrollment/reference audio
fields to the same artifact shape. The oracle path is a contract upper bound; the mismatched path is a
negative control that should pass enrollment-file validation while failing target-audio quality gates.

## Optional SpeechBrain SepFormer Environment

The SpeechBrain SepFormer profile keeps PyTorch, TorchAudio, SpeechBrain, and the WHAMR checkpoint out
of the smaller audio images. It is a blind two-speaker separator benchmark, not an enrollment-based
target-speaker extraction runtime.

```bash
make audio-eval-speechbrain-sepformer-build
make audio-eval-speechbrain-sepformer-contract-check
make audio-eval-speechbrain-sepformer-check
SPEECHBRAIN_VOICE_SIMILARITY_ARGS='--candidate-report artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json --score-warning-only' make audio-eval-speechbrain-voice-similarity-check
make audio-eval-whisper-speechbrain-sepformer-translation-check
make audio-eval-speechbrain-sepformer-shell
make audio-eval-speechbrain-sepformer-purge
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-sepformer-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-sepformer-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-voice-similarity-check --candidate-report artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json --score-warning-only
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-speechbrain-sepformer-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-speechbrain-sepformer-purge
```

The profile uses the shared Hugging Face cache volume and passes Hugging Face tokens only from the
host environment. SepFormer emits unordered separated streams and may normalize amplitude internally,
so the benchmark records oracle stream assignment and same-volume errors explicitly. Treat a pass as
evidence that blind separation helped the fixture, not proof that live speaker locking, enrollment, or
source suppression are solved.
The same profile also carries the optional SpeechBrain ECAPA voice-similarity scorer for externally
generated same-voice candidate reports. It verifies reference/output WAV hashes and writes ASV scores,
but remains candidate evidence rather than release proof until calibrated against consented local
speakers and human listener similarity.

## Optional WeSep Enrolled TSE Environment

The WeSep profile keeps the audio-enrollment target-speaker extraction stack out of the smaller
audio images. It uses pinned WeSep and WeSpeaker source checkouts, CPU-only PyTorch/TorchAudio plus
TorchCodec wheels, and a disposable `/root/.wesep` model-cache volume for the public English
checkpoint.

```bash
make audio-eval-wesep-build
make audio-eval-wesep-contract-check
make audio-eval-wesep-check
make audio-eval-whisper-wesep-translation-check
make audio-eval-wesep-shell
make audio-eval-wesep-purge
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-build
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-wesep-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-sortformer-rolling-fleurs-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-causal-tse-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-whisper-wesep-causal-translation-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-wesep-purge
```

The runner writes the same TSE JSONL/report contract as the oracle and SpeechBrain checks, but adds
explicit same-speaker enrollment audio paths, hashes, available enrollment duration, and whether the
fixture meets the WeSep demo recommendation of more than 5 seconds of enrollment audio. The current
June 12, 2026 run is release-candidate evidence rather than a warning-only probe: the runner applies
runtime-available mixture-correlation polarity correction and enrollment-RMS level normalization,
declares no reference-stem use, beats mixture passthrough with mean target SNR 9.766 dB and mean
interferer reduction 9.809 dB, keeps max absolute level error to 0.609 dB, and feeds both the older
oracle-windowed downstream Whisper diagnostic and the causal Sortformer-driven Whisper release
bridge. The report still records that the model is below oracle-quality ceiling gates and that longer
non-same-window enrollment plus direct TSE on causal diarization windows remain necessary for broader
confidence.

## Fallback TTS Audio

The same audio-eval base image includes eSpeak NG for the consent-safe neutral fallback TTS release
path. The contract target validates the report shape without depending on the engine, and the product
target synthesizes real WAV files from the current causal translation output:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-fallback-tts-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-fallback-tts-check
```

The June 12, 2026 run wrote `artifacts/audio_eval/runs/same-voice-tts/voice-clone-report.json`, four
hashed eSpeak NG WAV files, `voice_clone_status=fallback_voice`, `voice_similarity_claim=not_claimed`,
max level error 0.0 dB, and max peak -5.066 dBFS. This is release evidence for fallback spoken
English only; same-voice cloning still needs a dedicated provider/model benchmark.

## Same-Voice Candidate Artifacts

The same audio-eval base image also contains the validation path for externally generated same-voice
candidate WAVs. This path is intentionally smaller than a full model environment: future provider or
local-model spikes can write a manifest plus WAV/JSON sidecars, then destroy their own heavier runtime
after the candidate artifacts have been scored.

```bash
make audio-eval-same-voice-candidate-contract-check
SAME_VOICE_CANDIDATE_ARGS='--manifest artifacts/audio_eval/runs/same-voice-candidate/same-voice-candidate-manifest.json' make audio-eval-same-voice-candidate-check
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-same-voice-candidate-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-same-voice-candidate-check --manifest artifacts/audio_eval/runs/same-voice-candidate/same-voice-candidate-manifest.json
```

The manifest must include structured consent metadata, a consent evidence path, consent-bound
`speaker_ids` and `reference_audio_sha256s`, one or more mono 16-bit PCM source/reference WAVs, one
generated English output WAV per segment, and a similarity-evidence JSON sidecar whose speaker id,
metric, evaluator, score, threshold, reference/output SHA-256 hashes, and reference/output PCM hashes
match the manifest. The scorer copies those files under
`artifacts/audio_eval/runs/same-voice-candidate/candidate_artifacts/`, writes
`voice-clone-report.json`, recomputes the built-in `release_gate_acoustic_proxy_v1` score, and fails
cloned reference bytes/PCM, cross-segment reference clones, weak or non-recomputed similarity, missing
consent evidence, clipped output, or output levels more than 0.75 dB from the source audio.

`release_audio_gate.py` repeats the hash, WAV, level, consent binding, sidecar, and built-in acoustic
proxy checks, then keeps proxy-only `same_voice_candidate` reports out of release proof until a
calibrated ASV/human speaker-similarity release gate exists. The current release evidence still uses
`fallback_voice`; this candidate path plus the optional SpeechBrain ECAPA scorer is for evaluating
VoxCPM/CosyVoice/OpenVoice/provider outputs without weakening the fallback release gate.

## Host Real-Room Playback Suppression

Real-room playback/suppression checks run on the host audio stack because Docker cannot reliably
own the Windows input/output devices. Use the wrapper for repeatable command names and the direct
Python command when you need to tune a specific device/sample-rate pairing:

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
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-virtual-lab
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-prepare-manual --sample-rate-hz 48000 --playback-gain-db -18
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-check-manual --score-warning-only
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-sweep-routes --triple LISTENER_EAR_INPUT:SOURCE_SPEAKER_OUTPUT:HEADPHONE_OUTPUT --sample-rate-hz 48000 --channel-config 1:2 --score-warning-only
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-probe-route --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT --sample-rate-hz 48000 --input-channels 1 --output-channels 2
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-capture --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT --preflight-report artifacts/audio_eval/runs/headphone-earpiece-preflight/headphone-preflight-report.json --sample-rate-hz 48000 --input-channels 1 --output-channels 2 --headphone-device-label "placeholder REPLACE_WITH_HEADPHONE_MODEL" --isolation-fixture-label "placeholder REPLACE_WITH_EARCUP_AND_MIC_POSITION" --measurement-microphone-label "placeholder REPLACE_WITH_MIC_MODEL_AND_POSITION"
python scripts/run_real_room_playback_suppression.py probe-route --input-device 1 --output-device 3 --sample-rate-hz 16000 --duration-s 2 --playback-gain-db -18 --score-warning-only
python scripts/run_real_room_playback_suppression.py sweep-routes --pair 1:3 --pair 17:14 --sample-rate-hz 16000 --sample-rate-hz 48000 --channel-config 1:2 --channel-config 2:2 --max-attempts 8 --playback-gain-db -18 --score-warning-only
python scripts/run_real_room_playback_suppression.py sweep-devices --pair 12:10 --sample-rate-hz 48000 --max-reference-duration-s 3 --playback-gain-db -18 --score-warning-only
python scripts/run_real_room_playback_suppression.py qualify-device --input-device 12 --output-device 10 --sample-rate-hz 48000 --playback-gain-db -18 --score-warning-only
python scripts/run_real_room_playback_suppression.py check --input-device 12 --output-device 10 --sample-rate-hz 48000 --playback-gain-db -18 --score-warning-only
python scripts/run_headphone_isolation_check.py self-test
```

The runner writes ignored evidence under
`artifacts/audio_eval/runs/real-room-playback-suppression/`, including hashed playback references,
calibration recordings, the stereo cancellation render, the room loopback recording, and
`room-playback-suppression-report.json`. The release gate reopens the WAV artifacts, aligns separate
recordings within a bounded lag window, and recomputes calibration/reference fidelity and room
metrics instead of trusting JSON fields alone.
The `headphone-isolation-virtual-lab` command is a development-only scorer and artifact-plumbing
check. It should pass its own virtual gates and be rejected by `release_audio_gate.py`; physical
release evidence must come from either `headphone-isolation-probe-route` plus
`headphone-isolation-capture`, or `headphone-isolation-prepare-manual` plus
`headphone-isolation-score-manual`, with real listener-ear recording hardware.
Guided host capture must consume a preflight report generated with a selected, physically confirmed
capture-ready route; laptop built-in microphones remain route triage only.
Use an explicit expected-failure assertion when checking the release gate rejection:

```powershell
python scripts/release_audio_gate.py --headphone-isolation-report artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/headphone-virtual-lab-report.json --json *> artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/release-gate-virtual-rejection.json
if ($LASTEXITCODE -eq 0) { throw "expected release gate to reject the virtual listener-ear report" }
"release gate rejected the virtual listener-ear report as expected"
```

The qualification command writes a smaller report under
`artifacts/audio_eval/runs/real-room-device-qualification/` that proves only whether the device path
can reproduce known references faithfully enough for a later room-suppression measurement.
The route-probe command writes `artifacts/audio_eval/runs/real-room-route-probe/route-probe-report.json`
with `measurement_kind=real_room_route_probe_triage` and `release_proof=false`. It plays a chirp
sentinel and records matched confidence, lag, gain, clipping, route errors, hashes, and device
fingerprint. Passing it only means the route is worth speech qualification.
The sweep command writes `artifacts/audio_eval/runs/real-room-device-sweep/device-sweep-report.json`
with `measurement_kind=real_room_device_sweep_triage` and `release_proof=false`. It is for quickly
finding a promising input/output route only: every attempted config, failed gate, actual alignment
lag, device fingerprint, and margin-to-threshold is preserved, and any apparent winner must be rerun
with the full room `check` before `release_audio_gate.py` can pass.

The June 12, 2026 SoundWire/WASAPI host runs did not pass the release gate. The current 48 kHz device
qualification recorded audible calibration but failed reference fidelity
(`source_calibration_reference_correlation=-0.000594`,
`translated_calibration_reference_correlation=-0.000034`). The full aligned -18 dB playback run
recorded 83.799 dB source residual reduction, but calibration/reference fidelity failed
(`source_calibration_reference_correlation=-0.000557`,
`translated_calibration_reference_correlation=-0.000375`) and translated-output preservation failed
(`translated_output_correlation=0.000026`, distortion 91.632 dB). Keep this red until calibrated room
recordings preserve the reference signals, preserve translated speech, and reduce source residual at
the same time.
Route-probe triage also failed on the current host: MME `1:3` produced
`route_probe_reference_confidence=0.000215`, while WASAPI `12:10` failed stream opening with
PortAudio `Invalid number of channels`. Treat this as a host route/processing blocker before trying
to tune cancellation math.

For an honest private-listener release path, collect headphone/earpiece evidence with
`scripts/run_headphone_isolation_check.py capture` when measuring on the host, or `score-manual` when
the listener-ear WAV artifacts come from a separate lab recorder and the manual manifest. It requires
a source reference, open-ear source control recording, isolated-ear source recording, translated
playback reference, and translated headphone recording, plus specific headphone, listener-ear
microphone, and physical fixture labels.
Use `virtual-lab` only for development and CI regression. It writes
`artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/headphone-virtual-lab-report.json` with
`fixture_kind=headphone_earpiece_virtual_lab` and `release_proof=false`; `release_audio_gate.py` must
reject it. The physical setup details are in
`docs/development/headphone-isolation-release-runbook.md`.
Run `probe-route` first when the source/headphone/measurement route is uncertain; it writes
`artifacts/audio_eval/runs/headphone-earpiece-route-probe/headphone-route-probe-report.json` with
`measurement_kind=headphone_earpiece_route_probe_triage`, `release_proof=false`, route-open errors,
reference-fidelity metrics, artifact hashes, clipping gates, distinct source/headphone output
identity, and a byte-clone check. Passing it only means the route is worth trying with the full
guided capture; add `--score-warning-only` only to collect a failed diagnostic report and do not
advance unless `summary.passed=true`.
Use `sweep-routes` before `probe-route` when device indexes or host APIs are uncertain. It writes
`artifacts/audio_eval/runs/headphone-earpiece-route-probe-sweep/headphone-route-probe-sweep-report.json`
with every attempted listener-ear input/source output/headphone output triple, failed gates,
best-scored attempt, and candidate attempt. It is also `release_proof=false`; rerun any candidate as a
single `probe-route`, then run guided capture. If the sweep tries multiple sample rates or channel
configs, copy the chosen `candidate_attempt`'s exact `sample_rate_hz`, `input_channels`, and
`output_channels` into both follow-up commands. Failed attempts include `diagnosis` and the sweep
summary includes `failure_summary`; `gate:*` entries count route-gate failures, while route diagnosis
distinguishes route-open errors, too-quiet recordings, clipping, and audible but reference-distorted
Windows processing paths.
The guided capture command records source-open and source-isolated through the same source output
route, records translated playback through the headphone output, and embeds PortAudio device
snapshots, a device-path fingerprint, per-take levels, clipping counts, and hashes. Placeholder labels
and sub-second WAV bundles are rejected by the release gate. The report is written to
`artifacts/audio_eval/runs/headphone-earpiece-isolation/headphone-isolation-report.json` and is
accepted by the release gate only as `headphone_isolated_not_true_cancellation`, never as true
room-wide cancellation.
If host routing remains unreliable, `headphone-isolation-prepare-manual` writes
`artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-manifest.json`,
`manual-recording-checklist.md`, plus the source and translated reference WAVs. Record the three
listener-ear takes with a phone, USB mic, or external recorder; `headphone-isolation-play-manual` can
optionally play the
manifest references through the source and headphone outputs and writes a non-release
`manual-playback-log.json`. The playback helper requires explicit source/headphone output devices
unless `--output-device` or `--allow-default-output` is passed deliberately. Export 16-bit PCM WAV at
the kit sample rate, trim pre-roll so playback starts within 500 ms of recording start, then either
place the files at the manifest's expected paths or run `headphone-isolation-import-manual` with the
three raw recorder WAVs. The importer writes a non-release `manual-import-log.json`, can explicitly
downmix stereo WAV exports, and rejects reference clones, duplicate takes, placeholder labels supplied
to import, and implicit overwrites. Then run `headphone-isolation-check-manual` without warning-only
before scoring. The doctor writes `manual-recording-status.json` and fails until the manifest,
reference hashes, sample rate, mono 16-bit PCM format, and minimum recording durations are ready, and
until `check-manual` receives specific hardware and fixture labels matching the later
`headphone-isolation-score-manual` command.

## Release Audio Evidence Gate

Use the hard release gate only after the relevant audio-eval reports have been generated:

```bash
make release-audio-gate
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 release-audio-gate
```

Unlike warning-only research checks, this command exits nonzero when required reports are missing or
failing. Live microphone capture, causal diarization, real target-speaker extraction, and streaming
speech translation after accepted TSE are checked separately. On the current June 12, 2026 evidence,
the WeSep component report passes and the causal Sortformer plus Whisper-after-WeSep bridge satisfies
the streaming translation gate. Consent-safe fallback TTS also passes with independently verified WAV
hashes and level matching; same-voice proxy candidates are validation artifacts only until a stronger
speaker-similarity gate exists. The gate still blocks product-release claims until playback source
suppression has passing evidence: either true real-room cancellation or the measured headphone/earpiece
mode described above.
Prototype checks are recorded separately, must identify their prototype source kind, and cannot
satisfy release-blocking gates.

## Agent Rule

When a change introduces a new runtime dependency, provider, database, model server, queue, SDK, or
system package, update the disposable environment in the same change. Do not leave future agents to
reverse-engineer host setup from failure logs.

Minimum scaffolding for a new environment-sensitive feature:

1. Add or update a Dockerfile or Compose service under `docker/dev/`.
2. Add a script under `scripts/` that runs the smallest useful verification path.
3. Add a `make dev-env-*` target for build/run/destroy or extend `make dev-env-check`.
4. Document required env vars, secrets, mounted files, and cleanup steps here.
5. Keep secrets out of images and commits; pass them via env files or runtime environment.

## Flutter And Mobile Checks

Flutter is intentionally not baked into the core image because it is much larger and platform-specific
release builds need host tooling. For now, use the host/bootstrap path for Flutter:

```bash
make bootstrap
make flutter-check
```

If Flutter becomes a frequent CI/local blocker, add a separate `docker/dev/Dockerfile.flutter` and a
Compose profile instead of bloating the core environment.

## Research Pack Checks

Research scaffolding is intentionally lightweight and credential-free in check mode:

```bash
python3 scripts/prepare_robin_research_pack.py --check
```

When a real audio/model/provider decision is made, generate a dated pack, run Robin from the sibling
checkout, and add the smallest benchmark or smoke check needed to validate the selected option.
Research-backed audio work should follow `docs/research/research-backed-implementation-backlog.md`.
