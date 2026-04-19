# ADR 0001: Keep a single monorepo for the MVP

## Status
Accepted

## Why this exists
The MVP spans a shared client, a reusable realtime core, and a service gateway that must evolve together.
A monorepo keeps the contract, docs, and validation steps visible in one place.

## Boundary it owns
This decision defines the repository shape and keeps Flutter, Rust, Python, and protobuf code in a single source tree.
It also justifies shared CI and root-level developer commands.

## What is intentionally deferred
This ADR does not decide deployment topology or future service extraction.
If the product later needs independent release trains, that can be revisited with stronger operational data.
