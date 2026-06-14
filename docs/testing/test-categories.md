# Test Categories

Use `scripts/run_test_category.py` when you do not know which low-level target to run.

```bash
python3 scripts/run_test_category.py list
python3 scripts/run_test_category.py quick
python3 scripts/run_test_category.py release-status
python3 scripts/run_test_category.py all
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 test-category list
pwsh -NoProfile -File scripts/dev_container.ps1 test-category quick
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-status
pwsh -NoProfile -File scripts/dev_container.ps1 test-category all
```

Use `--dry-run` to inspect the command plan. By default, full output goes to
`artifacts/test-categories/` while the terminal shows only summaries plus bounded failure tails. Pass
`--verbose` when you deliberately want live logs.

## Category Map

| Category | Runs | Does not run |
| --- | --- | --- |
| `quick` | Local contract sanity checks for release-gate, live-capture, headphone isolation, and real-room playback reports. | Docker, model downloads, hardware capture, release gate. |
| `contracts` | All local audio/report contract self-tests. | Docker, model downloads, hardware capture, release gate. |
| `core` | The repository core check path. | Audio model profiles and physical audio evidence. |
| `audio-fixtures` | Disposable Docker audio fixtures for deterministic overlap, real-speech smoke, crowd-noise fixture, translation, capture replay, playback/suppression fixture, and fallback TTS. | Hardware capture, optional large model baselines, release gate. |
| `voice-candidates` | Same-voice candidate validation plus optional SpeechBrain ASV scoring. | Generating candidate audio. Requires candidate artifacts. |
| `optional-models` | Pyannote, Sortformer, Whisper, WeSep, and causal bridge baselines. | Hardware capture. Some steps need `HF_TOKEN` and accepted model terms. |
| `hardware` | Host device listing, listener-ear route preflight, and virtual listener-ear lab. | Release proof. Run physical capture/score commands from the runbook when ready. |
| `evidence-kit` | Manual listener-ear recording kit, readiness check, and raw WAV dropbox. | Audio playback/recording. Put the three exported WAVs in the dropbox, then rerun. |
| `recording-status` | Readiness check for the three manual listener-ear WAVs. | Playback, recording, scoring, or release proof. |
| `release-evidence` | Prepare/import/check the manual listener-ear kit, then print compact release status. | Audio playback/recording, placeholder-label scoring, or release proof. |
| `release-status` | Compact release-gate blocker and next-action handoff. | Exits zero by default; use `release` for strict failure semantics. |
| `release` | Strict audio release gate. | Evidence generation. Expected to fail until required artifacts are present. |
| `all` | `quick`, `core`, and `audio-fixtures`. | Hardware, release, optional model downloads, and artifact-dependent voice candidate scoring. |

## Recommended Paths

New contributor sanity check:

```bash
python3 scripts/run_test_category.py quick
```

Before a normal code handoff:

```bash
python3 scripts/run_test_category.py contracts
```

Before an audio-fixture change handoff:

```bash
python3 scripts/run_test_category.py audio-fixtures --continue-on-failure
```

Before release review:

```bash
python3 scripts/run_test_category.py all --continue-on-failure
python3 scripts/run_test_category.py release-evidence
python3 scripts/run_test_category.py release
```

The `release` category is allowed to fail when the operator handoff says physical evidence is
missing. Do not treat fixture-only passes as source-suppression release proof.
Use `release-status` first when you only need the current blocker and the next commands without a
large JSON or Markdown handoff.
Use `release-evidence` when you want the listener-ear kit prepared, current WAV dropbox imported if
complete, readiness checked, and the compact status printed in one pass.
Use `python3 scripts/release_audio_status.py --full-commands` when you need the detailed hardware
command list in the terminal.

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
