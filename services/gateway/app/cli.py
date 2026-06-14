from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn

from app.config import get_settings


def _positive_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if port <= 0 or port > 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Language gateway service")
    parser.add_argument(
        "--host",
        help="bind host; defaults to LANGUAGE_GATEWAY_HOST or 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=_positive_port,
        help="bind port; defaults to LANGUAGE_GATEWAY_PORT or 8000",
    )
    parser.add_argument(
        "--log-level",
        help="Uvicorn log level; defaults to LANGUAGE_GATEWAY_LOG_LEVEL or info",
    )
    return parser


def _apply_override(name: str, value: str | int | None) -> None:
    if value is not None:
        os.environ[name] = str(value)


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    _apply_override("LANGUAGE_GATEWAY_HOST", args.host)
    _apply_override("LANGUAGE_GATEWAY_PORT", args.port)
    _apply_override("LANGUAGE_GATEWAY_LOG_LEVEL", args.log_level)
    get_settings.cache_clear()
    settings = get_settings()
    from app import main as gateway_main

    uvicorn.run(
        gateway_main.app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
