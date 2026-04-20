# audio_core

## Ownership

This crate owns typed session, speaker, language, and priority primitives for the Language MVP.
It keeps realtime-facing domain data explicit and easy to validate.

## Public API at a glance

- `SessionId`, `SpeakerId`, and `LanguageCode` validate common identifiers.
- `SpeakerState` and `SessionState` model the snapshots used by higher-level policy crates.
- `PriorityScore` keeps focus-related scoring finite and explicit.

## Example

```rust
use audio_core::{
    LanguageCode, PriorityScore, SessionId, SessionMode, SessionState, SpeakerId, SpeakerState,
};

let session = SessionState::new(
    SessionId::new("session-1")?,
    SessionMode::Focus,
    vec![SpeakerState::new(
        SpeakerId::new("speaker-1")?,
        "Alice",
        LanguageCode::new("en")?,
        PriorityScore::new(0.8)?,
        true,
        false,
        true,
        0.1,
        1_700_000_000_000,
    )?],
);

assert_eq!(session.top_speaker().unwrap().display_name, "Alice");
# Ok::<(), audio_core::ValidationError>(())
```

## Run and validate

```bash
cargo fmt --all --check
cargo test -p audio_core
```

## Deliberately out of scope

This crate does not own prioritization policy, networking, protobuf code generation, or any audio DSP.
Those concerns stay in sibling crates or future integration layers.
