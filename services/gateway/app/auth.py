from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request, status

AUTH_TOKEN_ENV_VAR = "LANGUAGE_GATEWAY_AUTH_TOKEN"
_AUTH_SCHEME = "Bearer"


def get_configured_auth_token() -> str | None:
    raw_token = os.getenv(AUTH_TOKEN_ENV_VAR)
    if raw_token is None:
        return None

    token = raw_token.strip()
    if not token:
        return None
    return token


def auth_is_enabled() -> bool:
    return get_configured_auth_token() is not None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": _AUTH_SCHEME},
    )


def require_write_token(request: Request) -> None:
    expected_token = get_configured_auth_token()
    if expected_token is None:
        return

    authorization = request.headers.get("Authorization")
    if authorization is None:
        raise _unauthorized("Missing bearer token.")

    scheme, _, provided_token = authorization.partition(" ")
    candidate_token = provided_token.strip()
    if scheme.lower() != _AUTH_SCHEME.lower() or not candidate_token:
        raise _unauthorized("Invalid bearer token.")

    if not secrets.compare_digest(candidate_token, expected_token):
        raise _unauthorized("Invalid bearer token.")
