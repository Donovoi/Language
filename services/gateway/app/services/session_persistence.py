from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models import SessionMode, SessionResponse, SourceSuppressionMode, SpeakerState

_CURRENT_STATE_ID = 1
_SPEAKER_COLUMN_MIGRATIONS = {
    "input_level_dbfs": "REAL",
    "output_level_dbfs": "REAL",
    "overlapping_speaker_ids": "TEXT NOT NULL DEFAULT '[]'",
    "detected_language_code": "TEXT",
    "language_confidence": "REAL",
    "voice_clone_id": "TEXT",
    "voice_clone_status": "TEXT",
    "translated_audio_stream_id": "TEXT",
    "original_voice_suppression_db": "REAL",
    "playback_latency_ms": "INTEGER",
    "source_suppression_mode": "TEXT",
}


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
                    status_message,
                    input_level_dbfs,
                    output_level_dbfs,
                    overlapping_speaker_ids,
                    detected_language_code,
                    language_confidence,
                    voice_clone_id,
                    voice_clone_status,
                    translated_audio_stream_id,
                    original_voice_suppression_db,
                    playback_latency_ms,
                    source_suppression_mode
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
                input_level_dbfs=row["input_level_dbfs"],
                output_level_dbfs=row["output_level_dbfs"],
                overlapping_speaker_ids=_decode_speaker_ids(row["overlapping_speaker_ids"]),
                detected_language_code=row["detected_language_code"],
                language_confidence=row["language_confidence"],
                voice_clone_id=row["voice_clone_id"],
                voice_clone_status=row["voice_clone_status"],
                translated_audio_stream_id=row["translated_audio_stream_id"],
                original_voice_suppression_db=row["original_voice_suppression_db"],
                playback_latency_ms=row["playback_latency_ms"],
                source_suppression_mode=_source_suppression_mode_from_row(
                    row["source_suppression_mode"],
                    row["original_voice_suppression_db"],
                ),
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
                    status_message,
                    input_level_dbfs,
                    output_level_dbfs,
                    overlapping_speaker_ids,
                    detected_language_code,
                    language_confidence,
                    voice_clone_id,
                    voice_clone_status,
                    translated_audio_stream_id,
                    original_voice_suppression_db,
                    playback_latency_ms,
                    source_suppression_mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        speaker.input_level_dbfs,
                        speaker.output_level_dbfs,
                        json.dumps(speaker.overlapping_speaker_ids),
                        speaker.detected_language_code,
                        speaker.language_confidence,
                        speaker.voice_clone_id,
                        speaker.voice_clone_status,
                        speaker.translated_audio_stream_id,
                        speaker.original_voice_suppression_db,
                        speaker.playback_latency_ms,
                        (
                            speaker.source_suppression_mode.value
                            if speaker.source_suppression_mode is not None
                            else None
                        ),
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
                    input_level_dbfs REAL,
                    output_level_dbfs REAL,
                    overlapping_speaker_ids TEXT NOT NULL DEFAULT '[]',
                    detected_language_code TEXT,
                    language_confidence REAL,
                    voice_clone_id TEXT,
                    voice_clone_status TEXT,
                    translated_audio_stream_id TEXT,
                    original_voice_suppression_db REAL,
                    playback_latency_ms INTEGER,
                    source_suppression_mode TEXT,
                    PRIMARY KEY (state_id, order_index),
                    FOREIGN KEY (state_id) REFERENCES current_session_state(state_id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_current_speaker_state_columns(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_current_speaker_state_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(current_speaker_state)").fetchall()
        }
        for column_name, definition in _SPEAKER_COLUMN_MIGRATIONS.items():
            if column_name in existing_columns:
                continue
            connection.execute(
                f"ALTER TABLE current_speaker_state ADD COLUMN {column_name} {definition}"
            )


def _decode_speaker_ids(raw_value: str | None) -> list[str]:
    if raw_value is None:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _source_suppression_mode_from_row(
    raw_value: str | None,
    amount_db: float | None,
) -> str | None:
    if raw_value:
        return raw_value
    if amount_db is not None and amount_db > 0:
        return SourceSuppressionMode.OVERLAY_DUCKING.value
    return None
