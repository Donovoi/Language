import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_speakers_returns_ranked_session(client: TestClient) -> None:
    response = client.post(
        "/v1/speakers?mode=LOCKED",
        json=[
            {
                "speaker_id": "speaker-a",
                "display_name": "Alex",
                "language_code": "en-US",
                "priority": 0.6,
                "active": True,
                "is_locked": False,
                "front_facing": False,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 1,
            },
            {
                "speaker_id": "speaker-b",
                "display_name": "Mina",
                "language_code": "ko-KR",
                "priority": 0.55,
                "active": True,
                "is_locked": True,
                "front_facing": True,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 2,
            },
        ],
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["top_speaker_id"] == "speaker-b"
    assert [speaker["speaker_id"] for speaker in payload["speakers"]] == ["speaker-b", "speaker-a"]


def test_reset_restores_default_focus_session(client: TestClient) -> None:
    client.post(
        "/v1/speakers",
        json=[
            {
                "speaker_id": "custom-1",
                "display_name": "Custom",
                "language_code": "en-US",
                "priority": 0.4,
                "active": True,
                "is_locked": False,
                "front_facing": False,
                "persistence_bonus": 0.0,
                "last_updated_unix_ms": 10,
            }
        ],
    )

    response = client.post("/v1/session/reset?mode=FOCUS")
    payload = response.json()

    assert response.status_code == 200
    assert payload["reset"] is True
    assert payload["session"]["mode"] == "FOCUS"
    assert payload["session"]["session_id"] == "demo-session"
    assert len(payload["session"]["speakers"]) >= 4


def test_mock_scene_has_expected_shape(client: TestClient) -> None:
    response = client.get("/v1/mock/scene", params={"mode": "CROWD"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["supported_modes"] == ["FOCUS", "CROWD", "LOCKED"]
    assert payload["session"]["mode"] == "CROWD"
    assert len(payload["session"]["speakers"]) >= 4
    assert {
        "speaker_id",
        "display_name",
        "language_code",
        "priority",
        "active",
        "is_locked",
        "front_facing",
        "persistence_bonus",
        "last_updated_unix_ms",
    }.issubset(payload["session"]["speakers"][0])
