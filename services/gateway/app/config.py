from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

_DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
)
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True)
class Settings:
    title: str
    version: str
    log_level: str
    allow_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.getenv("LANGUAGE_GATEWAY_ALLOW_ORIGINS", "")
        return cls(
            title=os.getenv("LANGUAGE_GATEWAY_TITLE", "Language Gateway"),
            version=os.getenv("LANGUAGE_GATEWAY_VERSION", "0.1.0"),
            log_level=_parse_log_level(os.getenv("LANGUAGE_GATEWAY_LOG_LEVEL", "INFO")),
            allow_origins=_parse_origins(origins),
        )


def _parse_origins(raw_origins: str) -> tuple[str, ...]:
    if not raw_origins.strip():
        return _DEFAULT_ALLOWED_ORIGINS
    return tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())


def _parse_log_level(raw_log_level: str) -> str:
    candidate = raw_log_level.strip().upper()
    return candidate if candidate in _VALID_LOG_LEVELS else "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
