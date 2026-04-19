from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SessionMode(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    FOCUS = "FOCUS"
    CROWD = "CROWD"
    LOCKED = "LOCKED"


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


class MockSceneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionResponse
    supported_modes: list[SessionMode]
