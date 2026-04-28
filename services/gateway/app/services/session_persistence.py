from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models import SessionMode, SessionResponse, SpeakerState

_CURRENT_STATE_ID = 1


@dataclass(frozen=True, slots=True)
class PersistedSessionState:
    session_id: str
    mode: SessionMode
    speakers: list[SpeakerState]


class SQLiteSessionPersistence:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser()
        if not self._database_path.is_absolute():
            self._database_path = self._database_path.resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def load(self) -> PersistedSessionState | None:
        with self._connect() as connection:
            session_row = connection.execute(
                """
                SELECT session_id, mode
                FROM current_session_state
                WHERE state_id = ?
                """,
                (_CURRENT_STATE_ID,),
            ).fetchone()

            if session_row is None:
                return None

            speaker_rows = connection.execute(
                """
                SELECT
                    speaker_id,
                    display_name,
                    language_code,
                    priority,
                    active,
                    is_locked,
                    front_facing,
                    persistence_bonus,
                    last_updated_unix_ms,
                    source_caption,
                    translated_caption,
                    target_language_code,
                    lane_status,
                    status_message
                FROM current_speaker_state
                WHERE state_id = ?
                ORDER BY order_index ASC
                """,
                (_CURRENT_STATE_ID,),
            ).fetchall()

        speakers = [
            SpeakerState(
                speaker_id=row["speaker_id"],
                display_name=row["display_name"],
                language_code=row["language_code"],
                priority=row["priority"],
                active=bool(row["active"]),
                is_locked=bool(row["is_locked"]),
                front_facing=bool(row["front_facing"]),
                persistence_bonus=row["persistence_bonus"],
                last_updated_unix_ms=row["last_updated_unix_ms"],
                source_caption=row["source_caption"],
                translated_caption=row["translated_caption"],
                target_language_code=row["target_language_code"],
                lane_status=row["lane_status"],
                status_message=row["status_message"],
            )
            for row in speaker_rows
        ]
        return PersistedSessionState(
            session_id=session_row["session_id"],
            mode=SessionMode(session_row["mode"]),
            speakers=speakers,
        )

    def save(self, session: SessionResponse) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO current_session_state (state_id, session_id, mode)
                VALUES (?, ?, ?)
                ON CONFLICT(state_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    mode = excluded.mode
                """,
                (_CURRENT_STATE_ID, session.session_id, session.mode.value),
            )
            connection.execute(
                "DELETE FROM current_speaker_state WHERE state_id = ?",
                (_CURRENT_STATE_ID,),
            )
            connection.executemany(
                """
                INSERT INTO current_speaker_state (
                    state_id,
                    order_index,
                    speaker_id,
                    display_name,
                    language_code,
                    priority,
                    active,
                    is_locked,
                    front_facing,
                    persistence_bonus,
                    last_updated_unix_ms,
                    source_caption,
                    translated_caption,
                    target_language_code,
                    lane_status,
                    status_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        _CURRENT_STATE_ID,
                        index,
                        speaker.speaker_id,
                        speaker.display_name,
                        speaker.language_code,
                        speaker.priority,
                        int(speaker.active),
                        int(speaker.is_locked),
                        int(speaker.front_facing),
                        speaker.persistence_bonus,
                        speaker.last_updated_unix_ms,
                        speaker.source_caption,
                        speaker.translated_caption,
                        speaker.target_language_code,
                        speaker.lane_status.value,
                        speaker.status_message,
                    )
                    for index, speaker in enumerate(session.speakers)
                ],
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS current_session_state (
                    state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
                    session_id TEXT NOT NULL,
                    mode TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS current_speaker_state (
                    state_id INTEGER NOT NULL,
                    order_index INTEGER NOT NULL,
                    speaker_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    language_code TEXT NOT NULL,
                    priority REAL NOT NULL,
                    active INTEGER NOT NULL,
                    is_locked INTEGER NOT NULL,
                    front_facing INTEGER NOT NULL,
                    persistence_bonus REAL NOT NULL,
                    last_updated_unix_ms INTEGER NOT NULL,
                    source_caption TEXT,
                    translated_caption TEXT,
                    target_language_code TEXT,
                    lane_status TEXT NOT NULL,
                    status_message TEXT,
                    PRIMARY KEY (state_id, order_index),
                    FOREIGN KEY (state_id) REFERENCES current_session_state(state_id) ON DELETE CASCADE
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection