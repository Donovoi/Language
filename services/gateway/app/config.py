from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env_candidates() -> list[Path]:
    config_path = Path(__file__).resolve()
    parents = config_path.parents
    candidates: list[Path] = []

    if len(parents) > 1:
        candidates.append(parents[1] / ".env")
    if len(parents) > 3:
        candidates.append(parents[3] / ".env")

    candidates.append(Path.cwd() / ".env")

    deduped: list[Path] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, raw_value = line.partition("=")
        key = key.strip()
        value = raw_value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def _load_default_env() -> None:
    for candidate in _env_candidates():
        if candidate.is_file():
            _load_env_file(candidate)
            return


def _read_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default

    stripped = value.strip()
    if not stripped:
        return default
    return stripped


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    stripped = value.strip()
    if not stripped:
        return default

    try:
        return int(stripped)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


_load_default_env()


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    host: str
    port: int
    log_level: str


@lru_cache(maxsize=1)
def get_settings() -> GatewaySettings:
    return GatewaySettings(
        host=_read_str("LANGUAGE_GATEWAY_HOST", "127.0.0.1"),
        port=_read_int("LANGUAGE_GATEWAY_PORT", 8000),
        log_level=_read_str("LANGUAGE_GATEWAY_LOG_LEVEL", "info"),
    )