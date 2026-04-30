# Flutter/Rust Bridge Plan

## Why this exists
The current MVP keeps the Flutter app and Rust core loosely coupled so the product loop can move quickly.
A bridge plan makes the future integration path explicit without forcing premature FFI work into this pass.

## Boundary it owns
The intended future path is to expose Rust prioritization and session types through `flutter_rust_bridge` or an equivalent maintained bridge.
The Flutter layer should consume typed session snapshots from Rust while Python continues to orchestrate network-facing behavior.

The repository now also includes `crates/session_proto`, which generates Rust transport-facing protobuf types from `proto/session.proto` and converts the overlapping session/speaker subset into `audio_core`.
That crate is the bridge foundation for future Rust runtime reuse, but it does not yet expose Flutter-facing FFI.

## What is intentionally deferred
This document still defers Flutter-specific generated bindings, `flutter_rust_bridge` setup, and platform-specific native glue.
Those steps should start only after the transport crate and prioritization policy settle enough to avoid expensive churn.
