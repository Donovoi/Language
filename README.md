# Language

Language is a cross-platform starter template for building a focus-aware live translation product.
It provides a shared Flutter client shell, a Rust realtime core, a Python gateway, and protobuf contracts so teams can prototype multi-speaker prioritization before wiring in live translation, TTS, or diarization providers.

## Project purpose

This repository exists to make the next implementation steps obvious:
- simulate multi-speaker sessions without real audio
- score and rank speakers consistently across layers
- expose session state through a small gateway API
- render speaker lanes in a shared mobile/desktop client
- keep future translation and TTS integrations provider-agnostic

## Architecture summary

- **Flutter (`apps/field_app_flutter`)** owns the operator-facing client shell for iPhone, Android, macOS, and Windows.
- **Rust (`crates/audio_core`, `crates/focus_engine`)** owns typed session primitives and deterministic prioritization logic.
- **Python (`services/gateway`)** owns the local API, mock scene orchestration, and future model/provider adapters.
- **Protobuf (`proto/session.proto`)** owns shared contracts between the client, services, and future streaming components.

## Repository layout

```text
apps/
  field_app_flutter/     Flutter app shell and session UI
crates/
  audio_core/            Shared domain types and validation
  focus_engine/          Speaker ranking policy crate
services/
  gateway/               FastAPI gateway with mock session state
python/
  research/              Reserved for experiments and evaluation scripts
proto/
  session.proto          Shared session and speaker contracts
docs/
  architecture/          Architecture overview and ADRs
  api/                   API contracts and behavior notes
  development/           Setup and integration planning docs
  product/               Product goals and MVP framing
  testing/               Cross-repo testing strategy
.github/workflows/       Rust, Python, and Flutter CI pipelines
```

## Quickstart

### Prerequisites

Install:
- Rust stable toolchain
- Python 3.11+
- Flutter stable SDK
- Make

### Bootstrap the repository

```bash
make bootstrap
```

### Run quality checks

```bash
make check
```

### Start the local gateway

```bash
make gateway-run
```

### Start the Flutter client

```bash
make flutter-run
```

The Flutter app is intentionally kept light in-repo. `make flutter-run` regenerates local platform runners with `flutter create .` before launching the app so contributors can keep the tracked source tree small while still running the client on supported platforms.

## Current status

This repository currently provides:
- typed Rust models for sessions, speakers, and priority scoring
- a policy crate for ranking active speakers
- a FastAPI gateway with in-memory mock scenes and tests
- a Flutter operator shell that renders prioritized speaker lanes
- CI workflows for Rust, Python, and Flutter validation

Still deferred in this starter template:
- live audio capture and DSP
- streaming translation providers
- production authentication and persistence
- final Rust/Flutter FFI wiring

## Near-term roadmap

1. Replace mock scene updates with a streaming event source.
2. Move shared prioritization weights behind protobuf-backed configuration.
3. Introduce Rust/Flutter FFI for deterministic client-side scoring.
4. Add provider adapters for translation, diarization, and TTS.
5. Add integration tests that cover gateway-to-client flows.

## Contribution expectations

- Keep changes documented and update ADRs for meaningful architectural shifts.
- Prefer deterministic mock-first behavior before adding live integrations.
- Keep service boundaries explicit and provider-agnostic.
- Add or update tests when behavior could silently drift.
- Use the root `Makefile` and CI workflows as the default developer path.

See `CONTRIBUTING.md` for workflow conventions and the current definition of done.
