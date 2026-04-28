from __future__ import annotations

import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
import tempfile
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
from app.services.session_persistence import SQLiteSessionPersistence


_SUBSCRIPTION_QUEUE_SIZE = 64
_SESSION_DB_PATH_ENV = "LANGUAGE_GATEWAY_SESSION_DB_PATH"
_SESSION_DB_DIRECTORY = ".state"
_SESSION_DB_FILENAME = "session-store.sqlite3"


@dataclass(slots=True, frozen=True)
class QueuedSessionStreamEvent:
    event_id: int
    event: SessionStreamEvent


@dataclass(slots=True)
class _Subscription:
    queue: Queue[QueuedSessionStreamEvent]
    mode: SessionMode | None = None


def _default_database_path() -> Path:
    configured_path = os.getenv(_SESSION_DB_PATH_ENV)
    if configured_path and configured_path.strip():
        return Path(configured_path.strip()).expanduser()

    current_test = os.getenv("PYTEST_CURRENT_TEST")
    if current_test:
        digest = hashlib.sha1(current_test.encode("utf-8")).hexdigest()[:16]
        return Path(tempfile.gettempdir()) / f"language-gateway-tests-{os.getpid()}" / f"{digest}.sqlite3"

    return Path(__file__).resolve().parents[2] / _SESSION_DB_DIRECTORY / _SESSION_DB_FILENAME


class SessionStore:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self._lock = Lock()
        self._persistence = SQLiteSessionPersistence(database_path or _default_database_path())
        self._session = self._load_initial_session()
        self._subscriptions: list[_Subscription] = []
        self._last_event_id = 0

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
    ) -> tuple[Queue[QueuedSessionStreamEvent], SessionResponse, int]:
        with self._lock:
            queue: Queue[QueuedSessionStreamEvent] = Queue(maxsize=_SUBSCRIPTION_QUEUE_SIZE)
            self._subscriptions.append(_Subscription(queue=queue, mode=mode))
            return queue, self._session_for_mode_locked(mode), self._last_event_id

    def unsubscribe(self, queue: Queue[QueuedSessionStreamEvent]) -> None:
        with self._lock:
            self._subscriptions = [
                subscription
                for subscription in self._subscriptions
                if subscription.queue is not queue
            ]

    def reset(self, mode: SessionMode = SessionMode.FOCUS) -> SessionResponse:
        with self._lock:
            return self._commit_session_locked(build_mock_scene(mode).session)

    def set_mode(self, mode: SessionMode) -> SessionResponse:
        with self._lock:
            session = SessionResponse.model_validate(
                build_session(self._session.session_id, mode, self._session.speakers)
            )
            return self._commit_session_locked(session)

    def replace_speakers(
        self,
        speakers: list[SpeakerState],
        mode: SessionMode | None = None,
    ) -> SessionResponse:
        with self._lock:
            selected_mode = mode or self._session.mode
            session = SessionResponse.model_validate(
                build_session(self._session.session_id, selected_mode, speakers)
            )
            return self._commit_session_locked(session)

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
                                "last_updated_unix_ms": self._next_speaker_timestamp(speaker),
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

            session = SessionResponse.model_validate(
                build_session(
                    self._session.session_id,
                    self._session.mode,
                    updated_speakers,
                )
            )
            return self._commit_session_locked(session, changed_speaker_id=speaker_id)

    def _load_initial_session(self) -> SessionResponse:
        persisted = self._persistence.load()
        if persisted is None:
            session = build_mock_scene(SessionMode.FOCUS).session
            self._persistence.save(session)
            return session

        return SessionResponse.model_validate(
            build_session(persisted.session_id, persisted.mode, persisted.speakers)
        )

    def _commit_session_locked(
        self,
        session: SessionResponse,
        *,
        changed_speaker_id: str | None = None,
    ) -> SessionResponse:
        self._persistence.save(session)
        self._session = session
        response = session.model_copy(deep=True)
        self._broadcast_locked(changed_speaker_id=changed_speaker_id)
        return response

    def _broadcast_locked(self, changed_speaker_id: str | None = None) -> None:
        base_session = self._session.model_copy(deep=True)
        snapshot_event_id = self._next_event_id_locked()
        speaker_event_id = self._next_event_id_locked() if changed_speaker_id is not None else None

        for subscription in self._subscriptions:
            session = self._session_for_mode_locked(subscription.mode, session=base_session)
            self._push_event(
                subscription.queue,
                QueuedSessionStreamEvent(
                    event_id=snapshot_event_id,
                    event=SessionStreamEvent(
                        event=StreamEventType.SESSION_SNAPSHOT,
                        session=session,
                    ),
                ),
            )

            if changed_speaker_id is None:
                continue

            speaker_event = self._speaker_event_for_session(session, changed_speaker_id)
            if speaker_event is not None:
                self._push_event(
                    subscription.queue,
                    QueuedSessionStreamEvent(
                        event_id=speaker_event_id,
                        event=SessionStreamEvent(
                            event=StreamEventType.SPEAKER_UPDATE,
                            speaker_event=speaker_event,
                        ),
                    ),
                )

    def _push_event(
        self,
        queue: Queue[QueuedSessionStreamEvent],
        event: QueuedSessionStreamEvent,
    ) -> None:
        try:
            queue.put_nowait(event)
        except Full:
            with suppress(Empty):
                queue.get_nowait()
            with suppress(Full):
                queue.put_nowait(event)

    def _next_event_id_locked(self) -> int:
        self._last_event_id += 1
        return self._last_event_id

    @staticmethod
    def _next_speaker_timestamp(speaker: SpeakerState) -> int:
        return speaker.last_updated_unix_ms + 1

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
