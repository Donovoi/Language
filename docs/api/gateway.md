# Gateway API

## Why this exists
The gateway provides the local contract between the Flutter field client and the mock-first service layer.
It exposes deterministic session and speaker data while the rest of the system is still under construction.

## Boundary it owns
Base URL: `http://127.0.0.1:8000`

### `GET /health`
Compatibility health alias retained for existing local scripts:

```json
{"status": "ok"}
```

### `GET /livez`
Returns a lightweight liveness payload for process-level probes:

```json
{"status": "alive"}
```

### `GET /readyz`
Returns a readiness payload that verifies the gateway settings and current session store are available:

```json
{
	"status": "ready",
	"checks": {
		"settings": "ok",
		"session_store": "ok",
		"session_snapshot": "ok"
	}
}
```

If a required dependency is missing or unhealthy, the endpoint returns `503 Service Unavailable`
with `status: "not_ready"` and a failing `checks` entry.

### Mutating endpoint auth
`POST`, `PUT`, and `DELETE` endpoints can be protected with a single shared bearer token.

- Env var: `LANGUAGE_GATEWAY_AUTH_TOKEN`
- Header: `Authorization: Bearer <token>`

Behavior:

- when the env var is unset or blank, write auth is disabled to keep local mock development friction-free
- when the env var is set, mutating endpoints return `401 Unauthorized` unless the bearer token matches
- read-only routes such as `GET /v1/session`, `GET /v1/speakers`, `GET /v1/events/stream`, `GET /livez`, and `GET /readyz` remain auth-free

### Request logging
Every request now emits one structured log line with:

- `request_id`
- `method`
- `path`
- `status_code`
- `duration_ms`

The gateway reuses an inbound `X-Request-ID` header when present and otherwise generates one, then returns it in the response headers for correlation.

### `GET /v1/session`
Returns the current persisted session snapshot.
Optional query parameter: `mode=FOCUS|CROWD|LOCKED|UNSPECIFIED` previews an alternate mode
without mutating the stored session.

### `PUT /v1/session/mode`
Updates the persisted session mode.
Optional query parameter: `mode=FOCUS|CROWD|LOCKED|UNSPECIFIED`.

### `POST /v1/session/reset`
Resets the persisted session to the selected deterministic mock scene.
Default mode is `FOCUS`, passed as a query parameter.

### `GET /v1/speakers`
Returns the currently ranked speaker list for the active session.

### `POST /v1/speakers`
Replaces the current persisted speaker list with the supplied states and returns a ranked session response.
Optional query parameter: `mode=FOCUS|CROWD|LOCKED|UNSPECIFIED`.

### `PUT /v1/speakers/{speaker_id}/lock`
Locks a single speaker in the current session, reranks the session, and returns the updated snapshot.

### `DELETE /v1/speakers/{speaker_id}/lock`
Releases a speaker lock in the current session, reranks the session, and returns the updated snapshot.

### `GET /v1/events/stream`
Returns a persistent Server-Sent Events stream for live session updates.
Optional query parameter: `mode=FOCUS|CROWD|LOCKED|UNSPECIFIED` previews an alternate mode without
mutating the stored session.

The stream currently emits:

- one initial `session.snapshot` event containing the current ranked session
- future `session.snapshot` events whenever persisted session state changes
- targeted `speaker.update` events for direct speaker lock/unlock mutations

Idle connections receive SSE keep-alive comments so clients can stay attached between mutations.

## Local persistence design
The gateway now keeps a single current-session snapshot in SQLite instead of process memory alone.

- default database path: `services/gateway/.state/session-store.sqlite3`
- optional override: `LANGUAGE_GATEWAY_SESSION_DB_PATH=/absolute/path/to/session-store.sqlite3`
- stored data: session id, active mode, and the full ordered speaker list including lock state

On startup, the gateway restores the last saved session. If no database row exists yet, it seeds the
store with the deterministic `FOCUS` mock scene so reset/demo flows keep behaving the same way.

### `GET /v1/mock/scene`
Builds a deterministic mock scene for `FOCUS`, `CROWD`, or `LOCKED` mode.
The response includes the ranked session plus the supported modes list.

### `GET /v1/mock/live-ingest`
Returns the status of the simulated live ingest runner.

The payload reports whether a run is currently active, whether the most recent run completed,
which scenario is available (`briefing`), the configured interval, and step progress fields
(`total_steps`, `applied_steps`, `remaining_steps`) alongside the current session mode and top speaker.

### `POST /v1/mock/live-ingest`
Starts a simulated live ingest run that mutates the existing persisted session over time.

Query parameters:

- `mode=FOCUS|CROWD|LOCKED|UNSPECIFIED` chooses the reset baseline before the script starts.
- `interval_ms=<positive integer>` controls the time between scripted updates. Default: `350`.

Behavior:

- resets the current session through the existing session store
- replays a scripted `briefing` scenario with more than 20 timed updates across Alice, Bruno, and Carmen
- uses the same store mutation APIs as the rest of the gateway, so existing SSE subscribers receive the updates without any client refresh
- returns `409 Conflict` if another live ingest run is already active

### `DELETE /v1/mock/live-ingest`
Stops the active simulated live ingest run and returns the final runner status snapshot.

## What is intentionally deferred
The gateway currently persists only one local session snapshot.
Streaming transport beyond SSE, multi-session history, and provider adapters are still deferred until the mock-first workflow is stable.
The current auth/logging/health work is intentionally minimal and aimed at internal or limited beta use, not full IAM or production observability.

## How this interacts with SSE
The live ingest runner does not bypass the existing transport layer.
Instead, it calls the same `SessionStore` mutation methods used by the REST controls:

- scripted caption/status changes call the existing speaker replacement flow, which emits `session.snapshot` SSE events
- scripted lock and unlock beats call the existing lock helpers, which emit both `session.snapshot` and `speaker.update` events

That means the current Flutter client can stay attached to `GET /v1/events/stream` and react to live demo data exactly the same way it reacts to manual operator actions.
