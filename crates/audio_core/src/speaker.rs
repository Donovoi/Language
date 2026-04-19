use crate::{LanguageCode, PriorityScore, SpeakerId, ValidationError};

#[derive(Debug, Clone, PartialEq)]
pub struct SpeakerState {
    pub speaker_id: SpeakerId,
    pub display_name: String,
    pub language_code: LanguageCode,
    pub priority: PriorityScore,
    pub active: bool,
    pub is_locked: bool,
    pub front_facing: bool,
    pub persistence_bonus: f32,
    pub last_updated_unix_ms: u64,
}

impl SpeakerState {
    #[allow(clippy::too_many_arguments)]
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
