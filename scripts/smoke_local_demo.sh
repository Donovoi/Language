#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_DIR="$ROOT_DIR/services/gateway"
DEFAULT_GATEWAY_PYTHON="$GATEWAY_DIR/.venv/bin/python"

GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-8000}"
GATEWAY_BASE_URL="http://${GATEWAY_HOST}:${GATEWAY_PORT}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-3}"
SMOKE_START_TIMEOUT_SECONDS="${SMOKE_START_TIMEOUT_SECONDS:-20}"
REQUEST_PYTHON_CANDIDATE="${REQUEST_PYTHON:-python3}"
GATEWAY_PYTHON_CANDIDATE="${GATEWAY_PYTHON:-$DEFAULT_GATEWAY_PYTHON}"

STARTED_GATEWAY=0
GATEWAY_PID=""
TMP_DIR="$(mktemp -d)"
GATEWAY_LOG_FILE="$TMP_DIR/gateway.log"

log() {
  printf '\n==> %s\n' "$1"
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

resolve_executable() {
  local candidate="$1"

  if [[ "$candidate" == */* ]]; then
    if [[ "$candidate" != /* ]]; then
      candidate="$PWD/$candidate"
    fi
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    return 1
  fi

  command -v "$candidate" 2>/dev/null
}

cleanup() {
  local exit_code=$?

  trap - EXIT INT TERM

  if [[ $STARTED_GATEWAY -eq 1 && -n "$GATEWAY_PID" ]]; then
    if kill -0 "$GATEWAY_PID" 2>/dev/null; then
      kill "$GATEWAY_PID" 2>/dev/null || true
    fi
    wait "$GATEWAY_PID" 2>/dev/null || true
  fi

  if [[ $exit_code -ne 0 && -s "$GATEWAY_LOG_FILE" ]]; then
    printf '\nGateway log (%s):\n' "$GATEWAY_LOG_FILE" >&2
    cat "$GATEWAY_LOG_FILE" >&2 || true
  fi

  rm -rf "$TMP_DIR"
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

REQUEST_PYTHON_BIN="$(resolve_executable "$REQUEST_PYTHON_CANDIDATE" || true)"
GATEWAY_PYTHON_BIN="$(resolve_executable "$GATEWAY_PYTHON_CANDIDATE" || true)"

if [[ -z "$REQUEST_PYTHON_BIN" ]]; then
  fail "Unable to find a Python interpreter for HTTP validation. Set REQUEST_PYTHON or install python3."
fi

healthcheck_gateway() {
  GATEWAY_BASE_URL="$GATEWAY_BASE_URL" REQUEST_TIMEOUT_SECONDS="$REQUEST_TIMEOUT_SECONDS" "$REQUEST_PYTHON_BIN" - <<'PY'
import json
import os
import urllib.error
import urllib.request

base_url = os.environ["GATEWAY_BASE_URL"].rstrip("/")
timeout = float(os.environ["REQUEST_TIMEOUT_SECONDS"])

request = urllib.request.Request(
    f"{base_url}/health",
    headers={"Accept": "application/json"},
)

try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        status = response.status
except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
    raise SystemExit(1)

if status != 200:
    raise SystemExit(1)

try:
    payload = json.loads(body)
except json.JSONDecodeError:
    raise SystemExit(1)

if payload != {"status": "ok"}:
    raise SystemExit(1)
PY
}

start_gateway() {
  if [[ -z "$GATEWAY_PYTHON_BIN" ]]; then
    fail "Gateway Python was not found at $GATEWAY_PYTHON_CANDIDATE. Run make bootstrap or make gateway-venv first."
  fi

  log "Starting a temporary gateway at $GATEWAY_BASE_URL"
  (
    cd "$GATEWAY_DIR"
    exec "$GATEWAY_PYTHON_BIN" -m uvicorn app.main:app --host "$GATEWAY_HOST" --port "$GATEWAY_PORT" --log-level warning
  ) >"$GATEWAY_LOG_FILE" 2>&1 &

  GATEWAY_PID=$!
  STARTED_GATEWAY=1
}

wait_for_gateway() {
  local deadline=$((SECONDS + SMOKE_START_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    if [[ -n "$GATEWAY_PID" ]] && ! kill -0 "$GATEWAY_PID" 2>/dev/null; then
      fail "Temporary gateway exited before becoming healthy."
    fi

    if healthcheck_gateway; then
      return 0
    fi

    sleep 1
  done

  fail "Gateway did not become healthy within ${SMOKE_START_TIMEOUT_SECONDS}s."
}

verify_local_demo() {
  GATEWAY_BASE_URL="$GATEWAY_BASE_URL" REQUEST_TIMEOUT_SECONDS="$REQUEST_TIMEOUT_SECONDS" "$REQUEST_PYTHON_BIN" - <<'PY'
import json
import os
import urllib.request

base_url = os.environ["GATEWAY_BASE_URL"].rstrip("/")
timeout = float(os.environ["REQUEST_TIMEOUT_SECONDS"])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def fetch(path: str, accept: str) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Accept": accept},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.status, headers, body


def fetch_json(path: str) -> dict[str, object]:
    status, _headers, body = fetch(path, "application/json")
    require(status == 200, f"Expected 200 for {path}, got {status}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Expected JSON from {path}: {exc}") from exc


def parse_sse(payload: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in payload.split("\n\n"):
        lines = [line.rstrip("\r") for line in block.splitlines() if line.strip()]
        if not lines or all(line.startswith(":") for line in lines):
            continue

        event_name = None
        data_lines: list[str] = []
        for line in lines:
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))

        require(event_name is not None, f"SSE payload missing event name: {payload!r}")
        require(data_lines, f"SSE payload missing data lines: {payload!r}")
        events.append({"event": event_name, "data": json.loads("\n".join(data_lines))})

    return events


health = fetch_json("/health")
require(health == {"status": "ok"}, f"Unexpected /health payload: {health!r}")

session_payload = fetch_json("/v1/session")
require(isinstance(session_payload.get("session_id"), str) and bool(session_payload["session_id"]), "/v1/session missing session_id")
require(isinstance(session_payload.get("mode"), str) and bool(session_payload["mode"]), "/v1/session missing mode")
require(isinstance(session_payload.get("speakers"), list), "/v1/session missing speakers list")
require("top_speaker_id" in session_payload, "/v1/session missing top_speaker_id")

preview_payload = fetch_json("/v1/session?mode=FOCUS")
require(preview_payload.get("mode") == "FOCUS", f"Expected FOCUS preview, got {preview_payload.get('mode')!r}")
require(isinstance(preview_payload.get("speakers"), list) and bool(preview_payload["speakers"]), "FOCUS preview returned no speakers")
require(isinstance(preview_payload.get("top_speaker_id"), str) and bool(preview_payload["top_speaker_id"]), "FOCUS preview missing top_speaker_id")

first_speaker = preview_payload["speakers"][0]
require(isinstance(first_speaker.get("speaker_id"), str) and bool(first_speaker["speaker_id"]), "Preview speaker missing speaker_id")
require(isinstance(first_speaker.get("display_name"), str) and bool(first_speaker["display_name"]), "Preview speaker missing display_name")

stream_status, stream_headers, stream_body = fetch(
    "/v1/events/stream?mode=FOCUS&max_events=1",
    "text/event-stream",
)
require(stream_status == 200, f"Expected 200 for /v1/events/stream, got {stream_status}")
require(
    stream_headers.get("content-type", "").startswith("text/event-stream"),
    f"Unexpected SSE content type: {stream_headers.get('content-type')!r}",
)

events = parse_sse(stream_body)
require(len(events) == 1, f"Expected exactly one SSE event, got {len(events)}")
event = events[0]
require(event["event"] == "session.snapshot", f"Expected session.snapshot SSE event, got {event['event']!r}")

stream_session = event["data"].get("session")
require(isinstance(stream_session, dict), "SSE event missing session payload")
require(stream_session.get("session_id") == preview_payload["session_id"], "SSE session_id did not match FOCUS preview")
require(stream_session.get("mode") == "FOCUS", f"Expected FOCUS SSE snapshot, got {stream_session.get('mode')!r}")
require(stream_session.get("top_speaker_id") == preview_payload["top_speaker_id"], "SSE top_speaker_id did not match FOCUS preview")
require(
    isinstance(stream_session.get("speakers"), list) and bool(stream_session["speakers"]),
    "SSE snapshot returned no speakers",
)

print("Verified /health, /v1/session, and /v1/events/stream against the local demo baseline.")
PY
}

main() {
  if healthcheck_gateway; then
    log "Reusing existing gateway at $GATEWAY_BASE_URL"
  else
    start_gateway
    wait_for_gateway
  fi

  log "Validating local demo gateway endpoints"
  verify_local_demo
  log "Local demo smoke check passed"
}

main "$@"