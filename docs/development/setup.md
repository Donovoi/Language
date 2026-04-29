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
- the gateway Pydantic models in `services/gateway/app/models.py`
- the Flutter JSON models in `apps/field_app_flutter/lib/models/`
- the documented overlap subset in `crates/audio_core`

If you change a shared field or enum, update the proto and the hand-authored manifests in the same change so the workflow stays green.

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

The smoke script uses non-mutating `mode=FOCUS` preview requests for the session and SSE checks so the result stays deterministic even if the in-memory session was changed earlier during local testing.

If you need a non-default bind address, override `GATEWAY_HOST` and `GATEWAY_PORT` for both the smoke target and `make gateway-run`.

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
- `services/gateway` Python API gateway

## Notes

The repository keeps a mock-first developer path. The Flutter app source is tracked in-repo, while local platform runners are regenerated with `flutter create .` during bootstrap and run commands.
For release prep, use `release-builds.md`, `release-checklist.md`, `versioning.md`, and the root `CHANGELOG.md`.
