# focus_engine

## Ownership

This crate owns speaker ranking policy and active-speaker selection for the Language MVP.
It converts typed speaker state into deterministic ordering decisions.

## Run and validate

```bash
cargo fmt --all --check
cargo test -p focus_engine
```

## Deliberately out of scope

This crate does not own speaker identity models, transport, UI concerns, or actual audio mixing.
It remains a small policy layer on top of `audio_core`.
