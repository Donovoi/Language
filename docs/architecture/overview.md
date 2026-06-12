# Architecture Overview

## Product Loop

Language is organized around one realtime loop:

1. capture overlapping speech from a noisy local scene
2. separate/diarize speakers and estimate each speaker's input level
3. detect source language and translate speech to English
4. clone or condition the output voice to match the source speaker
5. play the English output at the same perceived volume
6. suppress the original voice so the translated mix is intelligible

The current implementation simulates steps 1, 2, 4, 5, and 6 with contract metadata while real providers
are being selected and integrated.

## Runtime Layers

### Client layer
Flutter provides the shared application shell for mobile and desktop, including speaker lanes,
language/translation state, volume matching, voice-clone readiness, translated-audio stream state,
and source-suppression diagnostics.

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
- future capture, diarization, speaker separation, voice-clone/TTS, and source-suppression integrations

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
- The contract now includes product-loop metadata: detected language confidence, input/output dBFS levels, overlapping speaker ids, voice-clone status, translated-audio stream ids, original-voice suppression diagnostics, and playback latency.
- Rust `audio_core` intentionally validates only the overlapping domain subset today (`SessionMode` plus the shared fields on `SessionState` and `SpeakerState`), which keeps the low-latency core decoupled from transport-only caption, audio-provider, and lane-status fields until full codegen or FFI wiring is worth the churn.
