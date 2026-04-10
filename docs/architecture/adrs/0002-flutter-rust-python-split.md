# ADR 0002: Split the starter template across Flutter, Rust, and Python

## Status
Accepted

## Why this exists

The product needs one operator-facing client across mobile and desktop, deterministic scoring logic that can move closer to realtime paths, and a service layer that can absorb fast-changing ML and provider integrations. Flutter, Rust, and Python match those needs with the least early complexity.

## Boundary owned by this decision

- Flutter owns presentation, local state, and future platform integration points.
- Rust owns typed domain primitives, priority scoring policies, and future low-latency shared logic.
- Python owns HTTP APIs, mock scenes, and future translation, diarization, and TTS adapters.
- Realtime translation logic does not live in Flutter because the UI layer should consume state, not own latency-sensitive orchestration.

## Intentionally deferred

This ADR does not approve full FFI wiring, streaming transports, or backend provider choices. Those remain deferred until the mock-first flow is stable and the Rust boundary is proven useful.
