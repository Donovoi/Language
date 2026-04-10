# focus_engine

## What it owns

This crate owns deterministic speaker ranking policy logic built on top of `audio_core` domain types.

## How to run and test it

```bash
cargo test -p focus_engine
cargo clippy -p focus_engine --all-targets --all-features -- -D warnings
```

## What it deliberately does not own

This crate does not own audio processing, transport, or session persistence. It scores and selects speakers only.
