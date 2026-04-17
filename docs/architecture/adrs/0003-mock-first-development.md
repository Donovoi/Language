# ADR 0003: Build the MVP around mock-first flows

## Status
Accepted

## Why this exists
The earliest product risk is whether the UI, contracts, and prioritization story make sense together.
Mock scenes let the team prove the product loop before depending on live audio, provider APIs, or latency-sensitive transport.

## Boundary it owns
This decision allows the gateway and Flutter client to ship with deterministic demo data and visible mode changes.
It keeps current tests focused on data shape, ordering, and session behavior.

## What is intentionally deferred
This ADR does not define live event transport, ingestion reliability, or provider quality metrics.
Those should be addressed after the mock-first developer flow is stable.
