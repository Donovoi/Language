#!/usr/bin/env python3
"""Smoke-test write-token auth against a running gateway process."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
GATEWAY_DIR = ROOT / "services" / "gateway"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def resolve_source_python(candidate: str) -> str:
    candidates = []
    if candidate:
        candidates.append(Path(candidate))
    if os.environ.get("GATEWAY_PYTHON"):
        candidates.append(Path(os.environ["GATEWAY_PYTHON"]))
    candidates.extend(
        [
            GATEWAY_DIR / ".venv" / "Scripts" / "python.exe",
            GATEWAY_DIR / ".venv" / "bin" / "python",
        ]
    )
    for path in candidates:
        if path.exists():
            return str(path.resolve())
    raise SystemExit("Gateway Python not found. Pass --gateway-python or create services/gateway/.venv.")


def request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: object | None = None,
    timeout: float,
) -> tuple[int, dict[str, str], object]:
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    data = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=request_headers,
        data=data,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw_headers = {key.lower(): value for key, value in response.headers.items()}
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw_headers = {key.lower(): value for key, value in exc.headers.items()}
        text = exc.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise RuntimeError(f"{method} {path} failed: {exc}") from exc

    try:
        payload: object = json.loads(text) if text else None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {path} returned non-JSON body: {text!r}") from exc
    return status, raw_headers, payload


def gateway_is_healthy(base_url: str, timeout: float) -> bool:
    try:
        status, _headers, payload = request_json(base_url, "GET", "/health", timeout=timeout)
    except Exception:
        return False
    return status == 200 and payload == {"status": "ok"}


def start_gateway(args: argparse.Namespace, temp_dir: Path) -> subprocess.Popen[bytes]:
    base_url = f"http://{args.host}:{args.port}"
    if gateway_is_healthy(base_url, args.request_timeout_seconds):
        raise SystemExit(f"Gateway already running at {base_url}; choose another auth smoke port.")

    env = os.environ.copy()
    env["LANGUAGE_GATEWAY_AUTH_TOKEN"] = args.token
    env["LANGUAGE_GATEWAY_SESSION_DB_PATH"] = str(temp_dir / "session-store.sqlite3")

    if args.gateway_command:
        working_dir = Path(args.gateway_working_directory or temp_dir).resolve()
        command = [
            str(Path(args.gateway_command).resolve()),
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--log-level",
            "warning",
        ]
    else:
        working_dir = GATEWAY_DIR
        command = [
            resolve_source_python(args.gateway_python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--log-level",
            "warning",
        ]

    stdout = (temp_dir / "gateway-auth.stdout.log").open("wb")
    stderr = (temp_dir / "gateway-auth.stderr.log").open("wb")
    try:
        return subprocess.Popen(
            command,
            cwd=working_dir,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        stdout.close()
        stderr.close()


def wait_for_gateway(process: subprocess.Popen[bytes], base_url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Gateway exited before becoming healthy with code {process.returncode}.")
        if gateway_is_healthy(base_url, 1.0):
            return
        time.sleep(0.25)
    raise RuntimeError(f"Gateway did not become healthy within {timeout:.1f}s.")


def verify_auth(base_url: str, token: str, timeout: float) -> None:
    status, _headers, payload = request_json(base_url, "GET", "/v1/session", timeout=timeout)
    require(status == 200, f"GET /v1/session without token returned {status}")
    require(isinstance(payload, dict) and payload.get("session_id"), "GET /v1/session missing payload")

    status, headers, payload = request_json(base_url, "PUT", "/v1/session/mode?mode=LOCKED", timeout=timeout)
    require(status == 401, f"write without token returned {status}")
    require(headers.get("www-authenticate") == "Bearer", "missing Bearer challenge for missing token")
    require(isinstance(payload, dict) and payload.get("detail") == "Missing bearer token.", "unexpected missing-token payload")

    status, headers, payload = request_json(
        base_url,
        "PUT",
        "/v1/session/mode?mode=LOCKED",
        headers=bearer("wrong-token"),
        timeout=timeout,
    )
    require(status == 401, f"write with wrong token returned {status}")
    require(headers.get("www-authenticate") == "Bearer", "missing Bearer challenge for wrong token")
    require(isinstance(payload, dict) and payload.get("detail") == "Invalid bearer token.", "unexpected wrong-token payload")

    status, _headers, payload = request_json(
        base_url,
        "PUT",
        "/v1/session/mode?mode=LOCKED",
        headers=bearer(token),
        timeout=timeout,
    )
    require(status == 200, f"write with matching token returned {status}")
    require(isinstance(payload, dict) and payload.get("mode") == "LOCKED", "matching token did not update mode")

    status, _headers, payload = request_json(
        base_url,
        "POST",
        "/v1/session/reset?mode=FOCUS",
        headers=bearer(token),
        timeout=timeout,
    )
    require(status == 200, f"reset with matching token returned {status}")
    require(isinstance(payload, dict) and payload.get("reset") is True, "matching token did not reset session")


def print_gateway_logs(temp_dir: Path) -> None:
    for name in ("gateway-auth.stderr.log", "gateway-auth.stdout.log"):
        path = temp_dir / name
        if path.exists() and path.stat().st_size:
            print(f"\n{name}:", file=sys.stderr)
            print(path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)


def run(args: argparse.Namespace) -> int:
    if args.self_test:
        require(bearer("x") == {"Authorization": "Bearer x"}, "bearer helper failed")
        print("gateway auth smoke self-test PASS")
        return 0

    if not args.token:
        args.token = secrets.token_urlsafe(24)

    base_url = f"http://{args.host}:{args.port}"
    if args.keep_temp:
        temp_dir_raw = tempfile.mkdtemp(prefix="language-gateway-auth-smoke-")
        temp_context = None
    else:
        temp_context = tempfile.TemporaryDirectory(
            prefix="language-gateway-auth-smoke-",
            ignore_cleanup_errors=True,
        )
        temp_dir_raw = temp_context.name

    temp_dir = Path(temp_dir_raw)
    process: subprocess.Popen[bytes] | None = None
    try:
        process = start_gateway(args, temp_dir)
        wait_for_gateway(process, base_url, args.start_timeout_seconds)
        verify_auth(base_url, args.token, args.request_timeout_seconds)
        print("Gateway auth smoke check passed")
        return 0
    except Exception:
        print_gateway_logs(temp_dir)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if temp_context is not None:
            temp_context.cleanup()
        elif args.keep_temp:
            print(f"Keeping gateway auth smoke temp directory: {temp_dir}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("GATEWAY_AUTH_SMOKE_PORT", "8012")))
    parser.add_argument("--gateway-python", default=os.environ.get("GATEWAY_PYTHON", ""))
    parser.add_argument("--gateway-command", default="")
    parser.add_argument("--gateway-working-directory", default="")
    parser.add_argument("--token", default=os.environ.get("LANGUAGE_GATEWAY_AUTH_SMOKE_TOKEN", ""))
    parser.add_argument("--request-timeout-seconds", type=float, default=3.0)
    parser.add_argument("--start-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
