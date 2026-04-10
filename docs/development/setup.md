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

This repository starts with mock data flows so the UI and shared core can be developed before wiring in live audio and provider integrations.
