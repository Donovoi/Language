from __future__ import annotations

from app.models import SessionMode, SessionResponse, SpeakerState
from app.services.mock_events import build_mock_scene
from app.services.prioritizer import build_session


class SessionStore:
    def __init__(self) -> None:
        self._session = build_mock_scene(SessionMode.FOCUS).session

    def current(self) -> SessionResponse:
        return self._session.model_copy(deep=True)

    def reset(self, mode: SessionMode = SessionMode.FOCUS) -> SessionResponse:
        self._session = build_mock_scene(mode).session
        return self.current()

    def set_mode(self, mode: SessionMode) -> SessionResponse:
        self._session = SessionResponse.model_validate(
            build_session(self._session.session_id, mode, self._session.speakers)
        )
        return self.current()

    def replace_speakers(self, speakers: list[SpeakerState], mode: SessionMode | None = None) -> SessionResponse:
        selected_mode = mode or self._session.mode
        self._session = SessionResponse.model_validate(
            build_session(self._session.session_id, selected_mode, speakers)
        )
        return self.current()


store = SessionStore()
