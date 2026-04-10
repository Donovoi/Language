# audio_core

## What it owns

This crate owns typed session, speaker, identifier, and priority primitives for the Language starter template.

## How to run and test it

```bash
cargo test -p audio_core
cargo clippy -p audio_core --all-targets --all-features -- -D warnings
```

## What it deliberately does not own

This crate does not own DSP, async runtime concerns, or policy-specific ranking logic.
