# Language

Language is a realtime speech translation app for noisy, multi-speaker rooms.

The product goal is to listen to overlapping speech from multiple people, detect each source
language, translate it to English, synthesize the English audio in the same speaker voice at the
same perceived volume, and suppress the original source voice so the user hears the translated mix
instead.

The repo is still mock-first, but the scaffolding, evidence gates, and audio fixtures are now shaped
around that full audio loop.

## Architecture

- `apps/field_app_flutter` - Flutter field console.
- `services/gateway` - FastAPI gateway, mock scene orchestration, session API, and provider-facing
  adapter boundaries.
- `crates/` - Rust realtime session primitives, prioritization policy, and protobuf bindings.
- `proto/session.proto` - canonical shared contract.
- `fixtures/audio_eval` - deterministic audio-evaluation fixtures.
- `scripts/` - local, Docker, audio, release-gate, and packaging commands.
- `docs/` - development, release, testing, architecture, and research notes.

## Quickstart

Bootstrap local SDKs and the gateway virtual environment:

```bash
bash scripts/bootstrap_dev.sh
```

Run the local smoke baseline:

```bash
make smoke-local-demo
```

Windows without Make or Bash:

```powershell
pwsh -NoProfile -File scripts/smoke_local_demo.ps1
```

Run the gateway:

```bash
make gateway-run
```

Run the Flutter app:

```bash
make flutter-run
```

## Tests

Use the categorized runner first. It keeps the normal path small by writing command output to log
files by default; pass `--verbose` only when you want live logs in the terminal.

```bash
python3 scripts/run_test_category.py quick
python3 scripts/run_test_category.py list
python3 scripts/run_test_category.py release-status
python3 scripts/run_test_category.py release-progress
python3 scripts/run_test_category.py release-artifacts
python3 scripts/run_test_category.py smoke-local
python3 scripts/run_test_category.py all
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 test-category quick
pwsh -NoProfile -File scripts/dev_container.ps1 test-category list
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-status
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-progress
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-artifacts
pwsh -NoProfile -File scripts/dev_container.ps1 test-category smoke-local
pwsh -NoProfile -File scripts/dev_container.ps1 test-category all
```

Make shortcuts:

```bash
make test-quick
make test-contracts
make test-audio-fixtures
make test-all
```

Common categories:

| Category | Use it for | Notes |
| --- | --- | --- |
| `quick` | Fast local contract sanity checks | No Docker, model downloads, or hardware access. |
| `contracts` | Audio/report contract self-tests | Still local and hardware-free. |
| `core` | Repository contract, Rust, gateway, and app checks | Uses `make check` or `scripts/check_local.ps1`. |
| `smoke-local` | Local gateway smoke baseline | Verifies health, session, and SSE demo endpoints. |
| `audio-fixtures` | Disposable Docker audio fixtures | Capture, translation, playback, fallback TTS. |
| `hardware` | Host audio discovery and listener-ear planning | Run deliberately when testing devices. |
| `route-triage` | Host headphone route preflight and probe handoff | Prints the probe command; does not run it. |
| `guided-capture` | Strict host-guided listener-ear capture | Requires explicit device IDs, concrete labels, and a confirmed preflight report. |
| `physical-audio-handoff` | Current host route, manual kit, and checklist | Best first command before a hardware session. |
| `evidence-kit` | Manual listener-ear recording kit/dropbox | Creates/checks the folder for the three release WAVs. |
| `recording-status` | Listener-ear WAV readiness | Use after adding the three manual recordings. |
| `release-evidence` | One-command listener-ear evidence handoff | Prepare/import/check the kit, then print release status. |
| `release-evidence-score` | Score complete listener-ear evidence | Requires real WAVs and concrete hardware labels. |
| `release-status` | Concise release blocker summary | Low-token next-action handoff; exits zero by default. |
| `release-progress` | Milestone percentages | Evidence-linked estimate for push summaries. |
| `release-artifacts` | Local source/gateway release handoff | Builds clean artifacts, checksums them, then smokes the packaged gateway wheel. |
| `release` | Strict release-gate status | Expected to fail until physical evidence is present. |
| `all` | Automated non-interactive suites | Excludes hardware, guided capture, release, optional model downloads, and artifact-dependent voice checks. |

Detailed test categories and the old command matrix live in
`docs/testing/test-categories.md`. Disposable environment details live in
`docs/development/disposable-test-environments.md`.

On Windows, `core` can use a portable Flutter SDK at `C:\tmp\flutter\bin\flutter.bat`, or set
`LANGUAGE_FLUTTER` to another Flutter executable.

## Audio Hardware

For host audio on Windows, Docker is the wrong boundary because Bluetooth, WASAPI, USB, and built-in
devices need direct access to the host audio stack.

Start with a non-recording preflight:

```powershell
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action self-test
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action list-devices
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action preflight --sample-rate-hz 48000 --input-channels 1 --output-channels 2
```

The wrapper auto-selects a supported Python `>=3.11,<3.14`; set `LANGUAGE_PYTHON` only when you need
to point it at a specific interpreter.

A laptop built-in mic and speakers are useful for route triage. Release evidence still needs real
listener-ear recordings: open-ear source, isolated source, and translated headphone playback from the
same listener-ear position. See `docs/development/headphone-isolation-release-runbook.md`.

To refresh preflight and print a deliberate non-release route probe command:

```powershell
python scripts/run_test_category.py route-triage
```

Before a physical recording session, refresh route triage, prepare/check the kit, and write the
current checklist:

```powershell
python scripts/run_test_category.py physical-audio-handoff
```

If preflight reports a capture-ready route and you have a real listener-ear mic in place, set the
device IDs and labels, then run:

```powershell
python scripts/run_test_category.py guided-capture --dry-run
python scripts/run_test_category.py guided-capture
```

Prepare/check the manual recording kit, import any complete dropbox WAVs, and print release status:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 test-category release-evidence
```

After the three WAVs are in the dropbox, set concrete labels and score the evidence:

```powershell
$env:LANGUAGE_HEADPHONE_DEVICE_LABEL = "Sony WH-1000XM6"
$env:LANGUAGE_ISOLATION_FIXTURE_LABEL = "left earcup sealed over phone recorder"
$env:LANGUAGE_MEASUREMENT_MICROPHONE_LABEL = "phone WAV recorder at listener-ear point"
python scripts/run_test_category.py release-evidence-score
```

Build local source and gateway package artifacts from a clean tree, then smoke the packaged gateway:

```powershell
python scripts/run_test_category.py release-artifacts
```

The focused commands remain available when you only want one part:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 test-category evidence-kit
pwsh -NoProfile -File scripts/dev_container.ps1 test-category recording-status
```

## Release Gate

The release gate is intentionally stricter than fixture tests:

```bash
python3 scripts/release_audio_gate.py
```

For a shorter status and next-action handoff:

```bash
python3 scripts/run_test_category.py release-status
```

That command also writes `artifacts/release/physical-audio-checklist.md` for the current hardware
handoff.

Use `python3 scripts/release_audio_status.py --full-commands` when you need the full hardware
command list in the terminal.

Use this for the milestone percentages reported after pushes:

```bash
python3 scripts/run_test_category.py release-progress
```

It writes:

- `artifacts/release/audio-gate-report.json`
- `artifacts/release/audio-gate-report.md`

Use the Markdown report for the operator handoff and the JSON report as the authoritative pass/fail
artifact. The current release path is still blocked until playback/source-suppression evidence is
collected from real listener-ear recordings or true room-cancellation evidence.

## Token Budget

This is mainly about keeping Codex/OpenAI development threads small. For long agent or CI runs,
prefer the quiet default:

```bash
python3 scripts/run_test_category.py quick
python3 scripts/run_test_category.py all --continue-on-failure
```

The runner stores full logs under `artifacts/test-categories/` and prints only summaries plus bounded
failure tails. Optional context-compression tools such as Headroom can be evaluated later, but they
should sit outside the release evidence path unless explicitly adopted and pinned.

See `docs/development/token-budget.md`.

## Research Gate

Use the sibling Robin checkout before choosing real audio models or providers:

```bash
python3 scripts/prepare_robin_research_pack.py
python3 scripts/prepare_robin_research_pack.py --check
python3 scripts/check_audio_corpus_catalog.py
```

Research notes and decisions live under `docs/research/`.

## Status

The repo currently includes:

- typed Rust session and speaker primitives with prioritization tests
- FastAPI gateway with health, session, speaker, mock-scene, live-ingest, persistence, and SSE routes
- Flutter operator shell for speaker lanes, translated captions, audio metadata, and lock controls
- protobuf-backed contract generation across gateway, Flutter, and Rust
- disposable Docker profiles for core and audio-eval work
- deterministic and small real-speech audio fixtures for overlap, translation, playback, fallback TTS,
  diarization, target-speaker extraction, and same-voice candidate validation
- release-gate reporting that rejects fixture-only, synthetic, self-attested, or incomplete physical
  evidence

## Contributing

- Keep changes scoped to the subsystem you are touching.
- Add or update disposable test scaffolding when introducing new runtimes, SDKs, models, or providers.
- Run the smallest relevant category before handoff.
- Keep research-backed audio decisions in `docs/research/decisions/`.
- Keep the README short; put detailed runbooks in `docs/`.
