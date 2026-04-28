from collections.abc import Callable
import csv
import json
from pathlib import Path
import time
from threading import Thread

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import SessionMode, SpeakerState
from app.routes import events as events_route
from app.services.prioritizer import build_session, score_speaker, sort_speakers


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


_PRIORITIZATION_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "crates"
    / "focus_engine"
    / "testdata"
    / "prioritization_vectors.tsv"
)


def _parse_sse(payload: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in payload.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if not any(line.startswith("event: ") for line in lines):
            continue
        event_name = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data_line = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        event_id = next(
            (line.removeprefix("id: ") for line in lines if line.startswith("id: ")),
            None,
        )
        events.append(
            {
                "id": int(event_id) if event_id is not None else None,
                "event": event_name,
                "data": json.loads(data_line),
            }
        )
    return events


def _split_sse_blocks(payload: str) -> list[list[str]]:
    return [
        [line for line in block.splitlines() if line.strip()]
        for block in payload.strip().split("\n\n")
        if any(line.strip() for line in block.splitlines())
    ]


def _wait_for(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before the timeout elapsed")


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _parse_bool_literal(raw: str) -> bool:
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise AssertionError(f"unexpected boolean literal {raw!r}")


def _load_prioritization_cases() -> list[dict[str, object]]:
    cases: dict[str, dict[str, object]] = {}

    with _PRIORITIZATION_FIXTURE_PATH.open(encoding="utf-8") as fixture:
        reader = csv.DictReader(
            [line for line in fixture if line.strip() and not line.startswith("#")],
            delimiter="\t",
        )
        for row in reader:
            case_id = row["case_id"]
            assert case_id is not None

            case = cases.setdefault(
                case_id,
                {
                    "case_id": case_id,
                    "mode": SessionMode[row["mode"]],
                    "expected_order": row["expected_order"].split(","),
                    "speakers": [],
                },
            )

            case["speakers"].append(
                {
                    "speaker": SpeakerState(
                        speaker_id=row["speaker_id"],
                        display_name=row["display_name"],
                        language_code="en",
                        priority=float(row["priority"]),
                        active=_parse_bool_literal(row["active"]),
                        is_locked=_parse_bool_literal(row["is_locked"]),
                        front_facing=_parse_bool_literal(row["front_facing"]),
                        persistence_bonus=float(row["persistence_bonus"]),
                        last_updated_unix_ms=0,
                    ),
                    "expected_score": float(row["expected_score"]),
                }
            )

    return list(cases.values())


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_and_readiness_endpoints_report_status(client: TestClient) -> None:
    live_response = client.get("/livez")
    ready_response = client.get("/readyz")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "alive"}

    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "status": "ready",
        "checks": {
            "settings": "ok",
            "session_store": "ok",
            "session_snapshot": "ok",
        },
    }


def test_readiness_returns_503_when_required_state_is_missing() -> None:
    app = create_app()
    delattr(app.state, "session_store")

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "settings": "ok",
            "session_store": "missing",
        },
    }


def test_request_logging_emits_structured_json_and_request_id_header(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_id = "req-test-123"

    with caplog.at_level("INFO", logger="language_gateway.request"):
        with TestClient(create_app()) as client:
            response = client.get("/livez", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id

    log_record = next(
        record
        for record in caplog.records
        if record.name == "language_gateway.request" and '"path":"/livez"' in record.getMessage()
    )
    payload = json.loads(log_record.getMessage())

    assert payload["event"] == "http.request"
    assert payload["request_id"] == request_id
    assert payload["method"] == "GET"
    assert payload["path"] == "/livez"
    assert payload["status_code"] == 200
    assert isinstance(payload["duration_ms"], float)


def test_read_endpoints_remain_auth_free_when_token_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGUAGE_GATEWAY_AUTH_TOKEN", "dev-token")

    with TestClient(create_app()) as client:
        session_response = client.get("/v1/session")
        events_response = client.get("/v1/events/stream?max_events=1")
        ready_response = client.get("/readyz")

    assert session_response.status_code == 200
    assert events_response.status_code == 200
    assert events_response.headers["content-type"].startswith("text/event-stream")
    assert ready_response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("put", "/v1/session/mode?mode=LOCKED", None),
        ("post", "/v1/session/reset?mode=LOCKED", None),
        ("post", "/v1/speakers", []),
        ("put", "/v1/speakers/speaker-alice/lock", None),
        ("delete", "/v1/speakers/speaker-alice/lock", None),
        ("post", "/v1/mock/live-ingest?interval_ms=1", None),
        ("delete", "/v1/mock/live-ingest", None),
    ],
)
def test_mutating_endpoints_require_bearer_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: list[dict[str, object]] | None,
) -> None:
    monkeypatch.setenv("LANGUAGE_GATEWAY_AUTH_TOKEN", "dev-token")

    request_kwargs = {"json": payload} if payload is not None else {}

    with TestClient(create_app()) as client:
        response = client.request(method, path, **request_kwargs)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == "Missing bearer token."


def test_mutating_endpoint_accepts_matching_bearer_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "dev-token"
    monkeypatch.setenv("LANGUAGE_GATEWAY_AUTH_TOKEN", token)

    with TestClient(create_app()) as client:
        response = client.put(
            "/v1/session/mode?mode=LOCKED",
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "LOCKED"


def test_mutating_endpoint_rejects_incorrect_bearer_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGUAGE_GATEWAY_AUTH_TOKEN", "dev-token")

    with TestClient(create_app()) as client:
        response = client.put(
            "/v1/session/mode?mode=LOCKED",
            headers=_auth_headers("wrong-token"),
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == "Invalid bearer token."


def test_event_stream_emits_snapshot_and_speaker_updates(client: TestClient) -> None:
    response = client.get("/v1/events/stream?mode=LOCKED&max_events=1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["connection"] == "keep-alive"
    assert response.headers["x-accel-buffering"] == "no"

    events = _parse_sse(response.text)
    assert len(events) == 1

    event = events[0]
    assert event["id"] == 0
    assert event["event"] == "session.snapshot"
    assert event["data"]["session"]["mode"] == "LOCKED"
    assert event["data"]["session"]["speakers"]


def test_event_stream_broadcasts_lock_updates() -> None:
    app = create_app()
    results: dict[str, object] = {}

    def read_stream() -> None:
        with TestClient(app) as stream_client:
            response = stream_client.get("/v1/events/stream?max_events=3")
            results["status_code"] = response.status_code
            results["headers"] = dict(response.headers)
            results["text"] = response.text

    reader = Thread(target=read_stream)
    reader.start()

    for _ in range(50):
        if app.state.session_store._subscriptions:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("event stream subscriber did not register in time")

    with TestClient(app) as mutation_client:
            lock_response = mutation_client.put("/v1/speakers/speaker-alice/lock")

    reader.join(timeout=5)

    assert lock_response.status_code == 200
    assert lock_response.json()["speakers"][0]["is_locked"] is True
    assert not reader.is_alive(), "stream reader did not finish after receiving max_events"
    assert results["status_code"] == 200

    events = _parse_sse(str(results["text"]))
    assert len(events) == 3
    initial_event, snapshot_event, speaker_event = events

    assert initial_event["id"] == 0
    assert initial_event["event"] == "session.snapshot"
    assert initial_event["data"]["session"]["top_speaker_id"] == "speaker-alice"
    assert snapshot_event["id"] == 1
    assert snapshot_event["event"] == "session.snapshot"
    assert snapshot_event["data"]["session"]["speakers"][0]["speaker_id"] == "speaker-alice"
    assert snapshot_event["data"]["session"]["speakers"][0]["is_locked"] is True
    assert snapshot_event["data"]["session"]["speakers"][0]["status_message"] == "Pinned by operator."

    assert speaker_event["id"] == 2
    assert speaker_event["event"] == "speaker.update"
    assert speaker_event["data"]["speaker_event"]["speaker_id"] == "speaker-alice"
    assert speaker_event["data"]["speaker_event"]["is_locked"] is True
    assert speaker_event["data"]["speaker_event"]["status_message"] == "Pinned by operator."


def test_event_stream_emits_keep_alive_comments_before_next_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events_route, "_KEEPALIVE_TIMEOUT_SECONDS", 0.01)
    app = create_app()
    results: dict[str, object] = {}

    def read_stream() -> None:
        with TestClient(app) as stream_client:
            response = stream_client.get("/v1/events/stream?max_events=2")
            results["status_code"] = response.status_code
            results["text"] = response.text

    reader = Thread(target=read_stream)
    reader.start()

    for _ in range(50):
        if app.state.session_store._subscriptions:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("event stream subscriber did not register in time")

    time.sleep(0.03)

    with TestClient(app) as mutation_client:
        mutation_response = mutation_client.put("/v1/speakers/speaker-alice/lock")

    reader.join(timeout=5)

    assert mutation_response.status_code == 200
    assert results["status_code"] == 200
    assert not reader.is_alive(), "stream reader did not finish after receiving max_events"

    blocks = _split_sse_blocks(str(results["text"]))
    assert any(block == [": keep-alive"] for block in blocks)

    events = _parse_sse(str(results["text"]))
    assert [event["event"] for event in events] == ["session.snapshot", "session.snapshot"]


def test_event_stream_reconnect_replays_current_snapshot_state() -> None:
    app = create_app()

    with TestClient(app) as client:
        initial_events = _parse_sse(client.get("/v1/events/stream?max_events=1").text)
        assert initial_events[0]["id"] == 0
        assert initial_events[0]["data"]["session"]["speakers"][0]["is_locked"] is False

        lock_response = client.put("/v1/speakers/speaker-alice/lock")
        assert lock_response.status_code == 200

        reconnect_events = _parse_sse(client.get("/v1/events/stream?max_events=1").text)

    assert reconnect_events[0]["id"] == 2
    assert reconnect_events[0]["event"] == "session.snapshot"
    assert reconnect_events[0]["data"]["session"]["speakers"][0]["speaker_id"] == "speaker-alice"
    assert reconnect_events[0]["data"]["session"]["speakers"][0]["is_locked"] is True
    assert reconnect_events[0]["data"]["session"]["speakers"][0]["status_message"] == "Pinned by operator."


def test_post_speakers_returns_priority_order(client: TestClient) -> None:
    response = client.post(
        "/v1/speakers?mode=LOCKED",
        json=[
            {
                "speaker_id": "speaker-a",
                "display_name": "Alice",
                "language_code": "en",
                "priority": 0.7,
                "active": True,
                "is_locked": False,
                "front_facing": False,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 1,
                "source_caption": "Where should we start?",
                "translated_caption": "Where should we start?",
                "target_language_code": "en",
                "lane_status": "READY",
                "status_message": "Translation live.",
            },
            {
                "speaker_id": "speaker-b",
                "display_name": "Bruno",
                "language_code": "pt-BR",
                "priority": 0.6,
                "active": True,
                "is_locked": True,
                "front_facing": True,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 2,
                "source_caption": "Posso compartilhar a proxima pergunta agora?",
                "translated_caption": "Can I share the next question now?",
                "target_language_code": "en",
                "lane_status": "READY",
                "status_message": "Pinned by operator.",
            },
            {
                "speaker_id": "speaker-c",
                "display_name": "Carmen",
                "language_code": "es",
                "priority": 0.9,
                "active": False,
                "is_locked": False,
                "front_facing": False,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 3,
                "source_caption": "Necesito revisar la cifra.",
                "translated_caption": "I need to verify the number.",
                "target_language_code": "en",
                "lane_status": "IDLE",
                "status_message": "Waiting for the next utterance.",
            },
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["top_speaker_id"] == "speaker-b"
    assert [speaker["speaker_id"] for speaker in payload["speakers"]] == [
        "speaker-b",
        "speaker-a",
        "speaker-c",
    ]
    assert payload["speakers"][0]["translated_caption"] == "Can I share the next question now?"
    assert payload["speakers"][0]["target_language_code"] == "en"
    assert payload["speakers"][0]["lane_status"] == "READY"


def test_prioritizer_matches_focus_engine_authority_vectors() -> None:
    for case in _load_prioritization_cases():
        case_id = str(case["case_id"])
        mode = case["mode"]
        expected_order = case["expected_order"]
        speaker_entries = case["speakers"]
        speakers = [entry["speaker"] for entry in speaker_entries]

        for entry in speaker_entries:
            speaker = entry["speaker"]
            assert round(score_speaker(speaker, mode), 3) == entry["expected_score"], (
                f"score drifted for {case_id} speaker {speaker.speaker_id}"
            )

        ordered = sort_speakers(speakers, mode)
        assert [speaker.speaker_id for speaker in ordered] == expected_order, (
            f"rank drifted for {case_id}"
        )

        session = build_session("parity-session", mode, speakers)
        assert session["top_speaker_id"] == expected_order[0], f"top speaker drifted for {case_id}"
        assert [speaker.speaker_id for speaker in session["speakers"]] == expected_order, (
            f"session ordering drifted for {case_id}"
        )


def test_post_speakers_rejects_unknown_fields_without_mutating_store(client: TestClient) -> None:
    baseline_response = client.get("/v1/session")
    assert baseline_response.status_code == 200

    response = client.post(
        "/v1/speakers",
        json=[
            {
                "speaker_id": "speaker-a",
                "display_name": "Alice",
                "language_code": "en",
                "priority": 0.7,
                "active": True,
                "is_locked": False,
                "front_facing": False,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 1,
                "unexpected": "field",
            }
        ],
    )

    assert response.status_code == 422
    assert client.get("/v1/session").json() == baseline_response.json()


def test_get_session_mode_preview_does_not_mutate_store(client: TestClient) -> None:
    preview_response = client.get("/v1/session?mode=CROWD")

    assert preview_response.status_code == 200
    assert preview_response.json()["mode"] == "CROWD"

    persisted_response = client.get("/v1/session")

    assert persisted_response.status_code == 200
    assert persisted_response.json()["mode"] == "FOCUS"


def test_put_session_mode_updates_store(client: TestClient) -> None:
    response = client.put("/v1/session/mode?mode=LOCKED")

    assert response.status_code == 200
    assert response.json()["mode"] == "LOCKED"
    assert client.get("/v1/session").json()["mode"] == "LOCKED"


def test_lock_and_unlock_speaker_updates_store(client: TestClient) -> None:
    lock_response = client.put("/v1/speakers/speaker-alice/lock")

    assert lock_response.status_code == 200
    assert lock_response.json()["speakers"][0]["speaker_id"] == "speaker-alice"
    assert lock_response.json()["speakers"][0]["is_locked"] is True

    unlock_response = client.delete("/v1/speakers/speaker-alice/lock")

    assert unlock_response.status_code == 200
    updated_alice = next(
        speaker
        for speaker in unlock_response.json()["speakers"]
        if speaker["speaker_id"] == "speaker-alice"
    )
    assert updated_alice["is_locked"] is False
    assert updated_alice["status_message"] == "Lock released."


def test_lock_returns_404_for_missing_speaker(client: TestClient) -> None:
    response = client.put("/v1/speakers/speaker-missing/lock")

    assert response.status_code == 404
    assert response.json()["detail"] == "Speaker 'speaker-missing' was not found."


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/v1/session?mode=INVALID", None),
        ("put", "/v1/session/mode?mode=INVALID", None),
        ("post", "/v1/session/reset?mode=INVALID", None),
        ("get", "/v1/mock/scene?mode=INVALID", None),
        ("post", "/v1/mock/live-ingest?mode=INVALID", None),
        ("post", "/v1/speakers?mode=INVALID", []),
    ],
)
def test_invalid_mode_requests_return_422(
    client: TestClient,
    method: str,
    path: str,
    payload: list[dict[str, object]] | None,
) -> None:
    response = client.request(method, path, json=payload)

    assert response.status_code == 422


def test_post_speakers_allows_empty_list_and_persists_mode(client: TestClient) -> None:
    mode_response = client.put("/v1/session/mode?mode=LOCKED")
    assert mode_response.status_code == 200

    response = client.post("/v1/speakers", json=[])

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "demo-session",
        "mode": "LOCKED",
        "speakers": [],
        "top_speaker_id": None,
    }
    assert client.get("/v1/speakers").json() == []
    assert client.get("/v1/session").json() == response.json()


def test_reset_restores_focus_mock_scene(client: TestClient) -> None:
    client.post(
        "/v1/speakers",
        json=[
            {
                "speaker_id": "speaker-z",
                "display_name": "Zara",
                "language_code": "de",
                "priority": 1.0,
                "active": True,
                "is_locked": False,
                "front_facing": False,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 4,
            }
        ],
    )

    response = client.post("/v1/session/reset?mode=FOCUS")

    assert response.status_code == 200
    payload = response.json()
    assert payload["reset"] is True
    assert payload["session"]["session_id"] == "demo-session"
    assert payload["session"]["top_speaker_id"] == "speaker-alice"
    assert len(payload["session"]["speakers"]) == 5


def test_reset_without_mode_restores_focus_after_empty_locked_state(client: TestClient) -> None:
    clear_response = client.post("/v1/speakers?mode=LOCKED", json=[])
    assert clear_response.status_code == 200
    assert clear_response.json()["top_speaker_id"] is None

    response = client.post("/v1/session/reset")

    assert response.status_code == 200
    payload = response.json()
    assert payload["reset"] is True
    assert payload["session"]["mode"] == "FOCUS"
    assert payload["session"]["top_speaker_id"] == "speaker-alice"
    assert len(payload["session"]["speakers"]) == 5


def test_restart_restores_persisted_session_and_sse_snapshot() -> None:
    replacement_payload = [
        {
            "speaker_id": "speaker-a",
            "display_name": "Alice",
            "language_code": "en",
            "priority": 0.7,
            "active": True,
            "is_locked": False,
            "front_facing": False,
            "persistence_bonus": 0.0,
            "last_updated_unix_ms": 101,
            "source_caption": "Where should we start?",
            "translated_caption": "Where should we start?",
            "target_language_code": "en",
            "lane_status": "READY",
            "status_message": "Translation live.",
        },
        {
            "speaker_id": "speaker-b",
            "display_name": "Bruno",
            "language_code": "pt-BR",
            "priority": 0.6,
            "active": True,
            "is_locked": True,
            "front_facing": True,
            "persistence_bonus": 0.0,
            "last_updated_unix_ms": 102,
            "source_caption": "Posso compartilhar a próxima pergunta agora?",
            "translated_caption": "Can I share the next question now?",
            "target_language_code": "en",
            "lane_status": "READY",
            "status_message": "Pinned by operator.",
        },
    ]

    with TestClient(create_app()) as first_client:
        mutation_response = first_client.post("/v1/speakers?mode=LOCKED", json=replacement_payload)

    assert mutation_response.status_code == 200
    persisted_session = mutation_response.json()
    assert persisted_session["mode"] == "LOCKED"
    assert persisted_session["top_speaker_id"] == "speaker-b"
    assert persisted_session["speakers"][0]["speaker_id"] == "speaker-b"
    assert persisted_session["speakers"][0]["is_locked"] is True

    with TestClient(create_app()) as restarted_client:
        restored_response = restarted_client.get("/v1/session")
        stream_response = restarted_client.get("/v1/events/stream?max_events=1")

    assert restored_response.status_code == 200
    assert restored_response.json() == persisted_session

    stream_events = _parse_sse(stream_response.text)
    assert len(stream_events) == 1
    assert stream_events[0]["id"] == 0
    assert stream_events[0]["event"] == "session.snapshot"
    assert stream_events[0]["data"]["session"] == persisted_session


def test_reset_persists_fallback_mock_scene_across_restart() -> None:
    with TestClient(create_app()) as first_client:
        clear_response = first_client.post("/v1/speakers?mode=LOCKED", json=[])
        assert clear_response.status_code == 200
        assert clear_response.json()["top_speaker_id"] is None

        reset_response = first_client.post("/v1/session/reset?mode=FOCUS")

    assert reset_response.status_code == 200
    reset_payload = reset_response.json()
    assert reset_payload["reset"] is True
    assert reset_payload["session"]["mode"] == "FOCUS"

    with TestClient(create_app()) as restarted_client:
        restored_response = restarted_client.get("/v1/session")

    assert restored_response.status_code == 200
    restored_session = restored_response.json()
    assert restored_session == reset_payload["session"]
    assert restored_session["top_speaker_id"] == "speaker-alice"
    assert len(restored_session["speakers"]) == 5
    assert all(speaker["is_locked"] is False for speaker in restored_session["speakers"])


def test_mock_scene_shape_changes_with_mode(client: TestClient) -> None:
    response = client.get("/v1/mock/scene?mode=CROWD")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["mode"] == "CROWD"
    assert payload["supported_modes"] == ["FOCUS", "CROWD", "LOCKED"]
    assert len(payload["session"]["speakers"]) == 5
    assert payload["session"]["speakers"][0]["speaker_id"] == "speaker-alice"
    assert payload["session"]["speakers"][0]["translated_caption"]
    assert payload["session"]["speakers"][0]["target_language_code"] == "en"
    assert payload["session"]["speakers"][0]["lane_status"] == "READY"


def test_live_ingest_stream_emits_progressive_snapshot_updates() -> None:
    app = create_app()
    results: dict[str, object] = {}

    def read_stream() -> None:
        with TestClient(app) as stream_client:
            response = stream_client.get("/v1/events/stream?max_events=8")
            results["status_code"] = response.status_code
            results["text"] = response.text

    reader = Thread(target=read_stream)
    reader.start()

    _wait_for(lambda: bool(app.state.session_store._subscriptions))

    with TestClient(app) as mutation_client:
        start_response = mutation_client.post("/v1/mock/live-ingest?interval_ms=1")

    reader.join(timeout=5)

    assert start_response.status_code == 202
    payload = start_response.json()
    assert payload["started"] is True
    assert payload["status"]["active"] is True
    assert payload["status"]["total_steps"] >= 20
    assert not reader.is_alive(), "stream reader did not finish after receiving max_events"
    assert results["status_code"] == 200

    events = _parse_sse(str(results["text"]))
    assert len(events) == 8
    assert [event["event"] for event in events] == ["session.snapshot"] * 8

    assert events[2]["data"]["session"]["speakers"][0]["speaker_id"] == "speaker-alice"
    assert events[2]["data"]["session"]["speakers"][0]["lane_status"] == "LISTENING"
    assert events[2]["data"]["session"]["speakers"][0]["translated_caption"] is None

    assert events[3]["data"]["session"]["speakers"][0]["lane_status"] == "TRANSLATING"
    assert events[4]["data"]["session"]["speakers"][0]["lane_status"] == "READY"
    assert (
        events[4]["data"]["session"]["speakers"][0]["translated_caption"]
        == "Let's open with field safety and timing."
    )

    assert events[5]["data"]["session"]["top_speaker_id"] == "speaker-bruno"
    assert events[5]["data"]["session"]["speakers"][0]["lane_status"] == "LISTENING"
    assert events[6]["data"]["session"]["speakers"][0]["lane_status"] == "TRANSLATING"
    assert events[7]["data"]["session"]["speakers"][0]["lane_status"] == "READY"


def test_live_ingest_emits_lock_and_unlock_speaker_events_over_sse() -> None:
    app = create_app()
    results: dict[str, object] = {}

    def read_stream() -> None:
        with TestClient(app) as stream_client:
            response = stream_client.get("/v1/events/stream?max_events=19")
            results["status_code"] = response.status_code
            results["text"] = response.text

    reader = Thread(target=read_stream)
    reader.start()

    _wait_for(lambda: bool(app.state.session_store._subscriptions))

    with TestClient(app) as mutation_client:
        start_response = mutation_client.post("/v1/mock/live-ingest?interval_ms=1")

    reader.join(timeout=5)

    assert start_response.status_code == 202
    assert not reader.is_alive(), "stream reader did not finish after receiving max_events"
    assert results["status_code"] == 200

    events = _parse_sse(str(results["text"]))
    speaker_updates = [event for event in events if event["event"] == "speaker.update"]

    assert len(speaker_updates) == 2
    assert speaker_updates[0]["data"]["speaker_event"]["speaker_id"] == "speaker-bruno"
    assert speaker_updates[0]["data"]["speaker_event"]["is_locked"] is True
    assert speaker_updates[0]["data"]["speaker_event"]["status_message"] == "Pinned by operator."

    assert speaker_updates[1]["data"]["speaker_event"]["speaker_id"] == "speaker-bruno"
    assert speaker_updates[1]["data"]["speaker_event"]["is_locked"] is False
    assert speaker_updates[1]["data"]["speaker_event"]["status_message"] == "Lock released."


def test_live_ingest_status_and_stop_endpoint_report_progress() -> None:
    app = create_app()

    with TestClient(app) as client:
        start_response = client.post("/v1/mock/live-ingest?mode=CROWD&interval_ms=20")

        assert start_response.status_code == 202
        assert start_response.json()["status"]["mode"] == "CROWD"

        _wait_for(lambda: client.get("/v1/mock/live-ingest").json()["applied_steps"] >= 1)

        status_response = client.get("/v1/mock/live-ingest")
        assert status_response.status_code == 200
        status_payload = status_response.json()
        assert status_payload["active"] is True
        assert status_payload["scenario_id"] == "briefing"
        assert status_payload["supported_scenarios"] == ["briefing"]
        assert status_payload["total_steps"] >= 20
        assert status_payload["remaining_steps"] < status_payload["total_steps"]

        conflict_response = client.post("/v1/mock/live-ingest?interval_ms=20")
        assert conflict_response.status_code == 409

        stop_response = client.delete("/v1/mock/live-ingest")
        assert stop_response.status_code == 200
        stop_payload = stop_response.json()
        assert stop_payload["stopped"] is True
        assert stop_payload["status"]["active"] is False
        assert stop_payload["status"]["completed"] is False
        assert stop_payload["status"]["applied_steps"] < stop_payload["status"]["total_steps"]

        final_status_response = client.get("/v1/mock/live-ingest")
        assert final_status_response.status_code == 200
        final_status_payload = final_status_response.json()
        assert final_status_payload["active"] is False
        assert final_status_payload["applied_steps"] == stop_payload["status"]["applied_steps"]
