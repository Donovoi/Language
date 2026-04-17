# ADR 0002: Split responsibilities across Flutter, Rust, and Python

## Status
Accepted

## Why this exists
The MVP needs one UI codebase, deterministic prioritization logic, and a fast service layer for mock scenes and future model integrations.
Using Flutter, Rust, and Python together gives the project a clear boundary between presentation, low-latency domain logic, and provider-facing orchestration.

## Boundary it owns
- Flutter owns the cross-platform app shell and operator experience.
- Rust owns typed session state and prioritization policy that can later sit behind an FFI bridge.
- Python owns HTTP APIs, mock scenes, and future adapter orchestration.

## What is intentionally deferred
This ADR does not wire Flutter to Rust directly yet.
It also leaves translation, diarization, and TTS implementations behind future gateway adapters.
