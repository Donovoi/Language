# Headphone/Earpiece Isolation Release Runbook

This runbook separates two useful but different activities:

- **Virtual listener-ear lab**: deterministic simulated WAV artifacts for development and CI. This
  must remain `release_proof=false`.
- **Physical listener-ear measurement**: real microphone evidence required by `release_audio_gate.py`
  for a release that uses the headphone/earpiece fallback path.

## Virtual Lab

Use this when changing scorer logic, artifact handling, reports, or release-gate rejection behavior:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-virtual-lab
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
  `scripts/run_headphone_isolation_check.py score` scores those WAV files.
- Improvised: place one headphone earcup over the laptop microphone array so the laptop mic acts as
  the listener-ear mic. This can be tried with the current hardware but is not as trustworthy as a
  real mic inside the earcup.

The microphone must capture three states from the same listener-ear position:

1. **Open-ear source control**: source speaker plays, headphone/earpiece isolation is absent.
2. **Isolated source**: source speaker plays at the same volume and route, headphone/earpiece is
   sealed/enabled over the measurement mic.
3. **Translated headphone playback**: headphone/earpiece stays sealed over the measurement mic while
   translated playback plays through the headphone output.

## Current Windows Device Pattern

Device numbers can shift. Always list devices first:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-list-devices
```

On the current host snapshot, likely candidates were:

- source speaker output: `14` (`Speakers (SoundWire Speakers), Windows WASAPI`)
- headphone output: `16` (`Headphones (WH-1000XM6), Windows WASAPI`)
- laptop microphone array: `17` (`Microphone Array..., Windows WASAPI`)
- headset microphone: `18` (`Headset (WH-1000XM6), Windows WASAPI`)

For final evidence, prefer a measurement mic physically inside/at the earcup. Use the headset mic only
for route triage unless it is physically positioned at the listener-ear point. The `17` examples below
are the current-host improvised path with the laptop mic array; replace `17` and the microphone label
with the real USB/lav/recorder input when you have that hardware.

## Hardware Setup Checklist

Before running the physical commands:

1. Pair or connect the WH-1000XM6 headphones and confirm Windows is using the stereo headphone output,
   not a hands-free/headset call profile, for translated playback.
2. Use a separate measurement input for release evidence: a USB/lavalier mic at the earcup is best. If
   you only have the laptop mic array, place one headphone earcup directly over the laptop mic opening
   and keep that placement unchanged for the isolated-source and translated-playback takes.
3. Do not use the WH-1000XM6 headset microphone as release evidence unless the mic is physically
   positioned at the listener-ear acoustic point. The headset mic mostly hears the room and Windows
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

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-sweep-routes --triple 17:14:16 --sample-rate-hz 48000 --channel-config 1:2 --playback-gain-db -18 --score-warning-only
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
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-probe-route --measurement-input-device 17 --source-output-device 14 --headphone-output-device 16 --sample-rate-hz 48000 --input-channels 1 --output-channels 2 --playback-gain-db -18
```

If it fails:

- move the source speaker closer to the measurement mic for the open-ear/source probe
- keep the headphone earcup sealed around the measurement mic for the headphone probe
- increase playback gain in small steps, for example `--playback-gain-db -12`, while avoiding clipping
- retry with MME candidates if WASAPI is not reference-faithful

If Bluetooth, PortAudio, or Windows processing keeps the guided route from passing, switch to the
manual external-recorder path instead of lowering thresholds:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-prepare-manual --sample-rate-hz 48000 --playback-gain-db -18
```

This writes release-derived playback references and a checklist manifest under
`artifacts/audio_eval/runs/headphone-earpiece-manual-kit/`:

- `source-reference.wav`
- `translated-playback-reference.wav`
- `manual-recording-manifest.json`

Record the three expected WAVs named in the manifest with the mic at the listener-ear position. Export
each recording as mono 16-bit PCM WAV at the kit sample rate, and trim pre-roll so the played
reference begins within 500 ms of the recording start. The release gate recomputes alignment with the
same 500 ms window; use a wider alignment window only for diagnosis, not release proof.

- `source-open-ear-recording.wav`: source reference through the original speaker, headphone/earpiece
  removed or isolation disabled.
- `source-isolated-ear-recording.wav`: same source reference and mic position, headphone/earpiece
  sealed over the mic.
- `translated-headphone-recording.wav`: translated reference through the headphone/earpiece while it
  remains sealed over the mic.

Then score those real recordings:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-score --source-reference artifacts/audio_eval/runs/headphone-earpiece-manual-kit/source-reference.wav --source-open-ear-recording artifacts/audio_eval/runs/headphone-earpiece-manual-kit/source-open-ear-recording.wav --source-isolated-ear-recording artifacts/audio_eval/runs/headphone-earpiece-manual-kit/source-isolated-ear-recording.wav --translated-playback-reference artifacts/audio_eval/runs/headphone-earpiece-manual-kit/translated-playback-reference.wav --translated-headphone-recording artifacts/audio_eval/runs/headphone-earpiece-manual-kit/translated-headphone-recording.wav --headphone-device-label "Sony WH-1000XM6 over-ear headphones" --isolation-fixture-label "WH-1000XM6 left earcup sealed over listener-ear microphone" --measurement-microphone-label "placeholder REPLACE_WITH_REAL_MIC_MODEL_AND_POSITION"
```

The manual kit itself is not release evidence: it has `release_proof=false`. Only the scored report at
`artifacts/audio_eval/runs/headphone-earpiece-isolation/headphone-isolation-report.json` can satisfy
the release gate, and only if its WAV-derived metrics pass. Replace every `placeholder REPLACE_WITH_*`
label with specific hardware and fixture text before treating the score as release evidence.

After the probe passes, run guided capture:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-capture --measurement-input-device 17 --source-output-device 14 --headphone-output-device 16 --sample-rate-hz 48000 --input-channels 1 --output-channels 2 --playback-gain-db -18 --headphone-device-label "Sony WH-1000XM6 over-ear headphones" --isolation-fixture-label "WH-1000XM6 left earcup sealed over built-in laptop microphone array" --measurement-microphone-label "built-in laptop microphone array used as improvised listener-ear microphone"
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

With only the WH-1000XM6 headset and no separate measurement mic, we can run:

- virtual lab
- route probes
- non-release triage reports

We cannot honestly claim final listener-ear isolation unless some microphone is placed at the
listener-ear acoustic position. The cheapest unblocker is a small USB/lavalier microphone or a phone
configured as a real input microphone, placed inside the headphone earcup during the guided capture.
