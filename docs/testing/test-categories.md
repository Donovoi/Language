# Test Categories

Use `scripts/run_test_category.py` when you do not know which low-level target to run.

```bash
python3 scripts/run_test_category.py list
python3 scripts/run_test_category.py quick
python3 scripts/run_test_category.py release-status
python3 scripts/run_test_category.py release-progress
python3 scripts/run_test_category.py release-artifacts
python3 scripts/run_test_category.py smoke-local
python3 scripts/run_test_category.py all
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 test-category list
pwsh -NoProfile -File scripts/dev_container.ps1 test-category quick
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-status
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-progress
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-artifacts
pwsh -NoProfile -File scripts/dev_container.ps1 test-category smoke-local
pwsh -NoProfile -File scripts/dev_container.ps1 test-category all
```

Use `--dry-run` to inspect the command plan. By default, full output goes to
`artifacts/test-categories/` while the terminal shows only summaries plus bounded failure tails. Pass
`--verbose` when you deliberately want live logs.

## Category Map

| Category | Runs | Does not run |
| --- | --- | --- |
| `quick` | Local contract sanity checks for release-gate, live-capture, headphone isolation, and real-room playback reports. | Docker, model downloads, hardware capture, release gate. |
| `contracts` | All local audio/report contract self-tests. | Docker, model downloads, hardware capture, release gate. Creates `.venv-audio-contract/` for fixture dependencies. |
| `core` | The repository core check path: `make check` on Make runners or `scripts/check_local.ps1` on PowerShell. | Audio model profiles and physical audio evidence. |
| `smoke-local` | Local gateway smoke baseline for `/health`, `/v1/session`, and deterministic SSE. | Flutter UI, audio fixtures, or physical release proof. |
| `audio-fixtures` | Disposable Docker audio fixtures for deterministic overlap, real-speech smoke, crowd-noise fixture, translation, capture replay, playback/suppression fixture, and fallback TTS. | Hardware capture, optional large model baselines, release gate. |
| `voice-candidates` | Same-voice candidate validation plus optional SpeechBrain ASV scoring. | Generating candidate audio. Requires candidate artifacts. |
| `optional-models` | Pyannote, Sortformer, Whisper, WeSep, and causal bridge baselines. | Hardware capture. Some steps need `HF_TOKEN` and accepted model terms. |
| `hardware` | Host device listing, listener-ear route preflight, and virtual listener-ear lab. | Release proof. Run physical capture/score commands from the runbook when ready. |
| `route-triage` | Refresh host headphone preflight and print the deliberate route-probe command. | The printed command is not run automatically; if run, it plays/records audio and remains non-release triage. |
| `guided-capture` | Strict host-guided listener-ear capture and scoring through PortAudio. | Requires explicit `LANGUAGE_*` device IDs, concrete labels, and a physically confirmed selected-route preflight report. |
| `physical-audio-handoff` | Refresh host device listings and route triage, prepare/check the manual kit, and write the physical-audio checklist. | Audio playback/recording, scoring, or release proof. |
| `evidence-kit` | Manual listener-ear recording kit, readiness check, and raw WAV dropbox. | Audio playback/recording. Put the three exported WAVs in the dropbox, then rerun. |
| `recording-status` | Readiness check for the three manual listener-ear WAVs. | Playback, recording, scoring, or release proof. |
| `reference-playback-dry-run` | Validate the manual reference playback plan without playing audio. | Requires explicit source/headphone output IDs. |
| `reference-playback` | Play the manual source/translated references for an external listener-ear recorder. | Plays audio; start the external recorder first. Not release evidence. |
| `release-evidence` | Prepare/import/check the manual listener-ear kit, then print compact release status. | Audio playback/recording, placeholder-label scoring, or release proof. |
| `release-evidence-score` | Import/check and score complete listener-ear evidence when WAVs and concrete labels are ready. | Audio playback/recording. Placeholder labels keep scoring blocked. |
| `release-status` | Compact release-gate blocker and next-action handoff. | Exits zero by default; use `release` for strict failure semantics. |
| `release-progress` | Evidence-linked milestone percentages and total completion estimate. | Pass/fail release authority still lives in the strict `release` category. |
| `release-artifacts` | Clean local source bundle, gateway package handoff, packaged gateway smoke, and write-token auth smoke. | Refuses dirty trees; writes manifest/checksums under `dist/local-release-artifacts/`, installs the wheel in a temporary virtualenv, and verifies the packaged CLI server plus mutating-route auth. |
| `release` | Strict audio release gate. | Evidence generation. Expected to fail until required artifacts are present. |
| `all` | `quick`, `core`, `smoke-local`, and `audio-fixtures`. | Hardware, guided capture, release, optional model downloads, and artifact-dependent voice candidate scoring. |

## Recommended Paths

New contributor sanity check:

```bash
python3 scripts/run_test_category.py quick
```

Before a normal code handoff:

```bash
python3 scripts/run_test_category.py contracts
```

`contracts` uses `scripts/run_audio_contract.py` for fixture self-tests that need `numpy`, `scipy`,
and `soundfile`. The helper creates `.venv-audio-contract/` from
`docker/dev/requirements-audio-eval.txt`; the first run may need PyPI access or a warm pip cache.
Set `LANGUAGE_AUDIO_CONTRACT_PYTHON` to override the base Python.

Before an audio-fixture change handoff:

```bash
python3 scripts/run_test_category.py audio-fixtures --continue-on-failure
```

Before release review:

```bash
python3 scripts/run_test_category.py all --continue-on-failure
python3 scripts/run_test_category.py physical-audio-handoff
python3 scripts/run_test_category.py release
```

The `release` category is allowed to fail when the operator handoff says physical evidence is
missing. Do not treat fixture-only passes as source-suppression release proof.
Use `release-status` first when you only need the current blocker and the next commands without a
large JSON or Markdown handoff.
Use `physical-audio-handoff` before a hardware session when you want host device IDs, route triage,
the manual kit, readiness status, and `artifacts/release/physical-audio-checklist.md` refreshed
together.
Use `reference-playback-dry-run` after setting `LANGUAGE_SOURCE_OUTPUT_DEVICE` and
`LANGUAGE_HEADPHONE_OUTPUT_DEVICE` to validate the three-take playback plan without playing audio.
Use `reference-playback` only when the external listener-ear recorder is rolling; the playback log
remains `release_proof=false`.
Use `guided-capture --dry-run` after preflight reports a capture-ready route and before you let the
host play/record audio. It fails before touching devices unless the required `LANGUAGE_*` device and
label environment variables are set.
Use `release-evidence` when you want the listener-ear kit prepared, current WAV dropbox imported if
complete, readiness checked, and the compact status printed in one pass.
Use `release-evidence-score` after the WAVs are present and these environment variables hold concrete
labels: `LANGUAGE_HEADPHONE_DEVICE_LABEL`, `LANGUAGE_ISOLATION_FIXTURE_LABEL`, and
`LANGUAGE_MEASUREMENT_MICROPHONE_LABEL`.
Use `release-progress` after pushes when you need reproducible milestone percentages.
Use `smoke-local` to produce the log artifact that backs the release smoke progress estimate.
Use `release-artifacts` after validation when you need a clean local source/gateway artifact handoff plus packaged gateway and auth smokes.
Use `python3 scripts/release_audio_status.py --full-commands` when you need the detailed hardware
command list in the terminal.
On Windows, `core` defaults to `services\gateway\.venv\Scripts\python.exe` to avoid unsupported
global Python versions; override it with `LANGUAGE_CORE_PYTHON` when needed. Flutter is resolved from
`LANGUAGE_FLUTTER`, `FLUTTER`, PATH, or the portable `C:\tmp\flutter\bin\flutter.bat` SDK.

## Low-Level Commands

The category runner is only a front door. Existing Make targets and PowerShell actions remain
available for focused work:

```bash
make audio-eval-check
make audio-eval-translation-check
make headphone-isolation-contract-check
make release-audio-gate
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 audio-eval-check
pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-contract-check
pwsh -NoProfile -File scripts/dev_container.ps1 release-audio-gate
```

For physical listener-ear evidence, use
`docs/development/headphone-isolation-release-runbook.md`. That runbook covers route preflight,
guided capture, the manual recorder kit, the raw WAV dropbox, import, readiness checks, and scoring.

## Token-Friendly Operation

Prefer the quiet default for long runs in agent threads:

```bash
python3 scripts/run_test_category.py all --continue-on-failure
```

This keeps the thread short while preserving full logs under `artifacts/test-categories/`. When a
quiet step fails, the runner prints only the last `--tail-lines` lines. Increase the tail only when
the failure cannot be diagnosed from the default bounded tail.
