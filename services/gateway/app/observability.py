from __future__ import annotations

import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_LOGGER_NAME = "language_gateway.request"


def configure_request_logger(log_level: str) -> logging.Logger:
    logger = logging.getLogger(_REQUEST_LOGGER_NAME)
    resolved_level = getattr(logging, log_level.upper(), logging.INFO)
    if not isinstance(resolved_level, int):
        resolved_level = logging.INFO

    logger.setLevel(resolved_level)
    return logger


def register_request_logging_middleware(app: FastAPI, *, logger: logging.Logger) -> None:
    @app.middleware("http")
    async def request_logging_middleware(
        request: Request,
        call_next,
    ) -> Response:
        request_id = _resolve_request_id(request)
        request.state.request_id = request_id
        start = perf_counter()
        response: Response | None = None

        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((perf_counter() - start) * 1000, 3)
            status_code = response.status_code if response is not None else 500

            if response is not None:
                response.headers.setdefault(REQUEST_ID_HEADER, request_id)

            logger.info(
                json.dumps(
                    {
                        "event": "http.request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "client_ip": request.client.host if request.client is not None else None,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )


def _resolve_request_id(request: Request) -> str:
    inbound_request_id = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if inbound_request_id:
        return inbound_request_id[:200]
    return uuid4().hex
