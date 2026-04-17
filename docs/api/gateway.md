# Gateway API

## Why this exists
The gateway provides the local contract between the Flutter field client and the mock-first service layer.
It exposes deterministic session and speaker data while the rest of the system is still under construction.

## Boundary it owns
Base URL: `http://127.0.0.1:8000`

### `GET /health`
Returns a simple readiness payload:

```json
{"status": "ok"}
```

### `GET /v1/session`
Returns the in-memory session snapshot.
Optional query parameter: `mode=FOCUS|CROWD|LOCKED|UNSPECIFIED`.

### `POST /v1/session/reset`
Resets the in-memory session to the selected mode.
Default mode is `FOCUS`.

### `GET /v1/speakers`
Returns the currently ranked speaker list for the active session.

### `POST /v1/speakers`
Replaces the current speaker list with the supplied states and returns a ranked session response.
Optional query parameter: `mode=FOCUS|CROWD|LOCKED|UNSPECIFIED`.

### `GET /v1/mock/scene`
Builds a deterministic mock scene for `FOCUS`, `CROWD`, or `LOCKED` mode.
The response includes the ranked session plus the supported modes list.

## What is intentionally deferred
The gateway currently keeps all session state in memory.
Streaming transport, auth, persistence, and provider adapters are deferred until the mock-first workflow is stable.
