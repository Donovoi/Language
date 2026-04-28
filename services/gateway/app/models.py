from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# Contract-lock manifests for CI. Keep these aligned with `proto/session.proto`
# and the Flutter models until multi-language codegen is worth landing.
CONTRACT_LOCKED_PROTO_ENUMS = {
    "SessionMode": {
        "proto_enum": "SessionMode",
        "members": {
            "UNSPECIFIED": {
                "proto": "SESSION_MODE_UNSPECIFIED",
                "api": "UNSPECIFIED",
            },
            "FOCUS": {
                "proto": "SESSION_MODE_FOCUS",
                "api": "FOCUS",
            },
            "CROWD": {
                "proto": "SESSION_MODE_CROWD",
                "api": "CROWD",
            },
            "LOCKED": {
                "proto": "SESSION_MODE_LOCKED",
                "api": "LOCKED",
            },
        },
    },
    "LaneStatus": {
        "proto_enum": "LaneStatus",
        "members": {
            "UNSPECIFIED": {
                "proto": "LANE_STATUS_UNSPECIFIED",
                "api": "UNSPECIFIED",
            },
            "IDLE": {
                "proto": "LANE_STATUS_IDLE",
                "api": "IDLE",
            },
            "LISTENING": {
                "proto": "LANE_STATUS_LISTENING",
                "api": "LISTENING",
            },
            "TRANSLATING": {
                "proto": "LANE_STATUS_TRANSLATING",
                "api": "TRANSLATING",
            },
            "READY": {
                "proto": "LANE_STATUS_READY",
                "api": "READY",
            },
            "ERROR": {
                "proto": "LANE_STATUS_ERROR",
                "api": "ERROR",
            },
        },
    },
    "StreamEventType": {
        "proto_enum": "StreamEventType",
        "members": {
            "UNSPECIFIED": {
                "proto": "STREAM_EVENT_TYPE_UNSPECIFIED",
                "api": "unknown",
            },
            "SESSION_SNAPSHOT": {
                "proto": "STREAM_EVENT_TYPE_SESSION_SNAPSHOT",
                "api": "session.snapshot",
            },
            "SPEAKER_UPDATE": {
                "proto": "STREAM_EVENT_TYPE_SPEAKER_UPDATE",
                "api": "speaker.update",
            },
        },
    },
}

CONTRACT_LOCKED_PROTO_MODELS = {
    "SpeakerState": {
        "proto_message": "SpeakerState",
        "fields": (
            "speaker_id",
            "display_name",
            "language_code",
            "priority",
            "active",
            "is_locked",
            "front_facing",
            "persistence_bonus",
            "last_updated_unix_ms",
            "source_caption",
            "translated_caption",
            "target_language_code",
            "lane_status",
            "status_message",
        ),
    },
    "SessionResponse": {
        "proto_message": "SessionState",
        "fields": (
            "session_id",
            "mode",
            "speakers",
            "top_speaker_id",
        ),
    },
    "SpeakerEventResponse": {
        "proto_message": "SpeakerEvent",
        "fields": (
            "speaker_id",
            "priority_delta",
            "active",
            "is_locked",
            "observed_unix_ms",
            "source_caption",
            "translated_caption",
            "target_language_code",
            "lane_status",
            "status_message",
        ),
    },
    "SessionStreamEvent": {
        "proto_message": "SessionStreamEvent",
        "fields": (
            "event",
            "session",
            "speaker_event",
        ),
    },
}


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
    UNSPECIFIED = "unknown"
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
