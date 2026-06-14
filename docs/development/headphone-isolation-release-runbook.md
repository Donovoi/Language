# Headphone/Earpiece Isolation Release Runbook

This runbook separates two useful but different activities:

- **Virtual listener-ear lab**: deterministic simulated WAV artifacts for development and CI. This
  must remain `release_proof=false`.
- **Physical listener-ear measurement**: real microphone evidence required by `release_audio_gate.py`
  for a release that uses the headphone/earpiece fallback path.

## Virtual Lab

Use this when changing scorer logic, artifact handling, reports, or release-gate rejection behavior:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action virtual-lab -Python $env:LANGUAGE_PYTHON
python scripts/release_audio_gate.py --headphone-isolation-report artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/headphone-virtual-lab-report.json --json *> artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/release-gate-virtual-rejection.json
if ($LASTEXITCODE -eq 0) { throw "expected release gate to reject the virtual listener-ear report" }
"release gate rejected the virtual listener-ear report as expected"
```

Expected result:

- `headphone-isolation-virtual-lab` passes its own virtual quality gates.
- `release_audio_gate.py` rejects the virtual report.

The virtual lab writes:

- `artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/source-reference.wav`
- `artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/source-open-ear-recording.wav`
- `artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/source-isolated-ear-recording.wav`
- `artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/translated-playback-reference.wav`
- `artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/translated-headphone-recording.wav`
- `artifacts/audio_eval/runs/headphone-earpiece-virtual-lab/headphone-virtual-lab-report.json`

Do not copy or rename this report to satisfy the release gate. It is synthetic and intentionally uses
`fixture_kind=headphone_earpiece_virtual_lab`.

## Physical Hardware Requirement

The release gate needs a microphone located where the listener's ear would be. A Bluetooth headset by
itself is not enough because its microphone is outside the earcup and measures the room, not the
sound at the listener ear.

Acceptable measurement setups:

- Best: a USB lavalier, USB measurement mic, wired earbud mic, or phone-as-USB-mic placed inside or
  flush with the headphone earcup.
- Good: an external recorder/phone records WAVs at the listener-ear point, then
  `scripts/run_headphone_isolation_check.py score-manual` validates the manifest and scores those
  WAV files.
- Triage only: place one headphone earcup over the laptop microphone array to check route behavior.
  The built-in laptop mic path does not unlock guided capture or release evidence; use a real
  listener-ear mic/recorder for scored release proof.

The microphone must capture three states from the same listener-ear position:

1. **Open-ear source control**: source speaker plays, headphone/earpiece isolation is absent.
2. **Isolated source**: source speaker plays at the same volume and route, headphone/earpiece is
   sealed/enabled over the measurement mic.
3. **Translated headphone playback**: headphone/earpiece stays sealed over the measurement mic while
   translated playback plays through the headphone output.

## Current Windows Device Pattern

Device numbers can shift. Always list devices first:

```powershell
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action list-devices
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action preflight --sample-rate-hz 48000 --input-channels 1 --output-channels 2
# If the report finds a capture-ready external listener-ear input, run its generated
# confirm_physical_input_preflight command. It includes --selected-route.
```

The categorized front door keeps the first pass shorter:

```powershell
python scripts/run_test_category.py route-triage
python scripts/run_test_category.py guided-capture --dry-run
```

Do not copy device IDs from this document. Windows audio IDs change when Bluetooth, USB, docks,
monitors, and default devices change. Treat the generated preflight report as the source of truth for
the current host, then copy only the commands it prints for that run.

For final evidence, prefer a measurement mic physically inside/at the earcup. Use laptop arrays,
monitor microphones, and headset microphones only for route triage unless the device is physically
positioned at the listener-ear acoustic point. Replace every `LISTENER_EAR_INPUT`,
`SOURCE_SPEAKER_OUTPUT`, `HEADPHONE_OUTPUT`, and hardware label below with values from the current
preflight report and your actual fixture.
The preflight command does not play or record audio. It writes
`artifacts/audio_eval/runs/headphone-earpiece-preflight/headphone-preflight-report.json` and
`headphone-preflight-report.md` with a device inventory fingerprint, likely input/output roles,
route candidates, and a recommendation to try guided capture after physical input confirmation or
switch to the manual external recorder path. It always remains `release_proof=false`.
Guided host `capture` requires the generated `--preflight-report` binding so the scored PortAudio
evidence is tied to the selected, physically confirmed route.

## Windows Host-Local Wrapper

For Windows physical-audio work, prefer the host-local wrapper because Docker cannot reliably expose
Bluetooth/WASAPI/USB audio routes. The wrapper creates `.venv-audio-local/`, installs `numpy`, and
installs `sounddevice` only for commands that touch host devices:

```powershell
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action self-test
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action list-devices
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action preflight --sample-rate-hz 48000 --input-channels 1 --output-channels 2
# Follow the generated confirm/capture commands only when preflight reports a capture-ready route.
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action prepare-manual --sample-rate-hz 48000 --playback-gain-db -18
```

The wrapper auto-selects a supported Python `>=3.11,<3.14`; set `LANGUAGE_PYTHON` only when you need
to point it at a specific interpreter. Use `-RecreateVenv` if dependency installation gets into a bad
state. A passing virtual lab or route probe is still not release evidence; the release gate needs a
physical listener-ear recording scored by `score-manual` or `capture`.

## Hardware Setup Checklist

Before running the physical commands:

1. Pair or connect the headphones and confirm Windows is using the stereo headphone output,
   not a hands-free/headset call profile, for translated playback.
2. Use a separate measurement input for release evidence: a USB/lavalier mic at the earcup is best.
   If you only have the laptop mic array, use it for `route_probe_triage_only`, not final capture.
3. Do not use a headset microphone as release evidence unless the mic is physically positioned at
   the listener-ear acoustic point. The headset mic mostly hears the room and Windows
   voice processing, so it is useful for route triage but not final isolation proof.
4. Put the source speaker where it will be during the test, then leave it fixed. For the open-ear
   control, the measurement mic should be exposed to the source. For the isolated-source take, seal
   the headphone earcup over the same mic position while the source speaker plays the same route.
5. Disable processing that can rewrite the probe signal: Windows audio enhancements, spatial audio,
   input noise suppression, AGC/auto gain, echo cancellation, and communications ducking. In Windows
   Sound settings, also set Communications behavior to "Do nothing" if available.
6. Start with moderate output volume and `--playback-gain-db -18`. Increase to `-12` only if the
   report says `recording_too_quiet`; lower it if the report says `recording_clipped`.
7. Keep the room quiet during the short probe and capture takes. Do not move the mic, source speaker,
   or headphone seal between the matching source-open and source-isolated takes.
8. Run `preflight` before `sweep-routes` or `probe-route`. If you are using the laptop mic array,
   place one headphone earcup directly over the laptop mic opening and use the generated
   `route_probe_triage_only` command only. If preflight does not report a capture-ready route, use
   the manual kit or connect a real listener-ear input before guided capture.

When a sweep or probe fails, use the diagnosis before changing hardware:

- `route_not_opened`: the device id, host API, sample rate, or channel count is incompatible; relist
  devices and try the same physical devices through another listed host API.
- `recording_too_quiet`: move the measurement mic closer to the sound being measured or raise gain in
  small steps.
- `reference_not_detected` or `reference_distorted`: after the recording is loud enough, Windows or
  Bluetooth processing is altering the probe, the wrong route is being recorded, or the mic is
  hearing room spill instead of the target path; disable processing, try another host API, or use a
  wired/USB listener-ear mic.
- `recording_clipped`: lower playback gain or device output volume and rerun the same route.
- `gate:headphone_route_outputs_distinct`: the selected source and headphone outputs resolved to the
  same PortAudio device; pick a different physical output route unless you are deliberately running a
  non-release shared-output diagnostic.

## Physical Test Commands

Sweep uncertain routes first. This command is expected to produce a triage report; it is not release
evidence, and `--score-warning-only` is acceptable here because the goal is to preserve diagnostics:

To refresh preflight and print the current safest route-probe command without playing audio:

```powershell
python scripts/run_test_category.py route-triage
```

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action sweep-routes -Python $env:LANGUAGE_PYTHON --triple 17:14:16 --sample-rate-hz 48000 --channel-config 1:2 --playback-gain-db -18 --score-warning-only
```

Use the sweep's `candidate_attempt` only to choose the next single route. Then probe that exact route.
Copy the candidate's exact `sample_rate_hz`, `input_channels`, and `output_channels` into both
`probe-route` and `capture`. This command must pass without `--score-warning-only` before capture is
worth running:

If the sweep has no candidate, inspect `summary.failure_summary` and each attempt's `diagnosis`.
`recording_too_quiet` means fix gain or mic placement before chasing fidelity. `reference_not_detected`
or `reference_distorted` on a loud route means the microphone heard sound but not the generated probe
faithfully; disable Windows enhancements/noise suppression/AGC/echo processing, move the mic or
source, try another host API/device triple, or use a USB/wired listener-ear mic. `gate:*` entries
count failed quality gates such as same-device source/headphone routing.

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action probe-route -Python $env:LANGUAGE_PYTHON --measurement-input-device 17 --source-output-device 14 --headphone-output-device 16 --sample-rate-hz 48000 --input-channels 1 --output-channels 2 --playback-gain-db -18
```

If it fails:

- move the source speaker closer to the measurement mic for the open-ear/source probe
- keep the headphone earcup sealed around the measurement mic for the headphone probe
- increase playback gain in small steps, for example `--playback-gain-db -12`, while avoiding clipping
- retry with MME candidates if WASAPI is not reference-faithful

If Bluetooth, PortAudio, or Windows processing keeps the guided route from passing, switch to the
manual external-recorder path instead of lowering thresholds:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action prepare-manual -Python $env:LANGUAGE_PYTHON --sample-rate-hz 48000 --playback-gain-db -18
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action check-manual -Python $env:LANGUAGE_PYTHON --score-warning-only
```

This writes release-derived playback references, a JSON manifest, and a human-readable recording
checklist under
`artifacts/audio_eval/runs/headphone-earpiece-manual-kit/`:

- `source-reference.wav`
- `translated-playback-reference.wav`
- `manual-recording-manifest.json`
- `manual-recording-checklist.md`

Optionally dry-run the manifest playback plan before touching the recorder:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action play-manual -Python $env:LANGUAGE_PYTHON --dry-run --source-output-device 14 --headphone-output-device 16
```

For a minimal hardware setup, use:

- source output: laptop speakers or another speaker that is not the Bluetooth headset
- headphone output: the Bluetooth headset/earpiece being tested
- measurement recorder: a phone voice recorder, USB mic, field recorder, or other recorder that is not
  the same Bluetooth headset mic

Put the recorder mic at the listener-ear position. For `source-open-ear-recording.wav`, leave the
headset/earpiece off or unsealed so the recorder hears the source speaker. For
`source-isolated-ear-recording.wav`, keep the source speaker in the same place and seal the headset
earcup/earpiece over the recorder mic. For `translated-headphone-recording.wav`, keep the seal and
play the translated reference through the headset. Keep the playback level comfortable and avoid
clipping on the recorder; it is better to repeat the take than to rescue distorted audio later.

Record the three expected takes with the mic at the listener-ear position. Export each recording as
16-bit PCM WAV at the kit sample rate, and trim pre-roll so the played reference begins within 500 ms
of the recording start. The release gate recomputes alignment with the same 500 ms window; use a
wider alignment window only for diagnosis, not release proof.

- `source-open-ear-recording.wav`: source reference through the original speaker, headphone/earpiece
  removed or isolation disabled.
- `source-isolated-ear-recording.wav`: same source reference and mic position, headphone/earpiece
  sealed over the mic.
- `translated-headphone-recording.wav`: translated reference through the headphone/earpiece while it
  remains sealed over the mic.

If you want the repo to play the references instead of using an external media player, start the
phone/USB recorder for each prompted take and run:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action play-manual -Python $env:LANGUAGE_PYTHON --source-output-device 14 --headphone-output-device 16
```

The playback helper requires explicit source/headphone output devices, or one deliberate
`--output-device` override, so a default Windows route does not silently produce bad recordings. Use
`--allow-default-output` only for diagnosis when you have manually verified the default route.

This writes `manual-playback-log.json` with `release_proof=false`. It is only an operator trace; the
release evidence still comes from the scored listener-ear WAV recordings.

If your recorder exports arbitrary filenames, place the three WAVs in the generated
`raw-listener-ear-recordings/` dropbox and rerun `collect-headphone-evidence`, or import them into
the manifest's expected paths before checking or scoring:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action import-manual -Python $env:LANGUAGE_PYTHON --source-open-ear-recording RAW_SOURCE_OPEN.wav --source-isolated-ear-recording RAW_SOURCE_ISOLATED.wav --translated-headphone-recording RAW_TRANSLATED.wav --allow-downmix
```

`--allow-downmix` is only a channel-format policy for stereo recorder exports. The importer does not
normalize loudness, denoise, repair clipping, resample, auto-select best takes, or trim for score. It
rejects exact reference clones, duplicate raw takes, placeholder labels supplied to the importer, and
target overwrites unless `--allow-overwrite` is explicit. It writes `manual-import-log.json` with
`release_proof=false`; only `score-manual` can produce release evidence. The collection wrapper uses
the same importer automatically when all three dropbox WAVs exist, and skips auto-import instead of
implicitly replacing target recordings on reruns.

Then run the manual-recording doctor without warning-only and with the real labels you will use for
scoring. It checks that the kit manifest remains `release_proof=false`, both reference WAVs exist and
still hash-match the manifest, all five WAVs are mono 16-bit PCM at the kit sample rate, the three
listener-ear recordings meet the minimum duration, and the score labels are no longer placeholders. It writes
`artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.json` and
`manual-recording-status.md`:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
$headphoneLabel = "REPLACE_WITH_HEADPHONE_MODEL"
$fixtureLabel = "REPLACE_WITH_EARCUP_AND_MIC_POSITION"
$microphoneLabel = "REPLACE_WITH_MIC_MODEL_AND_POSITION"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action check-manual -Python $env:LANGUAGE_PYTHON --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel
```

Only score the real recordings after this command reports ready. The manifest-driven scorer reuses
the reference and recording paths from the kit and writes the release-gated headphone isolation report:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
$headphoneLabel = "REPLACE_WITH_HEADPHONE_MODEL"
$fixtureLabel = "REPLACE_WITH_EARCUP_AND_MIC_POSITION"
$microphoneLabel = "REPLACE_WITH_MIC_MODEL_AND_POSITION"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action score-manual -Python $env:LANGUAGE_PYTHON --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel
```

The manual kit itself is not release evidence: it has `release_proof=false`. Only the scored report at
`artifacts/audio_eval/runs/headphone-earpiece-isolation/headphone-isolation-report.json` can satisfy
the release gate, and only if its WAV-derived metrics pass. Replace every `REPLACE_WITH_*` variable
value with specific hardware and fixture text before treating the score as release evidence. Use the
lower-level `headphone-isolation-score` command only when intentionally overriding manifest paths or
thresholds for diagnosis.

After preflight reports a capture-ready selected route and the probe passes, run guided capture with
the generated preflight report:

```powershell
$env:LANGUAGE_PYTHON = "C:\Path\To\python.exe"
$headphoneLabel = "REPLACE_WITH_HEADPHONE_MODEL"
$fixtureLabel = "REPLACE_WITH_EARCUP_AND_MIC_POSITION"
$microphoneLabel = "REPLACE_WITH_MIC_MODEL_AND_POSITION"
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action capture -Python $env:LANGUAGE_PYTHON --measurement-input-device LISTENER_EAR_INPUT --source-output-device SOURCE_SPEAKER_OUTPUT --headphone-output-device HEADPHONE_OUTPUT --preflight-report artifacts/audio_eval/runs/headphone-earpiece-preflight/headphone-preflight-report.json --sample-rate-hz 48000 --input-channels 1 --output-channels 2 --playback-gain-db -18 --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel
```

Or use the guarded category wrapper:

```powershell
$env:LANGUAGE_MEASUREMENT_INPUT_DEVICE = "LISTENER_EAR_INPUT"
$env:LANGUAGE_SOURCE_OUTPUT_DEVICE = "SOURCE_SPEAKER_OUTPUT"
$env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE = "HEADPHONE_OUTPUT"
$env:LANGUAGE_HEADPHONE_DEVICE_LABEL = $headphoneLabel
$env:LANGUAGE_ISOLATION_FIXTURE_LABEL = $fixtureLabel
$env:LANGUAGE_MEASUREMENT_MICROPHONE_LABEL = $microphoneLabel
python scripts/run_test_category.py guided-capture
```

Then run the release gate:

```powershell
python scripts/release_audio_gate.py --json
```

The release gate should pass only when the physical headphone report proves:

- open-ear source recording is audible and reference-faithful
- isolated source recording is at least 12 dB lower than the open-ear source control
- translated headphone playback is audible and reference-faithful
- WAV hashes, labels, device identity, and fingerprints are coherent

## Bluetooth-Only Limitation

With only a headset and no separate measurement mic, we can run:

- virtual lab
- route probes
- non-release triage reports

We cannot honestly claim final listener-ear isolation unless some microphone is placed at the
listener-ear acoustic position. The cheapest unblocker is a small USB/lavalier microphone or a phone
configured as a real input microphone, placed inside the headphone earcup during the guided capture.
When using a phone or recorder, export WAV rather than compressed audio; the manual doctor will fail
until the files are mono 16-bit PCM WAV at the exact sample rate named in the manifest.
