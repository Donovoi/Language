from __future__ import annotations

import os

import pytest

from app import cli
from app.config import get_settings


def test_cli_parser_rejects_invalid_port() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--port", "70000"])


def test_cli_applies_overrides_before_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int, log_level: str) -> None:
        captured.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "log_level": log_level,
                "settings": get_settings(),
            }
        )

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.delenv("LANGUAGE_GATEWAY_HOST", raising=False)
    monkeypatch.delenv("LANGUAGE_GATEWAY_PORT", raising=False)
    monkeypatch.delenv("LANGUAGE_GATEWAY_LOG_LEVEL", raising=False)
    get_settings.cache_clear()

    try:
        cli.main(["--host", "0.0.0.0", "--port", "9012", "--log-level", "warning"])
    finally:
        get_settings.cache_clear()
        for name in (
            "LANGUAGE_GATEWAY_HOST",
            "LANGUAGE_GATEWAY_PORT",
            "LANGUAGE_GATEWAY_LOG_LEVEL",
        ):
            os.environ.pop(name, None)

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9012
    assert captured["log_level"] == "warning"
    settings = captured["settings"]
    assert settings.host == "0.0.0.0"
    assert settings.port == 9012
    assert settings.log_level == "warning"
