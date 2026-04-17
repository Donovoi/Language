from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_speakers_returns_priority_order() -> None:
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


def test_reset_restores_focus_mock_scene() -> None:
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

    response = client.post("/v1/session/reset")

    assert response.status_code == 200
    payload = response.json()
    assert payload["reset"] is True
    assert payload["session"]["session_id"] == "demo-session"
    assert payload["session"]["top_speaker_id"] == "speaker-alice"
    assert len(payload["session"]["speakers"]) == 5


def test_mock_scene_shape_changes_with_mode() -> None:
    response = client.get("/v1/mock/scene?mode=CROWD")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["mode"] == "CROWD"
    assert payload["supported_modes"] == ["FOCUS", "CROWD", "LOCKED"]
    assert len(payload["session"]["speakers"]) == 5
    assert payload["session"]["speakers"][0]["speaker_id"] == "speaker-alice"
