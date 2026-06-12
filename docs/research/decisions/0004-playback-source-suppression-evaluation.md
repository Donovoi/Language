# Playback, Source Suppression, And Evaluation

- Decision id: RDR-0004
- Date: 2026-06-08
- Owner/agent: Codex research gate
- Subsystem: playback mixing, loudness matching, source-voice suppression, and benchmark design
- Implementation surface: future playback mixer, DSP adapter, gateway suppression metadata, disposable audio eval environment

## Product Constraint

The app should play translated English at the source speaker's perceived volume while making the
original source less distracting. The product language says "noise cancelling the original voice", but
the implementation must be physically honest: one consumer microphone/speaker cannot magically erase
a live human voice everywhere in the room.

## Options Considered

| Option | Evidence status | Runtime fit | Main concern |
| --- | --- | --- | --- |
| WebRTC APM baseline | Official WebRTC docs | Good first echo/noise/AGC module | It cancels app playback echo, not the real source speaker |
| Active speech plus loudness matching | ITU P.56, BS.1770, EBU R128 | Good first volume matching baseline | LUFS windows may be too slow for very short utterances |
| Playback masking plus adaptive ducking/fail-open suppression metadata | Product/DSP decision | Honest first product behavior | Does not truly cancel source audio |
| DeepFilterNet/DNS-style enhancement | Peer-reviewed/challenge-backed | Good capture hygiene and noise/interferer benchmark path | Not a translated-playback source canceller |
| True active source cancellation | Research/hardware-dependent | Possible only under constrained hardware/geometry | Risk of overpromising |

## Recommendation

Start with a conservative playback/suppression stack:

1. WebRTC Audio Processing Module for echo cancellation, noise suppression, and AGC baseline.
2. ITU P.56 active speech level plus dBFS/short-window loudness tracking for same-volume playback; use BS.1770/LUFS and EBU R128 as calibration references where windows are long enough.
3. Playback masking and adaptive ducking as the first "source suppression" behavior.
4. Treat AEC as cancellation of app translated playback leaking into the microphone, not cancellation of the real speaker in the room.
5. Report `original_voice_suppression_db` only as a measured diagnostic, not as a guarantee.
6. Fail open when suppression confidence is low.

Do not claim true original-voice cancellation until a benchmark proves it under the exact capture and
playback hardware configuration.

## Evidence

| Ref | Source | Status | Key result | Link |
| --- | --- | --- | --- | --- |
| R1 | WebRTC APM | Official docs | Provides echo cancellation, noise suppression, and automatic gain control for microphone signals. | https://webrtc.googlesource.com/src/+/7c793a7dbe548735fe9e1d107e00d17937202f47/modules/audio_processing/g3doc/audio_processing_module.md |
| R2 | ITU-R BS.1770-5 | Official standard | Defines algorithms for programme loudness and true-peak measurement. | https://www.itu.int/rec/R-REC-BS.1770-5-202311-I |
| R3 | EBU R128 | Official recommendation | Loudness normalization and permitted maximum level guidance. | https://tech.ebu.ch/publications/r128 |
| R4 | ITU-T P.56 | Official standard | Active speech level measurement. | https://www.itu.int/rec/T-REC-P.56 |
| R5 | W3C Media Capture | Official web standard | Echo cancellation is framed around removing system playback from microphone input. | https://www.w3.org/TR/mediacapture-streams/ |
| R6 | Microsoft AEC Challenge | Official benchmark repo | Full-band echo-cancellation datasets and metrics. | https://github.com/microsoft/AEC-Challenge |
| R7 | Microsoft DNS Challenge | Official benchmark repo | Noise suppression, personalized/non-personalized tracks, and interferer evaluation. | https://github.com/microsoft/DNS-Challenge |
| R8 | CHiME-8 DASR | Challenge paper/preprint | Provides a difficult multi-speaker distant ASR/diarization benchmark context. | https://arxiv.org/abs/2407.16447 |
| R9 | CHiME-7/8 review | Review/preprint | Shows challenging acoustic environments remain hard even for intensive ensembles. | https://arxiv.org/abs/2507.18161 |

## Metrics And Benchmark

- Primary metric: end-to-end latency from source speech to English playback
- Secondary metrics: P.56 active-level error, LUFS/dBFS target error, true-peak/clipping rate, translated speech intelligibility, residual source audibility, ERLE/AECMOS where applicable, DNSMOS/P.835 for enhancement
- Dataset or fixture: local room loopback with known source track, translated reference, loudspeaker output, and microphone recording; AEC Challenge and DNS Challenge fixtures for capture hygiene; FSD50K/Freesound and MUSAN from `fixtures/audio_eval/external_corpora/catalog.json` for crowd/noise augmentation after license filtering
- Disposable command: `scripts/benchmark_playback_suppression_fixture.py`,
  `make audio-eval-playback-suppression-contract-check`, and
  `make audio-eval-playback-suppression-check`; host-room command:
  `scripts/run_real_room_playback_suppression.py`,
  `make real-room-playback-suppression-probe-route`,
  `make real-room-playback-suppression-sweep-routes`,
  `make real-room-playback-suppression-qualify-device`,
  `make real-room-playback-suppression-sweep-devices`,
  `make real-room-playback-suppression-contract-check`, and
  `make real-room-playback-suppression-check`
- Pass condition: no clipping, stable loudness matching, source residual reduction measured honestly, and no translated-output distortion
- Current prototype result on June 12, 2026: four FLEURS translated-playback surrogate segments
  passed with max source/playback level error 0.0 dB, minimum source residual reduction 10.0 dB,
  minimum translated-to-residual ratio 10.011 dB, zero clipped samples, rendered peak -9.205 dBFS,
  and the explicit claim `ducking_masking_simulation_not_true_cancellation`
- Current host-room result on June 12, 2026: SoundWire/WASAPI loopback evidence failed. The 48 kHz
  device qualification recorded audible calibration but failed reference fidelity
  (`source_calibration_reference_correlation=-0.000594`,
  `translated_calibration_reference_correlation=-0.000034`). The current full aligned -18 dB playback
  run measured 83.799 dB source residual reduction, but calibration/reference fidelity failed
  (`source_calibration_reference_correlation=-0.000557`,
  `translated_calibration_reference_correlation=-0.000375`) and translated-output preservation failed
  (`translated_output_correlation=0.000026`, distortion 91.632 dB). The release gate now recomputes
  these metrics from WAV artifacts and requires audible, reference-faithful source/translated
  calibration recordings. The route-probe sweep and device sweep helpers are only
  `release_proof=false` triage artifacts for choosing candidate input/output routes; this remains
  the release blocker until a full room check passes.
- Current route-probe result on June 12, 2026: MME input `1` to output `3` at 16 kHz recorded the
  chirp sentinel but matched it with only `route_probe_reference_confidence=0.000215`; WASAPI input
  `12` to output `10` at 48 kHz failed stream opening with PortAudio `Invalid number of channels`.
  Treat this as a route/processing blocker before speech cancellation tuning.

## Integration Plan

- Contract fields: `input_level_dbfs`, `output_level_dbfs`, `original_voice_suppression_db`, `playback_latency_ms`
- Claim boundary field: `source_suppression_mode` distinguishes `UNAVAILABLE`,
  `OVERLAY_DUCKING`, `HEADPHONE_ISOLATED`, and `TRUE_CANCELLATION`; the dB field alone is not a
  cancellation claim.
- Gateway/Rust/Flutter files: Rust mixer helpers when low-latency audio code begins; gateway reports diagnostics; Flutter displays warnings
- Fallback behavior: translated audio at safe matched volume, no suppression claim, visible "suppression unavailable" state
- Rollback trigger: suppression artifacts make translated speech less intelligible than source speech

## Detractor Concerns

- Strongest objection: "Cancel the original voice" is not generally achievable from arbitrary room audio without constrained microphones, speakers, reference signals, and listener position; speakerphone mode should be described as translated overlay plus echo-controlled capture.
- Cheapest falsifying benchmark: play a known source voice and translated voice in the same room, record with the target microphone, and measure residual source intelligibility plus translated distortion.
- Fallback path: masking, ducking, headphones/earpiece mode, captions, and honest suppression diagnostics.
- Decision reversal condition: a measured source-suppression algorithm proves stable suppression without corrupting translated playback on the target device class.
