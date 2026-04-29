#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_DIR="$ROOT_DIR/services/gateway"
DEFAULT_GATEWAY_PYTHON="$GATEWAY_DIR/.venv/bin/python"

GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-8010}"
GATEWAY_BASE_URL="http://${GATEWAY_HOST}:${GATEWAY_PORT}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-5}"
STREAM_CAPTURE_TIMEOUT_SECONDS="${STREAM_CAPTURE_TIMEOUT_SECONDS:-20}"
SMOKE_START_TIMEOUT_SECONDS="${SMOKE_START_TIMEOUT_SECONDS:-20}"
LIVE_INGEST_INTERVAL_MS="${LIVE_INGEST_INTERVAL_MS:-80}"
EXPECTED_STREAM_EVENTS="${EXPECTED_STREAM_EVENTS:-8}"
REQUEST_PYTHON_CANDIDATE="${REQUEST_PYTHON:-python3}"
GATEWAY_PYTHON_CANDIDATE="${GATEWAY_PYTHON:-$DEFAULT_GATEWAY_PYTHON}"

STARTED_GATEWAY=0
GATEWAY_PID=""
TMP_DIR="$(mktemp -d)"
GATEWAY_LOG_FILE="$TMP_DIR/gateway.log"
SESSION_SNAPSHOT_FILE="$TMP_DIR/persisted-session.json"

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

normalize_path() {
  local candidate="$1"

  if [[ "$candidate" != /* ]]; then
    candidate="$PWD/$candidate"
  fi

  printf '%s\n' "$candidate"
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
SESSION_DB_PATH_CANDIDATE="${SMOKE_SESSION_DB_PATH:-$TMP_DIR/session-store.sqlite3}"
SESSION_DB_PATH="$(normalize_path "$SESSION_DB_PATH_CANDIDATE")"

if [[ -z "$REQUEST_PYTHON_BIN" ]]; then
  fail "Unable to find a Python interpreter for HTTP validation. Set REQUEST_PYTHON or install python3."
fi

mkdir -p "$(dirname "$SESSION_DB_PATH")"

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

stop_gateway() {
  if [[ $STARTED_GATEWAY -eq 0 || -z "$GATEWAY_PID" ]]; then
    return 0
  fi

  if kill -0 "$GATEWAY_PID" 2>/dev/null; then
    kill "$GATEWAY_PID" 2>/dev/null || true
  fi
  wait "$GATEWAY_PID" 2>/dev/null || true
  STARTED_GATEWAY=0
  GATEWAY_PID=""
}

start_gateway() {
  if healthcheck_gateway; then
    fail "A gateway is already responding at $GATEWAY_BASE_URL. Use a different GATEWAY_PORT for the isolated integration smoke."
  fi

  if [[ -z "$GATEWAY_PYTHON_BIN" ]]; then
    fail "Gateway Python was not found at $GATEWAY_PYTHON_CANDIDATE. Run make bootstrap or make gateway-venv first."
  fi

  log "Starting isolated gateway at $GATEWAY_BASE_URL"
  (
    cd "$GATEWAY_DIR"
    export LANGUAGE_GATEWAY_SESSION_DB_PATH="$SESSION_DB_PATH"
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

exercise_live_ingest_and_capture_snapshot() {
  GATEWAY_BASE_URL="$GATEWAY_BASE_URL" \
    REQUEST_TIMEOUT_SECONDS="$REQUEST_TIMEOUT_SECONDS" \
    STREAM_CAPTURE_TIMEOUT_SECONDS="$STREAM_CAPTURE_TIMEOUT_SECONDS" \
    LIVE_INGEST_INTERVAL_MS="$LIVE_INGEST_INTERVAL_MS" \
    EXPECTED_STREAM_EVENTS="$EXPECTED_STREAM_EVENTS" \
    LANGUAGE_GATEWAY_AUTH_TOKEN="${LANGUAGE_GATEWAY_AUTH_TOKEN:-}" \
    SESSION_SNAPSHOT_FILE="$SESSION_SNAPSHOT_FILE" \
    "$REQUEST_PYTHON_BIN" - <<'PY'
import json
import os
import threading
import time
import urllib.error
import urllib.request

base_url = os.environ["GATEWAY_BASE_URL"].rstrip("/")
timeout = float(os.environ["REQUEST_TIMEOUT_SECONDS"])
stream_timeout = float(os.environ["STREAM_CAPTURE_TIMEOUT_SECONDS"])
interval_ms = int(os.environ["LIVE_INGEST_INTERVAL_MS"])
expected_events = int(os.environ["EXPECTED_STREAM_EVENTS"])
auth_token = os.environ.get("LANGUAGE_GATEWAY_AUTH_TOKEN", "").strip() or None
snapshot_file = os.environ["SESSION_SNAPSHOT_FILE"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def perform_request(
    path: str,
    *,
    method: str = "GET",
    accept: str = "application/json",
    json_body: object | None = None,
    auth: bool = False,
) -> tuple[int, dict[str, str], str]:
    headers = {"Accept": accept}
    if auth and auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    payload = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(json_body).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url}{path}",
        headers=headers,
        data=payload,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, response_headers, body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SystemExit(f"{method} {path} failed: {exc}") from exc


def request_json(
    path: str,
    *,
    method: str = "GET",
    json_body: object | None = None,
    auth: bool = False,
) -> dict[str, object]:
    status, _headers, body = perform_request(
        path,
        method=method,
        json_body=json_body,
        auth=auth,
    )
    require(status == 200 or status == 202, f"Unexpected status {status} for {method} {path}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Expected JSON from {method} {path}: {exc}") from exc


def parse_sse_block(lines: list[str]) -> dict[str, object] | None:
    if not lines or all(line.startswith(":") for line in lines):
        return None

    event_name = None
    event_id = None
    data_lines: list[str] = []

    for line in lines:
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("id: "):
            raw_event_id = line.removeprefix("id: ")
            event_id = int(raw_event_id)
        elif line.startswith("data: "):
            data_lines.append(line.removeprefix("data: "))

    require(event_name is not None, f"SSE payload missing event name: {lines!r}")
    require(data_lines, f"SSE payload missing data lines: {lines!r}")

    return {
        "id": event_id,
        "event": event_name,
        "data": json.loads("\n".join(data_lines)),
    }


initial_session = request_json("/v1/session")
require(initial_session.get("mode") == "FOCUS", f"Expected initial FOCUS session, got {initial_session.get('mode')!r}")

captured_events: list[dict[str, object]] = []
stream_errors: list[BaseException] = []
ready_event = threading.Event()


def read_stream() -> None:
    request = urllib.request.Request(
        f"{base_url}/v1/events/stream?mode=FOCUS&max_events={expected_events}",
        headers={"Accept": "text/event-stream"},
    )

    try:
        with urllib.request.urlopen(request, timeout=stream_timeout) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            require(response.status == 200, f"Unexpected SSE status: {response.status}")
            require(
                headers.get("content-type", "").startswith("text/event-stream"),
                f"Unexpected SSE content type: {headers.get('content-type')!r}",
            )

            block: list[str] = []
            while len(captured_events) < expected_events:
                raw_line = response.readline()
                if raw_line == b"":
                    break

                line = raw_line.decode("utf-8").rstrip("\n").rstrip("\r")
                if line == "":
                    event = parse_sse_block(block)
                    block = []
                    if event is None:
                        continue
                    captured_events.append(event)
                    if len(captured_events) == 1:
                        ready_event.set()
                    continue

                block.append(line)

            if block and len(captured_events) < expected_events:
                event = parse_sse_block(block)
                if event is not None:
                    captured_events.append(event)
                    if len(captured_events) == 1:
                        ready_event.set()
    except BaseException as exc:  # pragma: no cover - smoke harness only
        stream_errors.append(exc)
        ready_event.set()


reader = threading.Thread(target=read_stream, name="integration-smoke-sse", daemon=True)
reader.start()

require(ready_event.wait(timeout=5.0), "Timed out waiting for the initial SSE snapshot.")
if stream_errors:
    raise SystemExit(f"SSE capture failed before live ingest started: {stream_errors[0]}")

start_payload = request_json(
    f"/v1/mock/live-ingest?mode=FOCUS&interval_ms={interval_ms}",
    method="POST",
    auth=True,
)
require(start_payload.get("started") is True, f"Unexpected live-ingest start payload: {start_payload!r}")
start_status = start_payload.get("status")
require(isinstance(start_status, dict), f"Live-ingest start response missing status: {start_payload!r}")
require(start_status.get("active") is True, f"Live-ingest did not report active status: {start_status!r}")
require(
    isinstance(start_status.get("total_steps"), int) and start_status["total_steps"] >= 20,
    f"Live-ingest total_steps was too small: {start_status!r}",
)

reader.join(timeout=stream_timeout)
require(not reader.is_alive(), "Timed out waiting for the expected live-ingest SSE updates.")
if stream_errors:
    raise SystemExit(f"SSE capture failed while live ingest was running: {stream_errors[0]}")

require(len(captured_events) == expected_events, f"Expected {expected_events} SSE events, got {len(captured_events)}")
require(
    [event["event"] for event in captured_events] == ["session.snapshot"] * expected_events,
    f"Unexpected SSE event types: {[event['event'] for event in captured_events]!r}",
)
require(captured_events[0]["id"] == 0, f"Expected initial SSE event id 0, got {captured_events[0]['id']!r}")
require(captured_events[0]["data"]["session"]["mode"] == "FOCUS", "Initial SSE snapshot was not FOCUS mode.")
require(
    captured_events[0]["data"]["session"]["session_id"] == initial_session["session_id"],
    "Initial SSE snapshot did not match the persisted session id.",
)
require(
    captured_events[2]["data"]["session"]["speakers"][0]["speaker_id"] == "speaker-alice",
    "Expected Alice to lead the first live-ingest update.",
)
require(
    captured_events[2]["data"]["session"]["speakers"][0]["lane_status"] == "LISTENING",
    "Expected Alice to enter LISTENING during live ingest.",
)
require(
    captured_events[3]["data"]["session"]["speakers"][0]["lane_status"] == "TRANSLATING",
    "Expected Alice to enter TRANSLATING during live ingest.",
)
require(
    captured_events[4]["data"]["session"]["speakers"][0]["lane_status"] == "READY",
    "Expected Alice to reach READY during live ingest.",
)
require(
    captured_events[5]["data"]["session"]["top_speaker_id"] == "speaker-bruno",
    "Expected Bruno to become the top speaker during live ingest.",
)
require(
    captured_events[6]["data"]["session"]["speakers"][0]["lane_status"] == "TRANSLATING",
    "Expected Bruno to reach TRANSLATING during live ingest.",
)
require(
    captured_events[7]["data"]["session"]["speakers"][0]["lane_status"] == "READY",
    "Expected Bruno to reach READY during live ingest.",
)


def wait_for_progress(min_steps: int) -> dict[str, object]:
    deadline = time.monotonic() + stream_timeout
    last_status: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last_status = request_json("/v1/mock/live-ingest")
        applied_steps = last_status.get("applied_steps")
        if isinstance(applied_steps, int) and applied_steps >= min_steps:
            return last_status
        time.sleep(0.05)
    raise SystemExit(f"Live ingest did not reach {min_steps} steps before timeout; last status: {last_status!r}")


progress_status = wait_for_progress(8)
require(progress_status.get("active") is True, f"Live-ingest stopped too early: {progress_status!r}")

stop_payload = request_json("/v1/mock/live-ingest", method="DELETE", auth=True)
require(stop_payload.get("stopped") is True, f"Unexpected live-ingest stop payload: {stop_payload!r}")
stop_status = stop_payload.get("status")
require(isinstance(stop_status, dict), f"Live-ingest stop response missing status: {stop_payload!r}")
require(stop_status.get("active") is False, f"Live-ingest still reported active after stop: {stop_status!r}")
require(stop_status.get("completed") is False, f"Expected a partial stop, got completed status: {stop_status!r}")
require(
    isinstance(stop_status.get("applied_steps"), int) and stop_status["applied_steps"] >= 8,
    f"Live-ingest stop did not persist enough progress: {stop_status!r}",
)
require(
    isinstance(stop_status.get("total_steps"), int) and stop_status["applied_steps"] < stop_status["total_steps"],
    f"Expected live-ingest to stop before completion: {stop_status!r}",
)

final_status = request_json("/v1/mock/live-ingest")
require(final_status.get("active") is False, f"Expected inactive live-ingest status after stop: {final_status!r}")
require(
    final_status.get("applied_steps") == stop_status.get("applied_steps"),
    f"Live-ingest progress changed unexpectedly after stop: {final_status!r}",
)

persisted_session = request_json("/v1/session")
require(
    persisted_session != initial_session,
    "Expected partial live-ingest progress to persist a changed session snapshot.",
)

with open(snapshot_file, "w", encoding="utf-8") as handle:
    json.dump(persisted_session, handle, indent=2, sort_keys=True)

print(
    "Verified /health, captured live SSE updates during /v1/mock/live-ingest, "
    "stopped the ingest run mid-flight, and saved the persisted session for restart verification."
)
PY
}

verify_persisted_snapshot_after_restart() {
  GATEWAY_BASE_URL="$GATEWAY_BASE_URL" \
    REQUEST_TIMEOUT_SECONDS="$REQUEST_TIMEOUT_SECONDS" \
    SESSION_SNAPSHOT_FILE="$SESSION_SNAPSHOT_FILE" \
    "$REQUEST_PYTHON_BIN" - <<'PY'
import json
import os
import urllib.error
import urllib.request

base_url = os.environ["GATEWAY_BASE_URL"].rstrip("/")
timeout = float(os.environ["REQUEST_TIMEOUT_SECONDS"])
snapshot_file = os.environ["SESSION_SNAPSHOT_FILE"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def perform_request(path: str, *, accept: str = "application/json") -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Accept": accept},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, headers, body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GET {path} returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SystemExit(f"GET {path} failed: {exc}") from exc


def request_json(path: str) -> dict[str, object]:
    status, _headers, body = perform_request(path)
    require(status == 200, f"Unexpected status {status} for GET {path}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Expected JSON from GET {path}: {exc}") from exc


def parse_sse(payload: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in payload.split("\n\n"):
        lines = [line.rstrip("\r") for line in block.splitlines() if line.strip()]
        if not lines or all(line.startswith(":") for line in lines):
            continue

        event_name = None
        data_lines: list[str] = []
        event_id = None

        for line in lines:
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("id: "):
                event_id = int(line.removeprefix("id: "))
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))

        require(event_name is not None, f"SSE payload missing event name: {payload!r}")
        require(data_lines, f"SSE payload missing data lines: {payload!r}")
        events.append(
            {
                "id": event_id,
                "event": event_name,
                "data": json.loads("\n".join(data_lines)),
            }
        )

    return events


with open(snapshot_file, encoding="utf-8") as handle:
    expected_session = json.load(handle)

health = request_json("/health")
require(health == {"status": "ok"}, f"Unexpected /health payload after restart: {health!r}")

restored_session = request_json("/v1/session")
require(
    restored_session == expected_session,
    "Persisted session did not survive gateway restart.",
)

live_ingest_status = request_json("/v1/mock/live-ingest")
require(live_ingest_status.get("active") is False, f"Live-ingest runner was unexpectedly active after restart: {live_ingest_status!r}")

stream_status, stream_headers, stream_body = perform_request(
    "/v1/events/stream?max_events=1",
    accept="text/event-stream",
)
require(stream_status == 200, f"Unexpected SSE status after restart: {stream_status}")
require(
    stream_headers.get("content-type", "").startswith("text/event-stream"),
    f"Unexpected SSE content type after restart: {stream_headers.get('content-type')!r}",
)

stream_events = parse_sse(stream_body)
require(len(stream_events) == 1, f"Expected one SSE snapshot after restart, got {len(stream_events)}")
require(stream_events[0]["event"] == "session.snapshot", f"Unexpected SSE event after restart: {stream_events[0]['event']!r}")
require(
    stream_events[0]["data"]["session"] == expected_session,
    "Initial SSE snapshot after restart did not match the restored session.",
)

print(
    "Verified that the restarted gateway restored the persisted session and emitted the same snapshot over /v1/events/stream."
)
PY
}

main() {
  start_gateway
  wait_for_gateway

  log "Running automated integration smoke against /health, /v1/events/stream, and /v1/mock/live-ingest"
  exercise_live_ingest_and_capture_snapshot

  log "Restarting the isolated gateway to verify SQLite-backed session recovery"
  stop_gateway
  start_gateway
  wait_for_gateway
  verify_persisted_snapshot_after_restart

  log "Cross-stack integration smoke passed"
}

main "$@"
