# Prioritization authority

_Last reviewed: 2026-05-01_

## Decision

- Rust `crates/focus_engine/src/lib.rs` is the authoritative source of the
  mode-aware prioritization table.
- `ModeFocusPolicy::for_mode(SessionMode)` defines the shipped `FOCUS`, `CROWD`,
  `LOCKED`, and `UNSPECIFIED` scoring behavior.
- Deterministic ties break by `speaker_id` across runtimes.
- The gateway runtime now prefers a direct Rust bridge via the `session_ranker`
  binary in `crates/session_proto/src/bin/session_ranker.rs`.
- Python `services/gateway/app/services/prioritizer.py` remains in place as the
  derived mirror and fallback path for environments where the native bridge is
  intentionally disabled or temporarily unavailable.

## Drift guard

The repository now uses one shared parity fixture:

- `crates/focus_engine/testdata/prioritization_vectors.tsv`

That fixture is loaded by:

- `crates/focus_engine/tests/prioritization_parity.rs`
- `services/gateway/tests/test_gateway.py`

This means policy drift fails loudly in both runtimes:

- change the Rust mode table without updating the fixture and Rust tests fail
- change the fixture without updating the Python mirror and gateway tests fail
- change the Python mirror without updating the Rust authority and gateway tests fail
- change the Rust runtime bridge contract and the gateway runtime tests fail

## Contributor workflow

When prioritization behavior changes:

1. update `ModeFocusPolicy::for_mode(SessionMode)` in `crates/focus_engine/src/lib.rs`
2. update `crates/focus_engine/testdata/prioritization_vectors.tsv`
3. keep `services/gateway/app/services/prioritizer.py` aligned as the documented fallback mirror
4. run focused validation in both runtimes
5. if the runtime bridge payload changes, update `crates/session_proto/src/bin/session_ranker.rs`

Recommended validation:

- `cargo test -p focus_engine`
- `services/gateway/.venv/bin/python -m pytest services/gateway/tests/test_gateway.py -q`

## Why this is the current shape

Task 3 first established one clear owner for prioritization behavior without forcing a full
Rust↔Python bridge in the same pass.
The follow-up runtime bridge now lets the gateway use the Rust authority directly while keeping
the Python path available as a small, parity-tested fallback instead of the primary implementation.