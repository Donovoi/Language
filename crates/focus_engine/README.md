# focus_engine

## Ownership

This crate owns the authoritative speaker ranking policy table and active-speaker
selection for the Language MVP.
`ModeFocusPolicy::for_mode(SessionMode)` is the documented source of truth for
Focus/Crowd/Locked/Unspecified behavior.
Python still mirrors those weights in `services/gateway/app/services/prioritizer.py`
until a direct bridge is worth the extra plumbing.

## Public API at a glance

- `ModeFocusPolicy::for_mode(SessionMode)` defines the authoritative scoring weights
    and persistence multiplier for each session mode.
- `rank_speakers_for_mode` returns the stable ranking used by the gateway.
- `top_n_active_speakers_for_mode` filters that ranking down to active speakers only.
- `FocusPolicy` and `rank_speakers` remain available for callers that need to inject
    a custom one-off policy.
- `testdata/prioritization_vectors.tsv` is the shared parity fixture loaded by Rust
    and gateway tests.

## Example

```rust
use audio_core::{LanguageCode, PriorityScore, SessionMode, SpeakerId, SpeakerState};
use focus_engine::rank_speakers_for_mode;

let ranked = rank_speakers_for_mode(
    &[
        SpeakerState::new(
            SpeakerId::new("speaker-a")?,
            "Alice",
            LanguageCode::new("en")?,
            PriorityScore::new(0.6)?,
            true,
            false,
            false,
            0.0,
            0,
        )?,
        SpeakerState::new(
            SpeakerId::new("speaker-b")?,
            "Bao",
            LanguageCode::new("en")?,
            PriorityScore::new(0.4)?,
            true,
            true,
            false,
            0.0,
            0,
        )?,
    ],
    SessionMode::Locked,
);

assert_eq!(ranked[0].speaker_id.as_str(), "speaker-b");
# Ok::<(), audio_core::ValidationError>(())
```

## Run and validate

```bash
cargo fmt --all --check
cargo test -p focus_engine
```

## Deliberately out of scope

This crate does not own speaker identity models, transport, UI concerns, or actual audio mixing.
It remains a small policy layer on top of `audio_core`, with the current Python
gateway acting as a derived runtime mirror until FFI or generated bindings are justified.
