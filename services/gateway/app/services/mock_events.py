from __future__ import annotations

from app.models import MockSceneResponse, SessionMode, SessionResponse, SpeakerState
from app.services.prioritizer import build_session

_BASE_SCENE = [
    {
        "speaker_id": "speaker-alice",
        "display_name": "Alice",
        "language_code": "en",
        "priority": 0.82,
        "active": True,
        "is_locked": False,
        "front_facing": True,
        "persistence_bonus": 0.18,
        "last_updated_unix_ms": 1_710_000_000_000,
    },
    {
        "speaker_id": "speaker-bruno",
        "display_name": "Bruno",
        "language_code": "pt-BR",
        "priority": 0.76,
        "active": True,
        "is_locked": False,
        "front_facing": False,
        "persistence_bonus": 0.12,
        "last_updated_unix_ms": 1_710_000_000_200,
    },
    {
        "speaker_id": "speaker-carmen",
        "display_name": "Carmen",
        "language_code": "es",
        "priority": 0.64,
        "active": False,
        "is_locked": False,
        "front_facing": False,
        "persistence_bonus": 0.05,
        "last_updated_unix_ms": 1_710_000_000_400,
    },
    {
        "speaker_id": "speaker-devi",
        "display_name": "Devi",
        "language_code": "hi",
        "priority": 0.71,
        "active": True,
        "is_locked": False,
        "front_facing": True,
        "persistence_bonus": 0.08,
        "last_updated_unix_ms": 1_710_000_000_600,
    },
    {
        "speaker_id": "speaker-ella",
        "display_name": "Ella",
        "language_code": "fr",
        "priority": 0.58,
        "active": True,
        "is_locked": False,
        "front_facing": False,
        "persistence_bonus": 0.02,
        "last_updated_unix_ms": 1_710_000_000_800,
    },
]


def _scene_for_mode(mode: SessionMode) -> list[SpeakerState]:
    speakers = [SpeakerState(**speaker) for speaker in _BASE_SCENE]
    if mode == SessionMode.FOCUS:
        speakers[0].priority = 0.95
        speakers[0].persistence_bonus = 0.25
        speakers[2].active = False
    elif mode == SessionMode.CROWD:
        speakers[1].priority = 0.74
        speakers[2].active = True
        speakers[2].priority = 0.69
        speakers[4].priority = 0.66
    elif mode == SessionMode.LOCKED:
        speakers[1].is_locked = True
        speakers[1].front_facing = True
        speakers[1].priority = 0.7
        speakers[0].priority = 0.8
    return speakers


def build_mock_scene(mode: SessionMode = SessionMode.FOCUS) -> MockSceneResponse:
    session = SessionResponse.model_validate(
        build_session(
            session_id="demo-session",
            mode=mode,
            speakers=_scene_for_mode(mode),
        )
    )
    return MockSceneResponse(
        session=session,
        supported_modes=[SessionMode.FOCUS, SessionMode.CROWD, SessionMode.LOCKED],
    )
