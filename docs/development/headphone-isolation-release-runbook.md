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

## Physical Test Commands

Probe first. This command must pass without `--score-warning-only` before capture is worth running:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-probe-route --measurement-input-device 17 --source-output-device 14 --headphone-output-device 16 --sample-rate-hz 48000 --playback-gain-db -18
```

If it fails:

- move the source speaker closer to the measurement mic for the open-ear/source probe
- keep the headphone earcup sealed around the measurement mic for the headphone probe
- increase playback gain in small steps, for example `--playback-gain-db -12`, while avoiding clipping
- retry with MME candidates if WASAPI is not reference-faithful

After the probe passes, run guided capture:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-capture --measurement-input-device 17 --source-output-device 14 --headphone-output-device 16 --sample-rate-hz 48000 --playback-gain-db -18 --headphone-device-label "Sony WH-1000XM6 over-ear headphones" --isolation-fixture-label "WH-1000XM6 left earcup sealed over built-in laptop microphone array" --measurement-microphone-label "built-in laptop microphone array used as improvised listener-ear microphone"
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
