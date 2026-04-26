from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SessionMode(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    FOCUS = "FOCUS"
    CROWD = "CROWD"
    LOCKED = "LOCKED"


class LaneStatus(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    TRANSLATING = "TRANSLATING"
    READY = "READY"
    ERROR = "ERROR"


class StreamEventType(str, Enum):
    SESSION_SNAPSHOT = "session.snapshot"
    SPEAKER_UPDATE = "speaker.update"


class SpeakerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    language_code: str = Field(min_length=2)
    priority: float
    active: bool
    is_locked: bool = False
    front_facing: bool = False
    persistence_bonus: float = 0.0
    last_updated_unix_ms: int = Field(ge=0)
    source_caption: str | None = None
    translated_caption: str | None = None
    target_language_code: str | None = Field(default=None, min_length=2)
    lane_status: LaneStatus = LaneStatus.UNSPECIFIED
    status_message: str | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    mode: SessionMode
    speakers: list[SpeakerState]
    top_speaker_id: str | None = None


class SessionResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: bool
    session: SessionResponse


class SpeakerEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_id: str = Field(min_length=1)
    priority_delta: float
    active: bool
    is_locked: bool = False
    observed_unix_ms: int = Field(ge=0)
    source_caption: str | None = None
    translated_caption: str | None = None
    target_language_code: str | None = Field(default=None, min_length=2)
    lane_status: LaneStatus = LaneStatus.UNSPECIFIED
    status_message: str | None = None


class SessionStreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: StreamEventType
    session: SessionResponse | None = None
    speaker_event: SpeakerEventResponse | None = None


class MockSceneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionResponse
    supported_modes: list[SessionMode]
