from __future__ import annotations

from dataclasses import dataclass

from app.models import SessionMode, SpeakerState


@dataclass(frozen=True)
class PriorityWeights:
    active_bonus: float
    inactive_penalty: float
    lock_bonus: float
    front_facing_bonus: float
    persistence_multiplier: float


WEIGHTS_BY_MODE: dict[SessionMode, PriorityWeights] = {
    SessionMode.UNSPECIFIED: PriorityWeights(0.25, 1.0, 0.3, 0.1, 0.5),
    SessionMode.FOCUS: PriorityWeights(0.4, 1.1, 0.45, 0.2, 1.0),
    SessionMode.CROWD: PriorityWeights(0.2, 0.8, 0.2, 0.1, 0.6),
    SessionMode.LOCKED: PriorityWeights(0.3, 1.0, 0.9, 0.15, 0.8),
}


def score_speaker(speaker: SpeakerState, mode: SessionMode) -> float:
    weights = WEIGHTS_BY_MODE[mode]
    score = speaker.priority + (speaker.persistence_bonus * weights.persistence_multiplier)
    score += weights.active_bonus if speaker.active else -weights.inactive_penalty
    if speaker.is_locked:
        score += weights.lock_bonus
    if speaker.front_facing:
        score += weights.front_facing_bonus
    return score


def sort_speakers(speakers: list[SpeakerState], mode: SessionMode) -> list[SpeakerState]:
    return sorted(
        speakers,
        key=lambda speaker: (-score_speaker(speaker, mode), speaker.display_name, speaker.speaker_id),
    )


def build_session(session_id: str, mode: SessionMode, speakers: list[SpeakerState]) -> dict[str, object]:
    ordered = sort_speakers(speakers, mode)
    return {
        "session_id": session_id,
        "mode": mode,
        "speakers": ordered,
        "top_speaker_id": ordered[0].speaker_id if ordered else None,
    }
