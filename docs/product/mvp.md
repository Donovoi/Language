# MVP

## Goal

Build a realtime multi-speaker speech translation system that can:

- listen to speech from multiple people at different volume levels, including overlapping speech
- detect each speaker's source language
- translate the speech to English in realtime
- synthesize the English translation in the same speaker voice
- play the translated voice back at the same perceived volume as the original speaker
- suppress or cancel the original source voice so the translated English mix is what the user hears
- present translated captions and per-speaker diagnostics while the audio path is being built

## Non-goals

The MVP does **not** promise:

- perfect universal room translation
- perfect distance estimation
- legally authoritative interpretation
- indistinguishable source-voice cloning
- perfect cancellation of every original speaker in every room

## Initial operating modes

### Focus mode
Translate and emphasize the most relevant speaker while keeping their English voice volume-matched.

### Crowd mode
Track many speakers, including overlapping speakers, but only elevate the top subset into the translated audio mix.

### Locked mode
Temporarily bias toward a user-selected speaker.

## First milestones

1. Local scene simulation
2. Speaker timeline UI
3. Backend event stream
4. Priority scoring
5. Basic end-to-end transport

## Current status

As of 2026-05-31, the initial milestones above are complete in the current mock/demo stack:

- local scene simulation exists via deterministic mock scenes and `/v1/mock/live-ingest`
- the shared session contract carries detected language confidence, input/output dBFS levels,
  overlapping speaker ids, voice clone status, translated-audio stream ids, source suppression diagnostics,
  and playback latency
- the Flutter field console renders speaker lanes, translated-caption fields, audio/voice/suppression
  state, and operator lock controls
- the gateway exposes persistent SSE for session snapshots and speaker updates
- Rust owns the authoritative prioritization policy, with parity checks against the gateway mirror
- the local end-to-end transport path is runnable via `make gateway-run`, `make flutter-run`, and `make smoke-local-demo`

## Next MVP milestones

1. live microphone capture and overlapping-speaker diarization path selection
2. provider-backed English voice clone/TTS stream behind the existing translated-audio metadata contract
3. source-voice suppression/noise-cancellation prototype
4. end-to-end demo smoke coverage that exercises the product-shaped audio metadata path
5. internal beta release artifacts and release checklist pass
