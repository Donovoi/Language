# Flutter/Rust Bridge Plan

## Why this exists
The current MVP keeps the Flutter app and Rust core loosely coupled so the product loop can move quickly.
A bridge plan makes the future integration path explicit without forcing premature FFI work into this pass.

## Boundary it owns
The intended future path is to expose Rust prioritization and session types through `flutter_rust_bridge` or an equivalent maintained bridge.
The Flutter layer should consume typed session snapshots from Rust while Python continues to orchestrate network-facing behavior.

## What is intentionally deferred
This document does not add generated bindings, build scripts, or platform-specific native glue.
Those steps should start only after the proto contract and prioritization policy settle enough to avoid expensive churn.
