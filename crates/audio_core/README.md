# audio_core

## Ownership

This crate owns typed session, speaker, language, and priority primitives for the Language MVP.
It keeps realtime-facing domain data explicit and easy to validate.

## Run and validate

```bash
cargo fmt --all --check
cargo test -p audio_core
```

## Deliberately out of scope

This crate does not own prioritization policy, networking, protobuf code generation, or any audio DSP.
Those concerns stay in sibling crates or future integration layers.
