from enum import Enum

from pydantic import BaseModel, Field


class SessionMode(str, Enum):
    FOCUS = "FOCUS"
    CROWD = "CROWD"
    LOCKED = "LOCKED"


class SpeakerInput(BaseModel):
    speaker_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    language_code: str = Field(min_length=2)
    priority: float = Field(ge=0.0)
    active: bool
    is_locked: bool = False
    last_updated_unix_ms: int = Field(ge=0)


class SpeakersRequest(BaseModel):
    speakers: list[SpeakerInput]
    mode: SessionMode | None = None


class SpeakerState(BaseModel):
    speaker_id: str
    display_name: str
    language_code: str
    priority: float
    active: bool
    is_locked: bool
    last_updated_unix_ms: int


class SpeakersResponse(BaseModel):
    count: int
    top_speaker_id: str | None
    speakers: list[SpeakerState]


class SessionResponse(BaseModel):
    session_id: str
    mode: SessionMode
    top_speaker_id: str | None
    speaker_count: int
    speakers: list[SpeakerState]


class MockSceneResponse(BaseModel):
    scene_id: str
    source: str
    session: SessionResponse
