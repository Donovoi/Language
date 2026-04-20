# Gateway Service

## Ownership

This service owns the local FastAPI API, in-memory session state, and deterministic mock scenes for the Language MVP.
It exposes the client-facing HTTP contract while keeping prioritization logic small and testable.

## Run and validate

```bash
python -m pip install -e '.[dev]'
python -m ruff check .
python -m pytest
uvicorn app.main:app --reload
```

## Runtime configuration

The gateway reads a small set of environment variables for first-release local deployments:

- `LANGUAGE_GATEWAY_ALLOW_ORIGINS`: comma-separated CORS allowlist; defaults to common localhost web origins
- `LANGUAGE_GATEWAY_LOG_LEVEL`: Python log level, default `INFO`
- `LANGUAGE_GATEWAY_TITLE`: optional FastAPI title override
- `LANGUAGE_GATEWAY_VERSION`: optional response/docs version override

## Deliberately out of scope

This service does not own realtime audio capture, diarization, translation provider execution, or TTS.
Those integrations stay deferred until the mock-first API contract is stable.
