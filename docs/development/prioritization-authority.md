# Prioritization authority

_Last reviewed: 2026-04-29_

## Decision

- Rust `crates/focus_engine/src/lib.rs` is the authoritative source of the
  mode-aware prioritization table.
- `ModeFocusPolicy::for_mode(SessionMode)` defines the shipped `FOCUS`, `CROWD`,
  `LOCKED`, and `UNSPECIFIED` scoring behavior.
- Deterministic ties break by `speaker_id` across runtimes.
- Python `services/gateway/app/services/prioritizer.py` remains in place only as
  a derived gateway mirror until a direct Rust bridge is worth the added build
  and runtime complexity.

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

## Contributor workflow

When prioritization behavior changes:

1. update `ModeFocusPolicy::for_mode(SessionMode)` in `crates/focus_engine/src/lib.rs`
2. update `crates/focus_engine/testdata/prioritization_vectors.tsv`
3. align `services/gateway/app/services/prioritizer.py`
4. run focused validation in both runtimes

Recommended validation:

- `cargo test -p focus_engine`
- `services/gateway/.venv/bin/python -m pytest services/gateway/tests/test_gateway.py -q`

## Why this is the current shape

Task 3 needed one clear owner for prioritization behavior without forcing a full
Rust↔Python bridge in the same pass.
This approach keeps the existing Python gateway architecture intact while making
the Rust policy table the documented authority and making drift visible immediately.