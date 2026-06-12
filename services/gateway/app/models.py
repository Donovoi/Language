from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.generated.session_contract import (
    LaneStatus,
    SessionMode,
    SourceSuppressionMode,
    StreamEventType,
)


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
    input_level_dbfs: float | None = None
    output_level_dbfs: float | None = None
    overlapping_speaker_ids: list[str] = Field(default_factory=list)
    detected_language_code: str | None = Field(default=None, min_length=2)
    language_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    voice_clone_id: str | None = None
    voice_clone_status: str | None = None
    translated_audio_stream_id: str | None = None
    original_voice_suppression_db: float | None = Field(default=None, ge=0.0)
    playback_latency_ms: int | None = Field(default=None, ge=0)
    source_suppression_mode: SourceSuppressionMode | None = None

    @model_validator(mode="after")
    def validate_suppression_claim(self) -> SpeakerState:
        _validate_suppression_claim(
            amount_db=self.original_voice_suppression_db,
            mode=self.source_suppression_mode,
        )
        return self


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
    input_level_dbfs: float | None = None
    output_level_dbfs: float | None = None
    overlapping_speaker_ids: list[str] = Field(default_factory=list)
    detected_language_code: str | None = Field(default=None, min_length=2)
    language_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    voice_clone_id: str | None = None
    voice_clone_status: str | None = None
    translated_audio_stream_id: str | None = None
    original_voice_suppression_db: float | None = Field(default=None, ge=0.0)
    playback_latency_ms: int | None = Field(default=None, ge=0)
    source_suppression_mode: SourceSuppressionMode | None = None

    @model_validator(mode="after")
    def validate_suppression_claim(self) -> SpeakerEventResponse:
        _validate_suppression_claim(
            amount_db=self.original_voice_suppression_db,
            mode=self.source_suppression_mode,
        )
        return self


def _validate_suppression_claim(
    *,
    amount_db: float | None,
    mode: SourceSuppressionMode | None,
) -> None:
    if amount_db is not None and amount_db > 0 and mode in (
        None,
        SourceSuppressionMode.UNSPECIFIED,
        SourceSuppressionMode.UNAVAILABLE,
    ):
        raise ValueError(
            "positive original_voice_suppression_db requires an explicit "
            "source_suppression_mode claim boundary"
        )


class SessionStreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: StreamEventType
    session: SessionResponse | None = None
    speaker_event: SpeakerEventResponse | None = None


class DiarizationSegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_id: str | None = Field(default=None, min_length=1)
    speaker_label: str | None = Field(default=None, min_length=1)
    start_s: float = Field(ge=0.0)
    end_s: float = Field(gt=0.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_segment(self) -> DiarizationSegmentInput:
        if self.speaker_id is None and self.speaker_label is None:
            raise ValueError("diarization segment must include speaker_id or speaker_label")
        if self.end_s <= self.start_s:
            raise ValueError("diarization segment end_s must be greater than start_s")
        return self

    @property
    def label(self) -> str:
        return self.speaker_id or self.speaker_label or ""


class DiarizationPredictionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    fixture_id: str | None = None
    adapter_id: str = Field(min_length=1)
    segments: list[DiarizationSegmentInput] = Field(default_factory=list)
    model_layer_latency_ms: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_schema_version(self) -> DiarizationPredictionInput:
        if self.schema_version != 1:
            raise ValueError(f"unsupported diarization prediction schema_version {self.schema_version}")
        return self


class MockSceneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionResponse
    supported_modes: list[SessionMode]
