from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.models import (
    DiarizationPredictionInput,
    DiarizationSegmentInput,
    LaneStatus,
    SessionMode,
    SessionResponse,
    SpeakerState,
)
from app.services.session_store import SessionStore


_DEFAULT_LANGUAGE_CODE = "und"
_DEFAULT_ACTIVE_HANGOVER_S = 0.75


@dataclass(frozen=True)
class DiarizationImportPolicy:
    """Policy for mapping diarization output into the gateway's speaker lanes."""

    active_hangover_s: float = _DEFAULT_ACTIVE_HANGOVER_S
    base_timestamp_unix_ms: int = 0
    language_code: str = _DEFAULT_LANGUAGE_CODE


@dataclass(frozen=True)
class _SpeakerSummary:
    speaker_id: str
    first_start_s: float
    last_end_s: float
    total_speech_s: float
    segment_count: int
    average_confidence: float


def speaker_states_from_diarization(
    prediction: DiarizationPredictionInput,
    *,
    observed_end_s: float | None = None,
    policy: DiarizationImportPolicy | None = None,
) -> list[SpeakerState]:
    """Convert a diarization prediction record into gateway speaker lanes.

    This is intentionally a metadata bridge only. Diarization does not provide language ID, ASR,
    translation, voice cloning, or suppression output; those fields stay empty until downstream
    adapters fill them.
    """

    import_policy = policy or DiarizationImportPolicy()
    if observed_end_s is None:
        observed_end_s = max((segment.end_s for segment in prediction.segments), default=0.0)
    if observed_end_s < 0.0:
        raise ValueError("observed_end_s must be greater than or equal to zero")

    visible_segments = _segments_visible_by(prediction.segments, observed_end_s)
    summaries = _speaker_summaries(visible_segments)
    overlap_lookup = _speaker_overlap_lookup(visible_segments)
    ordered = sorted(summaries.values(), key=lambda item: (item.first_start_s, item.speaker_id))

    states: list[SpeakerState] = []
    for index, summary in enumerate(ordered, start=1):
        seconds_since_last_heard = max(0.0, observed_end_s - summary.last_end_s)
        active = seconds_since_last_heard <= import_policy.active_hangover_s
        priority = _speaker_priority(summary, active, seconds_since_last_heard)
        states.append(
            SpeakerState(
                speaker_id=summary.speaker_id,
                display_name=f"Diarized speaker {index}",
                language_code=import_policy.language_code,
                priority=priority,
                active=active,
                is_locked=False,
                front_facing=False,
                persistence_bonus=0.0,
                last_updated_unix_ms=(
                    import_policy.base_timestamp_unix_ms + int(round(summary.last_end_s * 1000.0))
                ),
                lane_status=LaneStatus.LISTENING if active else LaneStatus.IDLE,
                status_message=_status_message(prediction.adapter_id, summary, active),
                overlapping_speaker_ids=sorted(overlap_lookup.get(summary.speaker_id, set())),
            )
        )
    return states


def apply_diarization_prediction(
    prediction: DiarizationPredictionInput,
    store: SessionStore,
    *,
    mode: SessionMode | None = None,
    observed_end_s: float | None = None,
) -> SessionResponse:
    speakers = speaker_states_from_diarization(prediction, observed_end_s=observed_end_s)
    return store.replace_speakers(speakers, mode=mode)


def _segments_visible_by(
    segments: Iterable[DiarizationSegmentInput],
    observed_end_s: float,
) -> list[DiarizationSegmentInput]:
    visible: list[DiarizationSegmentInput] = []
    for segment in segments:
        if segment.start_s >= observed_end_s:
            continue
        if segment.end_s <= 0.0:
            continue
        clipped_end_s = min(segment.end_s, observed_end_s)
        if clipped_end_s <= segment.start_s:
            continue
        visible.append(
            segment.model_copy(
                update={
                    "end_s": clipped_end_s,
                }
            )
        )
    return sorted(visible, key=lambda item: (item.start_s, item.end_s, item.label))


def _speaker_summaries(segments: Iterable[DiarizationSegmentInput]) -> dict[str, _SpeakerSummary]:
    grouped: dict[str, list[DiarizationSegmentInput]] = {}
    for segment in segments:
        grouped.setdefault(segment.label, []).append(segment)

    summaries: dict[str, _SpeakerSummary] = {}
    for speaker_id, speaker_segments in grouped.items():
        total_speech_s = sum(segment.end_s - segment.start_s for segment in speaker_segments)
        confidence_sum = sum(segment.confidence for segment in speaker_segments)
        summaries[speaker_id] = _SpeakerSummary(
            speaker_id=speaker_id,
            first_start_s=min(segment.start_s for segment in speaker_segments),
            last_end_s=max(segment.end_s for segment in speaker_segments),
            total_speech_s=total_speech_s,
            segment_count=len(speaker_segments),
            average_confidence=confidence_sum / len(speaker_segments),
        )
    return summaries


def _speaker_overlap_lookup(
    segments: list[DiarizationSegmentInput],
) -> dict[str, set[str]]:
    overlaps: dict[str, set[str]] = {}
    for index, left in enumerate(segments):
        for right in segments[index + 1 :]:
            if left.label == right.label:
                continue
            if left.start_s < right.end_s and right.start_s < left.end_s:
                overlaps.setdefault(left.label, set()).add(right.label)
                overlaps.setdefault(right.label, set()).add(left.label)
    return overlaps


def _speaker_priority(
    summary: _SpeakerSummary,
    active: bool,
    seconds_since_last_heard: float,
) -> float:
    active_bonus = 2.0 if active else 0.0
    recency_penalty = min(seconds_since_last_heard, 10.0) * 0.05
    confidence_bonus = summary.average_confidence * 0.25
    return round(summary.total_speech_s + active_bonus + confidence_bonus - recency_penalty, 3)


def _status_message(
    adapter_id: str,
    summary: _SpeakerSummary,
    active: bool,
) -> str:
    state = "listening" if active else f"last heard at {summary.last_end_s:.2f}s"
    return (
        f"Diarization {adapter_id}: {state}; "
        f"{summary.segment_count} segment(s), {summary.total_speech_s:.2f}s observed."
    )
