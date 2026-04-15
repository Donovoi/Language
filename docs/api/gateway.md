# Gateway API

## Why this exists

The gateway gives the Flutter client and future tools a stable local API for session state and mock speaker scenes. It exists to make product flows testable before any live translation backend is introduced.

## Boundary owned by the gateway

Base endpoints:
- `GET /health` returns service liveness.
- `GET /v1/session` returns the current in-memory session.
- `POST /v1/session/reset` restores the default mock-backed session state.
- `GET /v1/speakers` returns the current ranked speaker list.
- `POST /v1/speakers` accepts speaker inputs, re-ranks them, and updates session state.
- `GET /v1/mock/scene` returns a deterministic mock scene for a requested session mode.

The gateway owns JSON models, in-memory session state, and service-layer prioritization. It deliberately does not own live transport, authentication, persistence, or provider SDK orchestration yet.

## Intentionally deferred

- websocket or gRPC streaming
- real diarization events
- translation or TTS adapters
- persistent session storage
