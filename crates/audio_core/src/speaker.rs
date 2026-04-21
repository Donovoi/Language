use crate::{LanguageCode, PriorityScore, SpeakerId, ValidationError};

/// Speaker attributes consumed by ranking and focus policy.
#[derive(Debug, Clone, PartialEq)]
pub struct SpeakerState {
    /// Stable speaker identifier.
    pub speaker_id: SpeakerId,
    /// Human-readable label for UI and diagnostics.
    pub display_name: String,
    /// Preferred language for the speaker.
    pub language_code: LanguageCode,
    /// Base score supplied by upstream logic.
    pub priority: PriorityScore,
    /// Whether the speaker is currently active.
    pub active: bool,
    /// Whether the user explicitly locked this speaker.
    pub is_locked: bool,
    /// Whether the speaker is front-facing in the capture layout.
    pub front_facing: bool,
    /// Additional carry-over score from recent speaker history.
    pub persistence_bonus: f32,
    /// Timestamp of the last upstream update in Unix milliseconds.
    pub last_updated_unix_ms: u64,
}

impl SpeakerState {
    #[allow(clippy::too_many_arguments)]
    /// Creates a validated speaker snapshot.
    pub fn new(
        speaker_id: SpeakerId,
        display_name: impl Into<String>,
        language_code: LanguageCode,
        priority: PriorityScore,
        active: bool,
        is_locked: bool,
        front_facing: bool,
        persistence_bonus: f32,
        last_updated_unix_ms: u64,
    ) -> Result<Self, ValidationError> {
        let display_name = display_name.into();
        if display_name.trim().is_empty() {
            return Err(ValidationError::EmptyField("display_name"));
        }
        if !persistence_bonus.is_finite() || persistence_bonus < 0.0 {
            return Err(ValidationError::NegativePersistenceBonus);
        }

        Ok(Self {
            speaker_id,
            display_name,
            language_code,
            priority,
            active,
            is_locked,
            front_facing,
            persistence_bonus,
            last_updated_unix_ms,
        })
    }

    /// Returns the base priority plus any persistence bonus.
    pub fn effective_priority(&self) -> f32 {
        self.priority.value() + self.persistence_bonus
    }
}

#[cfg(test)]
mod tests {
    use super::SpeakerState;
    use crate::{LanguageCode, PriorityScore, SpeakerId, ValidationError};

    fn sample_speaker() -> Result<SpeakerState, ValidationError> {
        SpeakerState::new(
            SpeakerId::new("speaker-1")?,
            "Alice",
            LanguageCode::new("en")?,
            PriorityScore::new(0.75)?,
            true,
            false,
            true,
            0.1,
            1_700_000_000_000,
        )
    }

    #[test]
    fn builds_valid_speakers() {
        let speaker = sample_speaker().expect("speaker should be valid");
        assert_eq!(speaker.display_name, "Alice");
        assert_eq!(speaker.language_code.as_str(), "en");
    }

    #[test]
    fn rejects_blank_display_names() {
        let error = SpeakerState::new(
            SpeakerId::new("speaker-1").expect("speaker id"),
            " ",
            LanguageCode::new("en").expect("language code"),
            PriorityScore::new(0.75).expect("priority score"),
            true,
            false,
            true,
            0.1,
            0,
        )
        .expect_err("blank display names should fail");

        assert_eq!(error, ValidationError::EmptyField("display_name"));
    }

    #[test]
    fn rejects_negative_persistence_bonus() {
        let error = SpeakerState::new(
            SpeakerId::new("speaker-1").expect("speaker id"),
            "Alice",
            LanguageCode::new("en").expect("language code"),
            PriorityScore::new(0.75).expect("priority score"),
            true,
            false,
            true,
            -0.1,
            0,
        )
        .expect_err("negative persistence bonus should fail");

        assert_eq!(error, ValidationError::NegativePersistenceBonus);
    }
}
