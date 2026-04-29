# Cross-Stack Integration Smoke Runbook

Use this runbook to prove the local mock stack still behaves like one system instead of a pile of polite strangers.
It keeps the automated gateway checks and the manual Flutter verification separate so contributors can finish the full pass in under 10 minutes.

## Scope

This smoke covers the current internal demo path:

- gateway health and startup
- SSE delivery on `GET /v1/events/stream`
- simulated live ingest on `POST /v1/mock/live-ingest`
- persistence and restart recovery for the gateway session snapshot
- Flutter expectations for live lane updates, lock state, and reconnect behavior

## Before you start

Run the local bootstrap once if this machine has not built the repo before:

```bash
make bootstrap
```

The commands below assume local write auth is disabled, which is the default development setup. If you set `LANGUAGE_GATEWAY_AUTH_TOKEN`, add the bearer header when you trigger live ingest manually.

## Automated smoke: 2–3 minutes

Run the isolated gateway smoke first:

```bash
make smoke-integration-demo
```

What it does automatically:

- starts an isolated gateway instance on `http://127.0.0.1:8010`
- uses a temporary SQLite session database so the check does not reuse your normal local state
- verifies `GET /health`
- subscribes to `GET /v1/events/stream` and confirms live ingest drives progressive `session.snapshot` events
- starts `POST /v1/mock/live-ingest`, waits for multiple streamed updates, then stops the run before completion
- restarts the gateway on the same temporary database
- verifies the persisted session is restored by both `GET /v1/session` and the first SSE snapshot after restart

If port `8010` is already in use, rerun with a different smoke port:

```bash
make smoke-integration-demo INTEGRATION_SMOKE_PORT=8012
```

## Manual Flutter verification: 5–7 minutes

Use the automated smoke above as the gateway confidence check, then do this short UI pass to verify the Flutter client still behaves correctly with the same live ingest path.

### 1. Start the gateway on a persistent local database

In terminal A:

```bash
mkdir -p tmp
LANGUAGE_GATEWAY_SESSION_DB_PATH=$PWD/tmp/flutter-integration-smoke.sqlite3 make gateway-run GATEWAY_PORT=8010
```

Leave this terminal running.

### 2. Launch the Flutter app against the local gateway

In terminal B, choose one of these:

Desktop or simulator that can reach localhost directly:

```bash
make flutter-run FLUTTER_RUN_ARGS="--dart-define=FIELD_APP_API_BASE_URL=http://127.0.0.1:8010"
```

Android emulator:

```bash
make flutter-run FLUTTER_RUN_ARGS="--dart-define=FIELD_APP_API_BASE_URL=http://10.0.2.2:8010"
```

### 3. Confirm the initial connected state

Once the app loads, verify:

- the title is `Language Field Console`
- the session starts in `Focus mode`
- the status chip shows `Live updates connected`
- at least one speaker lane is visible without tapping `Refresh session`

### 4. Trigger live ingest while you watch the lanes

In terminal C:

```bash
curl --fail -X POST "http://127.0.0.1:8010/v1/mock/live-ingest?mode=FOCUS&interval_ms=350"
```

If local write auth is enabled, use:

```bash
curl --fail -H "Authorization: Bearer $LANGUAGE_GATEWAY_AUTH_TOKEN" -X POST "http://127.0.0.1:8010/v1/mock/live-ingest?mode=FOCUS&interval_ms=350"
```

### 5. Verify the live Flutter expectations

Within the next 30–60 seconds, confirm all of the following happen without manually refreshing the app:

- Alice moves through `LISTENING`, `TRANSLATING`, and `READY`
- Bruno becomes the `Primary translation target`
- translated captions update in place on the active lane
- Bruno briefly shows the locked state with `Pinned by operator.`
- Bruno later returns to the unlocked state with `Lock released.`
- the app keeps the `Live updates connected` badge while the ingest run is active

### 6. Verify persistence and reconnect

Stop the gateway in terminal A with `Ctrl+C`, then restart it with the exact same command from step 1.

Back in the Flutter app, verify:

- the status briefly recovers back to `Live updates connected`
- the last session snapshot is still present after the restart
- using `Refresh session` does not reset the lanes back to the original demo state

## Pass criteria

Mark the smoke as passing only when:

- the automated command exits `0`
- the Flutter app shows live ingest changes without a manual refresh
- the post-restart Flutter session still matches the last gateway snapshot you saw before the restart

## When this fails

Common failure hints:

- `make smoke-integration-demo` fails immediately: another process is already bound to the chosen smoke port
- the Flutter app shows `Live updates offline`: the app is pointed at the wrong base URL or the gateway was not started yet
- the ingest request returns `401`: local write auth is enabled and the bearer header was omitted
- the session resets after restart: verify the gateway was restarted with the same `LANGUAGE_GATEWAY_SESSION_DB_PATH`
