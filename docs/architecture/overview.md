# Architecture Overview

## Layers

### Client layer
Flutter provides the shared application shell for mobile and desktop.

### Realtime core
Rust owns deterministic, low-latency logic such as:
- audio-oriented domain types
- speaker priority policies
- mixer-safe state transitions

### Service layer
Python services expose provider-agnostic APIs for:
- session control
- speaker events
- translation provider adapters
- future diarization and synthesis integrations

## Why this split

- Flutter gives the fastest path to a shared cross-platform UI.
- Rust is well suited for reusable low-latency logic.
- Python remains the best place for fast model experimentation and service integration.

## Repository shape

- `apps/` user-facing applications
- `crates/` Rust libraries
- `services/` Python APIs
- `docs/` product and architecture records
- `proto/` shared contracts

## Shared contract boundary

- `proto/session.proto` is the canonical ledger for shared gateway/client session payloads and SSE envelopes.
- Python and Flutter still use hand-authored transport models for now, but each side carries an explicit contract manifest and CI fails when those models drift from the proto.
- Rust `audio_core` intentionally validates only the overlapping domain subset today (`SessionMode` plus the shared fields on `SessionState` and `SpeakerState`), which keeps the low-latency core decoupled from transport-only caption and lane-status fields until full codegen or FFI wiring is worth the churn.
