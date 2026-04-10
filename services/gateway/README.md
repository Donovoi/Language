# Gateway service

## What it owns

This service owns the local FastAPI gateway for session state, mock speaker scenes, and mode-aware prioritization at the API boundary.

## How to run and test it

```bash
cd services/gateway
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload
ruff check .
pytest
```

## What it deliberately does not own

The gateway does not yet own live audio ingestion, streaming transport, persistence, authentication, or provider-specific translation and TTS integrations.
