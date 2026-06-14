# Development Setup

## Toolchain

Install:
- Flutter stable
- Rust stable toolchain
- Python 3.11+
- Make

## One-command bootstrap

The repository includes `scripts/bootstrap_dev.sh` to install or reuse the local Flutter SDK,
create the gateway virtual environment, and prepare the Flutter app runners.

```bash
bash scripts/bootstrap_dev.sh
```

The script installs Flutter under `~/.local/share/flutter`, creates a launcher at
`~/.local/bin/flutter`, and creates `services/gateway/.venv` for Python dependencies so local
development does not rely on `--break-system-packages`.

## Suggested local workflow

```bash
make bootstrap
make smoke-local-demo
make smoke-integration-demo
make check
```

## Contract lock

Pushes and pull requests now run `.github/workflows/contract-lock.yml`, which compares `proto/session.proto` against:
- the generated gateway contract module in `services/gateway/app/generated/session_contract.py`
- the generated Flutter contract module in `apps/field_app_flutter/lib/generated/session_contract.dart`
- the gateway Pydantic model field shapes in `services/gateway/app/models.py`
- the documented overlap subset in `crates/audio_core`

If you change a shared field or enum in `proto/session.proto`, refresh the generated artifacts before you run checks:

```bash
make generate-contract-bindings
```

The repository validation now includes `contract-bindings-check`, so `make check` will fail if the generated Python and Flutter contract files are stale.

## Local smoke check

Use `make smoke-local-demo` to verify the repo-level demo baseline before you launch the full UI.

The smoke flow will:
- reuse an already healthy gateway at `http://127.0.0.1:8000`, or start a temporary one from `services/gateway/.venv`
- verify `GET /health`
- verify `GET /v1/session`
- verify a deterministic `FOCUS` preview on `GET /v1/events/stream?mode=FOCUS&max_events=1`
- clean up the temporary gateway automatically on exit

```bash
make smoke-local-demo
```

Windows hosts without `make`, Bash, or WSL can run the same gateway smoke baseline with:

```powershell
pwsh -NoProfile -File scripts/smoke_local_demo.ps1
```

The Windows-native equivalent for the broader repository validation path is:

```powershell
pwsh -NoProfile -File scripts/check_local.ps1
```

Pass `-SkipFlutter` only for a partial host run when Flutter is not installed. The plain command
refreshes `services/gateway/.venv` like `make check`; pass `-UseExistingGatewayVenv` only when you
deliberately want a faster reuse run. The gateway currently supports Python `>=3.11,<3.14`; pass
`-Python $env:LANGUAGE_PYTHON` after setting it to a supported interpreter path if the host's default
`python` is outside that range.
For local source and gateway package artifacts on Windows:

```powershell
pwsh -NoProfile -File scripts/package_local.ps1
```

That command auto-resolves a supported Python `>=3.11,<3.14`, refreshes
`services/gateway/.venv`, and rebuilds `services/gateway/dist/`; set `LANGUAGE_PACKAGE_PYTHON` or
pass `-Python` only when you need an explicit interpreter. Use `-Action source-bundle` for source
archives only. It writes a scope-specific local artifact handoff manifest and `SHA256SUMS.txt` under
`dist/local-release-artifacts/`.

For Windows host-audio headphone/earpiece isolation work, use the local wrapper instead of Docker so
PortAudio can see Bluetooth, WASAPI, USB, and built-in microphone devices directly:

```powershell
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action self-test
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action virtual-lab
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action preflight --sample-rate-hz 48000 --input-channels 1 --output-channels 2
pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action prepare-manual --sample-rate-hz 48000 --playback-gain-db -18
```

The wrapper creates `.venv-audio-local/` and installs only the packages needed for the selected
action. It auto-selects a supported Python `>=3.11,<3.14` from `-Python`, `LANGUAGE_PYTHON`,
`PYTHON`, Codex's bundled runtime, or `python`; set `LANGUAGE_PYTHON` when you need a specific
interpreter. Device-listing, preflight, route-probe, sweep, capture, and manual-playback actions also
install `sounddevice`; pure manifest/scoring actions need only `numpy`. Preflight is no-audio
hardware planning only and writes `release_proof=false` reports under
`artifacts/audio_eval/runs/headphone-earpiece-preflight/`. Laptop built-in microphones are useful
only for route triage: place the headphone earcup over the laptop mic opening only when following a
generated `route_probe_triage_only` command. Guided capture requires a capture-ready external
listener-ear input and the generated `--preflight-report`; otherwise use the manual recorder kit and
score the real listener-ear WAVs.

The smoke script uses non-mutating `mode=FOCUS` preview requests for the session and SSE checks so the result stays deterministic even if the in-memory session was changed earlier during local testing.

If you need a non-default bind address, override `GATEWAY_HOST` and `GATEWAY_PORT` for both the
smoke target and gateway run command. The PowerShell smoke honors the same `GATEWAY_HOST`,
`GATEWAY_PORT`, `GATEWAY_PYTHON`, `REQUEST_TIMEOUT_SECONDS`, and `SMOKE_START_TIMEOUT_SECONDS`
environment variables as the Bash smoke, and also exposes matching command parameters.

```bash
GATEWAY_HOST=127.0.0.1 GATEWAY_PORT=8010 make smoke-local-demo
GATEWAY_HOST=127.0.0.1 GATEWAY_PORT=8010 make gateway-run
```

If another process is already using the target port and it is not the Language gateway, stop it or choose a different `GATEWAY_PORT` before running the smoke check.

## Cross-stack integration smoke

Use `make smoke-integration-demo` when you want the deeper end-to-end gateway smoke that exercises live ingest and restart persistence, not just the static baseline.

The integration smoke will:
- start its own isolated gateway instance on `http://127.0.0.1:8010` by default
- use a temporary SQLite session database so the run does not reuse your normal local state
- verify `GET /health`
- subscribe to `GET /v1/events/stream` and confirm live updates arrive while `POST /v1/mock/live-ingest` runs
- stop the ingest run before completion, restart the gateway on the same database, and verify the persisted session is restored

```bash
make smoke-integration-demo
```

If port `8010` is already in use, override the isolated smoke port:

```bash
make smoke-integration-demo INTEGRATION_SMOKE_PORT=8012
```

For the short manual Flutter follow-up, use `docs/development/integration-smoke-runbook.md`.
That runbook keeps the automated gateway checks separate from the manual UI verification and shows how to pass `FIELD_APP_API_BASE_URL` through `make flutter-run` with `FLUTTER_RUN_ARGS`.

## Repository areas

- `apps/field_app_flutter` shared client shell
- `crates/audio_core` shared realtime primitives
- `crates/focus_engine` speaker priority logic
- `crates/session_proto` generated Rust protobuf transport layer
- `services/gateway` Python API gateway

## Notes

The repository keeps a mock-first developer path. The Flutter app source is tracked in-repo, while local platform runners are regenerated with `flutter create .` during bootstrap and run commands.
For release prep, use `release-builds.md`, `release-checklist.md`, `versioning.md`, and the root `CHANGELOG.md`.
