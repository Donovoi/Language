# ADR 0004: Lock shared contracts with proto plus CI before full codegen

## Status
Accepted

_Update (2026-05-01):_ The repository has since added generated Python/Dart contract artifacts and a Rust transport crate (`crates/session_proto`). This ADR still owns the original decision to lock the shared contract before full runtime-wide migration.

## Why this exists
The repository already has one protobuf file plus hand-authored Python and Flutter models, which made it too easy for the contract to drift quietly.
Full generated bindings across Rust, Python, and Flutter would be ideal long term, but it is still too much churn for the current mock-first stage.

## Boundary it owns
- `proto/session.proto` is the canonical ledger for shared gateway/client session payloads and SSE event shapes.
- Generated contract artifacts now feed the active gateway and Flutter model layers, and CI verifies those generated files stay current.
- CI also validates the overlapping Rust `audio_core` subset so shared domain fields and `SessionMode` variants cannot drift silently even though the domain crate still does not model transport-only caption and lane-status fields.

## What is intentionally deferred
This ADR does not land Flutter-to-Rust FFI or full runtime-wide generated binding adoption.
It also does not require `audio_core` to absorb caption text, translation status, or `top_speaker_id` yet; those remain transport-layer concerns until the runtime ownership decision settles.