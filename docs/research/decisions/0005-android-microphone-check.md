# Android foreground microphone check

- Decision id: 0005
- Date: 2026-11-15
- Subsystem: capture-vad-noise-front-end (capture diagnostic only)
- Research: question matrix validated with `prepare_robin_research_pack.py --check`;
  equivalent literature-agent and independent detractor pass, using primary Android docs.

## Product constraint and recommendation

Give the Android field console a real, local microphone check before connecting capture to
translation. Record three seconds of mono PCM16 at 16 kHz, show signal levels, and let the
user explicitly replay or discard it. Retain the clip only in memory while the screen is
foreground. Do not upload it, automatically play it, change system volume, or label it as
translated audio. No new dependency, service, model, or proto field is needed.

Select native `AudioRecord` and `AudioTrack` through a small Flutter method channel.
The runner-up, `MediaRecorder` plus `MediaPlayer`, is suitable for file recordings but adds
encoding/file handling before PCM can be inspected. This is a diagnostic, not a low-latency
streaming architecture decision. The maximum five-second buffer is 160 kB before copies;
hardware assumptions are Android API 24+ with a working 16 kHz mono input.

## Evidence

All sources below are official implementation documentation, not peer-reviewed quality claims.

- [AudioRecord](https://developer.android.com/reference/android/media/AudioRecord):
  nonblocking reads, explicit error codes and active input routing support bounded capture.
- [Recording overview](https://developer.android.com/media/platform/mediarecorder):
  runtime microphone permission, foreground restrictions, and device-dependent input processing.
- [AudioTrack](https://developer.android.com/reference/android/media/AudioTrack):
  static PCM playback exposes frame progress; it does not prove acoustic audibility.
- [Audio focus](https://developer.android.com/media/optimize/audio-focus):
  acquire focus before playback, stop on loss, abandon on completion; Android 15+ requires
  the foreground app or a suitable foreground service.
- [Flutter channels](https://docs.flutter.dev/platform-integration/platform-channels):
  binary PCM can cross the existing platform channel without another plugin.

Use `VOICE_RECOGNITION` input and report the selected source; do not claim unprocessed or
calibrated sound pressure levels. RMS and peak dBFS describe the returned samples only.

## Metrics and disposable benchmark

- VM: native capture/playback, invalid duration, concurrency, cancellation and clearing contracts.
  An emulator signal (including zeroes) is never physical audio evidence.
- Phone: inspect returned PCM independently in Dart; check length, finite RMS/peak, signal
  presence, active input route and system-silenced flag. Replay and check output frame progress.
- Commands: `make android-vm-smoke`; `make android-audio-smoke ANDROID_DEVICE=<serial>`.
- A phone run with room sound proves the capture path returns signal. It does not establish
  speech intelligibility, known-stimulus fidelity, translation, same-voice output or suppression.
- No waveform is written to test logs; only aggregate diagnostics. Release evidence stays false.

## Detractor round before implementation

- Strongest objection: plausible PCM can be silence, an unexpected route, or processed room noise;
  a completed future alone proves neither acoustic fidelity nor a functioning real-time pipeline.
- Cheapest falsifying benchmark: run capture with a known external stimulus and compare PCM,
  then deny permission, stop mid-capture and background the Activity. Verify no clip survives.
- Mitigation: native monotonic deadline, nonblocking worker reads, atomic cancellation,
  `finally` release, route/silence diagnostics, explicit playback with transient focus,
  stop on background/focus loss/headphone disconnect. UI reports silence without a success claim.
- Fallback: show actionable capture/permission errors and leave the existing caption console usable.
- Reversal: repeated physical-device capture stalls, unsupported format or unreliable cleanup
  would block this path and favor a maintained capture plugin or alternate native configuration.
- Remaining limitation: room-sound runs are signal smoke tests; a controlled stimulus and human
  listening remain necessary before claiming audio quality. This round does not alter release gates.

## Implementation detractor and regression coverage

The code-review detractor found that a mounted Flutter lifecycle observer could mask a broken
native `onPause` handler in the smoke test. The test now unmounts that observer before its direct
capture, backgrounds the Activity, and requires cancellation followed by an empty clip after resume.
Playback cancellation is also bounded to one second, and permission restoration failures fail the run.

The first VM run exposed a platform-specific regression that widget mocks missed: native channel
PCM arrives as a read-only byte view. The Dart wrapper now makes an owned writable copy before
discarding; a read-only-view regression test exercises that case. The runner uses `--no-uninstall`
because Flutter otherwise removes the APK before permission restoration can run.
