# Gateway Service

## Ownership

This service owns the local FastAPI API, SQLite-backed session state, and deterministic mock scenes for the Language MVP.
It exposes the client-facing HTTP contract while keeping prioritization logic small and testable.
The current mock-first pass now includes a deterministic SSE event stream for session snapshots and
speaker-lane updates.

## Configuration

The gateway can load the repo-root `.env` file automatically when you start it with `python -m app.main`.
That keeps the existing source defaults intact while making host/port changes and container runs configurable.

| Variable | Default | Used by | Notes |
| --- | --- | --- | --- |
| `LANGUAGE_GATEWAY_HOST` | `127.0.0.1` | `python -m app.main`, container entrypoint | Override to `0.0.0.0` for container runs. |
| `LANGUAGE_GATEWAY_PORT` | `8000` | `python -m app.main`, container entrypoint | Change the bind port without editing code. |
| `LANGUAGE_GATEWAY_LOG_LEVEL` | `info` | `python -m app.main`, container entrypoint | Passed straight through to Uvicorn. |
| `LANGUAGE_GATEWAY_SESSION_DB_PATH` | `services/gateway/.state/session-store.sqlite3` | `SessionStore` | Optional absolute or relative SQLite file path for local session persistence. |
| `LANGUAGE_GATEWAY_AUTH_TOKEN` | unset | mutating gateway routes | Optional. When set, `POST`/`PUT`/`DELETE` routes require `Authorization: Bearer <token>`. Leave unset for friction-free local mock development. |
| `LANGUAGE_GATEWAY_TRANSLATION_PROVIDER` | `disabled` | translation adapter | Set to `libretranslate` to enable real text translation. |
| `LANGUAGE_GATEWAY_TRANSLATION_BASE_URL` | unset | translation adapter | Base URL for a LibreTranslate-compatible service, for example `https://translate.example.com`. |
| `LANGUAGE_GATEWAY_TRANSLATION_API_KEY` | unset | translation adapter | Optional API key forwarded to the provider as `api_key`. |
| `LANGUAGE_GATEWAY_TRANSLATION_TARGET_LANGUAGE` | `en` | translation adapter | Default target language when a speaker update omits `target_language_code`. |
| `LANGUAGE_GATEWAY_TRANSLATION_TIMEOUT_MS` | `4000` | translation adapter | HTTP timeout for provider requests. |
| `FIELD_APP_API_BASE_URL` | platform default | Flutter `--dart-define` | Leave unset to keep the built-in fallback (`10.0.2.2:8000` on Android emulator, `127.0.0.1:8000` elsewhere). |

Edit the repo-root `.env` (copied from `.env.example`) when you want explicit local defaults.

The gateway persists the current session id, mode, ranked speaker list, and speaker lock state in SQLite.
Delete the configured database file when you want a completely fresh local state.

## Translation adapter behavior

Task 9 lands one real-provider path without changing the Flutter client contract:

- when `LANGUAGE_GATEWAY_TRANSLATION_PROVIDER=libretranslate` and
	`LANGUAGE_GATEWAY_TRANSLATION_BASE_URL` are both configured, the gateway translates any
	`READY` speaker update whose `translated_caption` is empty but `source_caption` is present
- `POST /v1/speakers` therefore supports server-side translation by sending
	`translated_caption: null` and either a speaker-level `target_language_code` or the env default
- `POST /v1/mock/live-ingest` reuses the same store mutation path, so the existing Flutter SSE flow
	starts showing provider-backed captions automatically when the adapter is enabled
- if the adapter is disabled or unconfigured, the scripted live ingest keeps its built-in mock
	translations exactly as before
- if the adapter call fails, the speaker lane moves to `ERROR` and `status_message` carries the
	provider error instead of crashing the session update

## Auth and health behavior

Read endpoints stay open so the local demo, SSE inspection, and smoke checks still work without extra setup.
When `LANGUAGE_GATEWAY_AUTH_TOKEN` is configured, mutating routes require a matching bearer token:

```text
Authorization: Bearer <LANGUAGE_GATEWAY_AUTH_TOKEN>
```

Health endpoints now split responsibilities:

- `GET /health` — compatibility alias that still returns `{"status": "ok"}`
- `GET /livez` — process liveness probe
- `GET /readyz` — readiness probe that verifies app settings plus the current session store

Each response also includes `X-Request-ID`, and request logs now emit one structured JSON line per request with the request ID, method, path, status code, and duration.

## Run and validate

```bash
python -m pip install -e '.[dev]'
python -m ruff check .
python -m pytest
```

For day-to-day local work, the existing hot-reload path still works:

```bash
uvicorn app.main:app --reload
```

When you want the gateway to honor `LANGUAGE_GATEWAY_*` from the repo-root `.env`, use:

```bash
python -m app.main
```

For Flutter, pass the optional base URL override at compile time:

```bash
flutter run --dart-define=FIELD_APP_API_BASE_URL=http://127.0.0.1:8000
```

## Container path

From the repo root, you can build and run the gateway in a container:

```bash
docker build -f services/gateway/Dockerfile -t language-gateway services/gateway
docker run --rm -p 8000:8000 --env-file .env -e LANGUAGE_GATEWAY_HOST=0.0.0.0 language-gateway
```

The container exposes the same `GET /health` endpoint at `http://127.0.0.1:8000/health`.

## Deliberately out of scope

This service does not own realtime audio capture, diarization, or TTS.
Only a minimal text-in/text-out translation adapter is included for the current beta slice.
Broader provider orchestration still stays deferred until the mock-first API contract is stable.
