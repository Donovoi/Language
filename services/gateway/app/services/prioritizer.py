from app.models import SessionMode, SpeakerInput, SpeakerState


class SpeakerPrioritizer:
    """Applies deterministic mode-aware speaker ranking."""

    def rank(self, speakers: list[SpeakerInput], mode: SessionMode) -> list[SpeakerState]:
        ranked = [self._to_state(speaker, mode) for speaker in speakers]
        ranked.sort(
            key=lambda speaker: (
                -speaker.priority,
                not speaker.active,
                not speaker.is_locked,
                speaker.speaker_id,
            )
        )
        return ranked

    def _to_state(self, speaker: SpeakerInput, mode: SessionMode) -> SpeakerState:
        score = speaker.priority

        if speaker.active:
            score += 0.35 if mode is SessionMode.FOCUS else 0.2
        else:
            score = max(0.0, score - (0.25 if mode is SessionMode.FOCUS else 0.1))

        if speaker.is_locked:
            score += 0.8 if mode is SessionMode.LOCKED else 0.35

        if mode is SessionMode.CROWD:
            score += 0.1

        return SpeakerState(
            speaker_id=speaker.speaker_id,
            display_name=speaker.display_name,
            language_code=speaker.language_code.lower(),
            priority=round(score, 3),
            active=speaker.active,
            is_locked=speaker.is_locked,
            last_updated_unix_ms=speaker.last_updated_unix_ms,
        )
