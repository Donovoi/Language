from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_speakers_returns_ranked_session() -> None:
    response = client.post(
        "/v1/speakers",
        json={
            "mode": "LOCKED",
            "speakers": [
                {
                    "speaker_id": "speaker-a",
                    "display_name": "Alex",
                    "language_code": "en-US",
                    "priority": 0.6,
                    "active": True,
                    "is_locked": False,
                    "last_updated_unix_ms": 1,
                },
                {
                    "speaker_id": "speaker-b",
                    "display_name": "Mina",
                    "language_code": "ko-KR",
                    "priority": 0.55,
                    "active": True,
                    "is_locked": True,
                    "last_updated_unix_ms": 2,
                },
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["top_speaker_id"] == "speaker-b"
    assert [speaker["speaker_id"] for speaker in payload["speakers"]] == ["speaker-b", "speaker-a"]


def test_reset_restores_default_focus_session() -> None:
    client.post(
        "/v1/speakers",
        json={
            "mode": "CROWD",
            "speakers": [
                {
                    "speaker_id": "custom-1",
                    "display_name": "Custom",
                    "language_code": "en-US",
                    "priority": 0.4,
                    "active": True,
                    "is_locked": False,
                    "last_updated_unix_ms": 10,
                }
            ],
        },
    )

    response = client.post("/v1/session/reset")
    payload = response.json()

    assert response.status_code == 200
    assert payload["mode"] == "FOCUS"
    assert payload["session_id"] == "session-local-demo"
    assert payload["speaker_count"] >= 4


def test_mock_scene_has_expected_shape() -> None:
    response = client.get("/v1/mock/scene", params={"mode": "CROWD"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["scene_id"] == "crowd-scene"
    assert payload["session"]["mode"] == "CROWD"
    assert payload["session"]["speaker_count"] >= 4
    assert {
        "speaker_id",
        "display_name",
        "language_code",
        "priority",
        "active",
        "is_locked",
        "last_updated_unix_ms",
    }.issubset(payload["session"]["speakers"][0])
