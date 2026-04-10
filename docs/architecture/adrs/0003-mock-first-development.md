# ADR 0003: Build the product flow with mock scenes first

## Status
Accepted

## Why this exists

The current risk is not model quality; it is unclear product flow and weak integration boundaries. Mock scenes let the team validate speaker ranking, session presentation, and operator interactions before introducing live audio, translation latency, or provider-specific failures.

## Boundary owned by this decision

The gateway and client must support a deterministic mock path that can be used for local demos, UI work, and CI-friendly tests. New features should preserve that path unless a replacement testable flow exists.

## Intentionally deferred

This ADR does not define how live event streams, real microphones, or external provider credentials will work. Those integrations should be added only after the mock path stops changing frequently.
