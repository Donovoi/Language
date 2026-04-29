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


_SUPPORTED_TRANSLATION_PROVIDERS = {"disabled", "libretranslate"}


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    host: str
    port: int
    log_level: str


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    provider: str
    base_url: str | None
    api_key: str | None
    timeout_ms: int
    default_target_language_code: str

    @property
    def enabled(self) -> bool:
        return self.provider == "libretranslate" and self.base_url is not None


def _read_optional_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _normalize_language_tag(language_tag: str) -> str:
    return language_tag.strip().replace("_", "-").lower()


def get_translation_settings() -> TranslationSettings:
    provider = _read_str("LANGUAGE_GATEWAY_TRANSLATION_PROVIDER", "disabled").lower()
    if provider not in _SUPPORTED_TRANSLATION_PROVIDERS:
        supported = ", ".join(sorted(_SUPPORTED_TRANSLATION_PROVIDERS))
        raise ValueError(
            f"LANGUAGE_GATEWAY_TRANSLATION_PROVIDER must be one of {supported}, got {provider!r}"
        )

    timeout_ms = _read_int("LANGUAGE_GATEWAY_TRANSLATION_TIMEOUT_MS", 4000)
    if timeout_ms <= 0:
        raise ValueError(
            "LANGUAGE_GATEWAY_TRANSLATION_TIMEOUT_MS must be greater than zero, "
            f"got {timeout_ms!r}"
        )

    base_url = _read_optional_str("LANGUAGE_GATEWAY_TRANSLATION_BASE_URL")
    if base_url is not None:
        base_url = base_url.rstrip("/")

    return TranslationSettings(
        provider=provider,
        base_url=base_url,
        api_key=_read_optional_str("LANGUAGE_GATEWAY_TRANSLATION_API_KEY"),
        timeout_ms=timeout_ms,
        default_target_language_code=_normalize_language_tag(
            _read_str("LANGUAGE_GATEWAY_TRANSLATION_TARGET_LANGUAGE", "en")
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> GatewaySettings:
    return GatewaySettings(
        host=_read_str("LANGUAGE_GATEWAY_HOST", "127.0.0.1"),
        port=_read_int("LANGUAGE_GATEWAY_PORT", 8000),
        log_level=_read_str("LANGUAGE_GATEWAY_LOG_LEVEL", "info"),
    )