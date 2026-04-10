# Testing Strategy

## Why this exists

The repository spans Rust, Python, Flutter, and protobuf contracts. A clear testing strategy keeps the starter template predictable as those layers evolve together.

## Boundary owned by this strategy

- Rust crates must cover constructor invariants and prioritization behavior with unit tests.
- The Python gateway must cover endpoint behavior and service-level sorting with pytest.
- The Flutter app must cover core rendering and mode-driven UI changes with widget tests.
- CI must fail fast on formatting, lint, and test regressions in each stack.

## Intentionally deferred

This strategy does not yet include end-to-end device tests, contract generation checks, load tests, or audio pipeline benchmarks. Those should be added after the mock-first foundation is stable.
