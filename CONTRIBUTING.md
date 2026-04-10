# Contributing

## Workflow

1. Create a branch for each change.
2. Keep commits small and descriptive.
3. Update documentation for architectural changes.
4. Add tests when behavior can silently drift.
5. Prefer explicit code over hidden framework magic in realtime paths.

## Commit style

Use conventional prefixes where practical:

- `feat:` new capability
- `fix:` bug fix
- `docs:` documentation only
- `refactor:` internal change without feature change
- `test:` tests only
- `chore:` maintenance

## Definition of done

A change is ready when:

- local checks pass
- affected docs are updated
- public interfaces are documented
- defaults are safe and deterministic

## Architectural discipline

For non-trivial design changes, add or update an ADR under `docs/architecture/adrs/`.
