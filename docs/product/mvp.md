# MVP

## Goal

Build a multi-speaker, focus-aware live translation system that can:

- track multiple speakers in a scene
- prioritize them dynamically
- present translated captions per speaker lane
- return metadata needed for translated-audio mixing

## Non-goals

The MVP does **not** promise:

- perfect universal room translation
- perfect distance estimation
- legally authoritative interpretation
- perfect source-voice cloning

## Initial operating modes

### Focus mode
Translate and emphasize the most relevant speaker.

### Crowd mode
Track many speakers but only elevate the top subset into the translated audio mix.

### Locked mode
Temporarily bias toward a user-selected speaker.

## First milestones

1. Local scene simulation
2. Speaker timeline UI
3. Backend event stream
4. Priority scoring
5. Basic end-to-end transport

## Current status

As of 2026-04-29, the initial milestones above are complete in the current mock/demo stack:

- local scene simulation exists via deterministic mock scenes and `/v1/mock/live-ingest`
- the Flutter field console renders speaker lanes, translated-caption fields, and operator lock controls
- the gateway exposes persistent SSE for session snapshots and speaker updates
- Rust owns the authoritative prioritization policy, with parity checks against the gateway mirror
- the local end-to-end transport path is runnable via `make gateway-run`, `make flutter-run`, and `make smoke-local-demo`

## Next MVP milestones

1. provider-backed text translation in the gateway
2. end-to-end demo smoke coverage and operator runbook
3. internal beta release artifacts and release checklist pass
4. audio capture and diarization path selection
5. translated-audio / TTS metadata path
