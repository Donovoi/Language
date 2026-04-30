# session_proto

## Ownership

This crate owns the Rust transport-facing protobuf bindings generated from `proto/session.proto`.
It bridges those generated types into the validated domain primitives in `audio_core` without pushing
protobuf concerns down into the domain crate.

## Public API at a glance

- generated `language::session::v1` protobuf messages and enums via `prost`
- conversion helpers between generated transport types and `audio_core`
- explicit conversion failures for invalid enum values or invalid domain data

## Example

```rust
use audio_core::{LanguageCode, PriorityScore, SessionId, SessionMode, SessionState, SpeakerId, SpeakerState};
use session_proto::language::session::v1;

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

let transport: v1::SessionState = (&session).into();
assert_eq!(transport.session_id, "session-1");
# Ok::<(), Box<dyn std::error::Error>>(())
```

## Run and validate

```bash
cargo fmt --all --check
cargo test -p session_proto
```

## Deliberately out of scope

This crate does not own prioritization policy, Python/Flutter bridges, or runtime networking.
It is the Rust transport layer for the shared protobuf contract, with higher-level integration still
owned by sibling crates or future bridge work.
