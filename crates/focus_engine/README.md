# focus_engine

## Ownership

This crate owns speaker ranking policy and active-speaker selection for the Language MVP.
It converts typed speaker state into deterministic ordering decisions.

## Public API at a glance

- `FocusPolicy` defines the scoring weights used for focus selection.
- `rank_speakers` returns a stable ranking across all speakers.
- `top_n_active_speakers` filters that ranking down to active speakers only.

## Example

```rust
use audio_core::{LanguageCode, PriorityScore, SpeakerId, SpeakerState};
use focus_engine::{rank_speakers, FocusPolicy};

let ranked = rank_speakers(
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
    &FocusPolicy::default(),
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
It remains a small policy layer on top of `audio_core`.
