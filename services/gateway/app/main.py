from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from app.config import Settings, get_settings
from app.routes import health_router, mock_router, sessions_router, speakers_router
from app.services.session_store import SessionStore

logger = logging.getLogger("language.gateway")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    _configure_logging(resolved_settings.log_level)

    app = FastAPI(title=resolved_settings.title, version=resolved_settings.version)
    app.state.settings = resolved_settings
    app.state.session_store = SessionStore()
    if resolved_settings.allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.allow_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def log_requests(request: Request, call_next: RequestResponseEndpoint) -> Response:
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "request_complete method=%s path=%s status_code=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("request_failed method=%s path=%s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(speakers_router)
    app.include_router(mock_router)
    return app


def _configure_logging(log_level: str) -> None:
    logging_level = logging.getLevelNamesMapping()[log_level]
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging_level)
    logger.setLevel(logging_level)


app = create_app()
