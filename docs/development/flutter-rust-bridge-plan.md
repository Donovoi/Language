# Flutter and Rust bridge plan

## Why this exists

The current starter template keeps prioritization logic split between the Rust core and the Python mock gateway. This note records how the client can later move deterministic scoring closer to the shared Rust layer without forcing FFI into the first pass.

## Boundary owned by this plan

A future bridge should expose typed Rust functions for session updates, speaker scoring, and mode-aware ranking to the Flutter client through `flutter_rust_bridge` or an equivalent generated FFI layer. Flutter should continue to own UI state and rendering, while Rust should own reusable policy and validation logic.

## Intentionally deferred

This plan does not add generated bindings, native packaging, or shared build automation yet. It also does not choose the exact transport between the gateway and the client once live streaming replaces the mock endpoints.
