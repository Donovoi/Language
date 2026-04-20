import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
