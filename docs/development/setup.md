# Development Setup

## Toolchain

Install:
- Flutter stable
- Rust stable toolchain
- Python 3.11+
- Make

## Suggested local workflow

```bash
make bootstrap
make check
```

## Repository areas

- `apps/field_app_flutter` shared client shell
- `crates/audio_core` shared realtime primitives
- `crates/focus_engine` speaker priority logic
- `services/gateway` Python API gateway

## Notes

The repository keeps a mock-first developer path. The Flutter app source is tracked in-repo, while local platform runners are regenerated with `flutter create .` during bootstrap and run commands.
For release prep, use `release-builds.md`, `release-checklist.md`, `versioning.md`, and the root `CHANGELOG.md`.
