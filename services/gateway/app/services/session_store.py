from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Lock

from fastapi import Request

from app.models import (
    SessionMode,
    SessionResponse,
    SessionStreamEvent,
    SpeakerEventResponse,
    SpeakerState,
    StreamEventType,
)
from app.services.mock_events import build_mock_scene
from app.services.prioritizer import build_session


@dataclass(slots=True)
class _Subscription:
    queue: Queue[SessionStreamEvent]
    mode: SessionMode | None = None


class SessionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._session = build_mock_scene(SessionMode.FOCUS).session
        self._subscriptions: list[_Subscription] = []

    def current(self) -> SessionResponse:
        with self._lock:
            return self._session.model_copy(deep=True)

    def preview(self, mode: SessionMode) -> SessionResponse:
        with self._lock:
            return SessionResponse.model_validate(
                build_session(self._session.session_id, mode, self._session.speakers)
            )

    def subscribe(
        self,
        mode: SessionMode | None = None,
    ) -> tuple[Queue[SessionStreamEvent], SessionResponse]:
        with self._lock:
            queue: Queue[SessionStreamEvent] = Queue(maxsize=32)
            self._subscriptions.append(_Subscription(queue=queue, mode=mode))
            return queue, self._session_for_mode_locked(mode)

    def unsubscribe(self, queue: Queue[SessionStreamEvent]) -> None:
        with self._lock:
            self._subscriptions = [
                subscription
                for subscription in self._subscriptions
                if subscription.queue is not queue
            ]

    def reset(self, mode: SessionMode = SessionMode.FOCUS) -> SessionResponse:
        with self._lock:
            self._session = build_mock_scene(mode).session
            response = self._session.model_copy(deep=True)
            self._broadcast_locked()
            return response

    def set_mode(self, mode: SessionMode) -> SessionResponse:
        with self._lock:
            self._session = SessionResponse.model_validate(
                build_session(self._session.session_id, mode, self._session.speakers)
            )
            response = self._session.model_copy(deep=True)
            self._broadcast_locked()
            return response

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
            response = self._session.model_copy(deep=True)
            self._broadcast_locked()
            return response

    def set_speaker_lock(self, speaker_id: str, is_locked: bool) -> SessionResponse | None:
        with self._lock:
            updated_speakers: list[SpeakerState] = []
            found = False

            for speaker in self._session.speakers:
                if speaker.speaker_id == speaker_id:
                    found = True
                    updated_speakers.append(
                        speaker.model_copy(
                            update={
                                "is_locked": is_locked,
                                "status_message": (
                                    "Pinned by operator."
                                    if is_locked
                                    else "Lock released."
                                ),
                            }
                        )
                    )
                else:
                    updated_speakers.append(speaker)

            if not found:
                return None

            self._session = SessionResponse.model_validate(
                build_session(
                    self._session.session_id,
                    self._session.mode,
                    updated_speakers,
                )
            )
            response = self._session.model_copy(deep=True)
            self._broadcast_locked(changed_speaker_id=speaker_id)
            return response

    def _broadcast_locked(self, changed_speaker_id: str | None = None) -> None:
        base_session = self._session.model_copy(deep=True)

        for subscription in self._subscriptions:
            session = self._session_for_mode_locked(subscription.mode, session=base_session)
            self._push_event(
                subscription.queue,
                SessionStreamEvent(
                    event=StreamEventType.SESSION_SNAPSHOT,
                    session=session,
                ),
            )

            if changed_speaker_id is None:
                continue

            speaker_event = self._speaker_event_for_session(session, changed_speaker_id)
            if speaker_event is not None:
                self._push_event(
                    subscription.queue,
                    SessionStreamEvent(
                        event=StreamEventType.SPEAKER_UPDATE,
                        speaker_event=speaker_event,
                    ),
                )

    def _push_event(self, queue: Queue[SessionStreamEvent], event: SessionStreamEvent) -> None:
        try:
            queue.put_nowait(event)
        except Full:
            with suppress(Empty):
                queue.get_nowait()
            with suppress(Full):
                queue.put_nowait(event)

    def _session_for_mode_locked(
        self,
        mode: SessionMode | None,
        *,
        session: SessionResponse | None = None,
    ) -> SessionResponse:
        base_session = session or self._session
        if mode is None:
            return base_session.model_copy(deep=True)
        return SessionResponse.model_validate(
            build_session(base_session.session_id, mode, base_session.speakers)
        )

    def _speaker_event_for_session(
        self,
        session: SessionResponse,
        speaker_id: str,
    ) -> SpeakerEventResponse | None:
        for index, speaker in enumerate(session.speakers):
            if speaker.speaker_id != speaker_id:
                continue

            baseline = session.speakers[index + 1].priority if index + 1 < len(session.speakers) else 0.0
            return SpeakerEventResponse(
                speaker_id=speaker.speaker_id,
                priority_delta=round(speaker.priority - baseline, 3),
                active=speaker.active,
                is_locked=speaker.is_locked,
                observed_unix_ms=speaker.last_updated_unix_ms,
                source_caption=speaker.source_caption,
                translated_caption=speaker.translated_caption,
                target_language_code=speaker.target_language_code,
                lane_status=speaker.lane_status,
                status_message=speaker.status_message,
            )

        return None


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store
