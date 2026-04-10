# ADR 0001: Keep a single product monorepo

## Status
Accepted

## Why this exists

The MVP spans a shared client, a realtime core, a gateway, and protobuf contracts that need to evolve together. A single monorepo keeps those boundaries visible, makes cross-layer refactors easier, and gives CI one place to validate the starter template.

## Boundary owned by this decision

This repository owns the top-level layout for apps, crates, services, docs, and shared contracts. It also owns the expectation that foundational changes land with matching docs, tests, and workflow updates in the same pull request.

## Intentionally deferred

This ADR does not define release tooling, package publishing, or a future split into separately versioned repositories. If the product later needs independent release cadences, that can be revisited with usage data.
