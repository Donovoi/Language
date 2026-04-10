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
