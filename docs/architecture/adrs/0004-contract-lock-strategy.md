# ADR 0004: Lock shared contracts with proto plus CI before full codegen

## Status
Accepted

## Why this exists
The repository already has one protobuf file plus hand-authored Python and Flutter models, which made it too easy for the contract to drift quietly.
Full generated bindings across Rust, Python, and Flutter would be ideal long term, but it is still too much churn for the current mock-first stage.

## Boundary it owns
- `proto/session.proto` is the canonical ledger for shared gateway/client session payloads and SSE event shapes.
- `services/gateway/app/models.py` and `apps/field_app_flutter/lib/models/` keep hand-authored models, but they must expose explicit contract manifests that CI can compare to the proto.
- CI also validates the overlapping Rust `audio_core` subset so shared domain fields and `SessionMode` variants cannot drift silently even though Rust does not yet model transport-only caption and lane-status fields.

## What is intentionally deferred
This ADR does not land generated bindings, Flutter-to-Rust FFI, or a full Rust transport model.
It also does not require `audio_core` to absorb caption text, translation status, or `top_speaker_id` yet; those remain transport-layer concerns until the runtime ownership decision settles.