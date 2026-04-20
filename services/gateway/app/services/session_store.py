from __future__ import annotations

import logging
from threading import Lock

from fastapi import Request

from app.models import SessionMode, SessionResponse, SpeakerState
from app.services.mock_events import build_mock_scene
from app.services.prioritizer import build_session

logger = logging.getLogger("language.gateway.session_store")


class SessionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._session = build_mock_scene(SessionMode.FOCUS).session

    def current(self) -> SessionResponse:
        with self._lock:
            return self._session.model_copy(deep=True)

    def preview(self, mode: SessionMode) -> SessionResponse:
        with self._lock:
            return SessionResponse.model_validate(
                build_session(self._session.session_id, mode, self._session.speakers)
            )

    def reset(self, mode: SessionMode = SessionMode.FOCUS) -> SessionResponse:
        with self._lock:
            self._session = build_mock_scene(mode).session
            logger.info("session_reset mode=%s speaker_count=%s", mode.value, len(self._session.speakers))
            return self._session.model_copy(deep=True)

    def set_mode(self, mode: SessionMode) -> SessionResponse:
        with self._lock:
            self._session = SessionResponse.model_validate(
                build_session(self._session.session_id, mode, self._session.speakers)
            )
            logger.info("session_mode_updated mode=%s speaker_count=%s", mode.value, len(self._session.speakers))
            return self._session.model_copy(deep=True)

    def replace_speakers(
        self,
        speakers: list[SpeakerState],
        mode: SessionMode | None = None,
    ) -> SessionResponse:
        with self._lock:
            selected_mode = mode or self._session.mode
            self._session = SessionResponse.model_validate(
                build_session(self._session.session_id, selected_mode, speakers)
            )
            logger.info(
                "session_speakers_replaced mode=%s speaker_count=%s",
                selected_mode.value,
                len(self._session.speakers),
            )
            return self._session.model_copy(deep=True)


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store
