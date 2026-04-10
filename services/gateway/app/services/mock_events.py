from collections.abc import Iterable
from copy import deepcopy

from app.models import (
    MockSceneResponse,
    SessionMode,
    SessionResponse,
    SpeakerInput,
    SpeakersResponse,
)
from app.services.prioritizer import SpeakerPrioritizer

_DEFAULT_SESSION_ID = "session-local-demo"

_MOCK_SCENES: dict[SessionMode, list[SpeakerInput]] = {
    SessionMode.FOCUS: [
        SpeakerInput(
            speaker_id="speaker-01",
            display_name="Alex",
            language_code="en-US",
            priority=0.92,
            active=True,
            is_locked=False,
            last_updated_unix_ms=1712745001000,
        ),
        SpeakerInput(
            speaker_id="speaker-02",
            display_name="Mina",
            language_code="ko-KR",
            priority=0.63,
            active=True,
            is_locked=False,
            last_updated_unix_ms=1712745001200,
        ),
        SpeakerInput(
            speaker_id="speaker-03",
            display_name="Luis",
            language_code="es-ES",
            priority=0.48,
            active=False,
            is_locked=False,
            last_updated_unix_ms=1712744999000,
        ),
        SpeakerInput(
            speaker_id="speaker-04",
            display_name="Nora",
            language_code="fr-FR",
            priority=0.41,
            active=False,
            is_locked=False,
            last_updated_unix_ms=1712744997000,
        ),
    ],
    SessionMode.CROWD: [
        SpeakerInput(
            speaker_id="speaker-01",
            display_name="Alex",
            language_code="en-US",
            priority=0.72,
            active=True,
            is_locked=False,
            last_updated_unix_ms=1712745001000,
        ),
        SpeakerInput(
            speaker_id="speaker-02",
            display_name="Mina",
            language_code="ko-KR",
            priority=0.68,
            active=True,
            is_locked=False,
            last_updated_unix_ms=1712745001200,
        ),
        SpeakerInput(
            speaker_id="speaker-03",
            display_name="Luis",
            language_code="es-ES",
            priority=0.61,
            active=True,
            is_locked=False,
            last_updated_unix_ms=1712745001400,
        ),
        SpeakerInput(
            speaker_id="speaker-04",
            display_name="Nora",
            language_code="fr-FR",
            priority=0.54,
            active=False,
            is_locked=False,
            last_updated_unix_ms=1712744997000,
        ),
        SpeakerInput(
            speaker_id="speaker-05",
            display_name="Jae",
            language_code="ja-JP",
            priority=0.47,
            active=True,
            is_locked=False,
            last_updated_unix_ms=1712745001600,
        ),
    ],
    SessionMode.LOCKED: [
        SpeakerInput(
            speaker_id="speaker-02",
            display_name="Mina",
            language_code="ko-KR",
            priority=0.58,
            active=True,
            is_locked=True,
            last_updated_unix_ms=1712745001200,
        ),
        SpeakerInput(
            speaker_id="speaker-01",
            display_name="Alex",
            language_code="en-US",
            priority=0.74,
            active=True,
            is_locked=False,
            last_updated_unix_ms=1712745001000,
        ),
        SpeakerInput(
            speaker_id="speaker-03",
            display_name="Luis",
            language_code="es-ES",
            priority=0.49,
            active=False,
            is_locked=False,
            last_updated_unix_ms=1712744999000,
        ),
        SpeakerInput(
            speaker_id="speaker-04",
            display_name="Nora",
            language_code="fr-FR",
            priority=0.44,
            active=False,
            is_locked=False,
            last_updated_unix_ms=1712744997000,
        ),
    ],
}


class SessionStore:
    def __init__(self, prioritizer: SpeakerPrioritizer | None = None) -> None:
        self._prioritizer = prioritizer or SpeakerPrioritizer()
        self._mode = SessionMode.FOCUS
        self._session_id = _DEFAULT_SESSION_ID
        self._source = "mock"
        self._speakers = self._prioritizer.rank(self._scene(self._mode), self._mode)

    def get_session(self) -> SessionResponse:
        top_speaker_id = self._speakers[0].speaker_id if self._speakers else None
        return SessionResponse(
            session_id=self._session_id,
            mode=self._mode,
            top_speaker_id=top_speaker_id,
            speaker_count=len(self._speakers),
            speakers=self._speakers,
        )

    def get_speakers(self) -> SpeakersResponse:
        session = self.get_session()
        return SpeakersResponse(
            count=session.speaker_count,
            top_speaker_id=session.top_speaker_id,
            speakers=session.speakers,
        )

    def reset(self) -> SessionResponse:
        self._mode = SessionMode.FOCUS
        self._source = "mock"
        self._speakers = self._prioritizer.rank(self._scene(self._mode), self._mode)
        return self.get_session()

    def apply_speakers(
        self,
        speakers: Iterable[SpeakerInput],
        mode: SessionMode | None = None,
    ) -> SessionResponse:
        if mode is not None:
            self._mode = mode

        self._source = "custom"
        self._speakers = self._prioritizer.rank(list(speakers), self._mode)
        return self.get_session()

    def load_mock_scene(self, mode: SessionMode) -> MockSceneResponse:
        self._mode = mode
        self._source = "mock"
        self._speakers = self._prioritizer.rank(self._scene(mode), mode)
        return MockSceneResponse(scene_id=f"{mode.value.lower()}-scene", source=self._source, session=self.get_session())

    def _scene(self, mode: SessionMode) -> list[SpeakerInput]:
        return deepcopy(_MOCK_SCENES[mode])
