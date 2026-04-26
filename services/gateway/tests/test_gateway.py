import json
import time
from threading import Thread

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _parse_sse(payload: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in payload.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        event_name = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data_line = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append({"event": event_name, "data": json.loads(data_line)})
    return events


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_event_stream_emits_snapshot_and_speaker_updates(client: TestClient) -> None:
    response = client.get("/v1/events/stream?mode=LOCKED&max_events=1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    assert len(events) == 1

    event = events[0]
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

    assert initial_event["event"] == "session.snapshot"
    assert initial_event["data"]["session"]["top_speaker_id"] == "speaker-alice"
    assert snapshot_event["event"] == "session.snapshot"
    assert snapshot_event["data"]["session"]["speakers"][0]["speaker_id"] == "speaker-alice"
    assert snapshot_event["data"]["session"]["speakers"][0]["is_locked"] is True
    assert snapshot_event["data"]["session"]["speakers"][0]["status_message"] == "Pinned by operator."

    assert speaker_event["event"] == "speaker.update"
    assert speaker_event["data"]["speaker_event"]["speaker_id"] == "speaker-alice"
    assert speaker_event["data"]["speaker_event"]["is_locked"] is True
    assert speaker_event["data"]["speaker_event"]["status_message"] == "Pinned by operator."


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
