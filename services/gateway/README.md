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

## Deliberately out of scope

This service does not own realtime audio capture, diarization, translation provider execution, or TTS.
Those integrations stay deferred until the mock-first API contract is stable.
