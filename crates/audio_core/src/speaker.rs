use crate::{validate_non_empty, LanguageCode, PriorityScore, SpeakerId, ValidationResult};

#[derive(Debug, Clone, PartialEq)]
pub struct SpeakerState {
    speaker_id: SpeakerId,
    display_name: String,
    language_code: LanguageCode,
    priority: PriorityScore,
    active: bool,
    is_locked: bool,
    last_updated_unix_ms: u64,
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
        last_updated_unix_ms: u64,
    ) -> ValidationResult<Self> {
        let display_name = display_name.into();
        validate_non_empty("display_name", &display_name)?;

        Ok(Self {
            speaker_id,
            display_name,
            language_code,
            priority,
            active,
            is_locked,
            last_updated_unix_ms,
        })
    }

    pub fn speaker_id(&self) -> &SpeakerId {
        &self.speaker_id
    }

    pub fn display_name(&self) -> &str {
        &self.display_name
    }

    pub fn language_code(&self) -> &LanguageCode {
        &self.language_code
    }

    pub fn priority(&self) -> PriorityScore {
        self.priority
    }

    pub fn active(&self) -> bool {
        self.active
    }

    pub fn is_locked(&self) -> bool {
        self.is_locked
    }

    pub fn last_updated_unix_ms(&self) -> u64 {
        self.last_updated_unix_ms
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_speaker() -> SpeakerState {
        SpeakerState::new(
            SpeakerId::new("speaker-1").expect("speaker id should be valid"),
            "Alex",
            LanguageCode::new("en-us").expect("language code should be valid"),
            PriorityScore::new(0.8).expect("priority should be valid"),
            true,
            false,
            42,
        )
        .expect("speaker should be valid")
    }

    #[test]
    fn constructs_speaker_state() {
        let speaker = sample_speaker();
        assert_eq!(speaker.display_name(), "Alex");
        assert!(speaker.active());
    }

    #[test]
    fn rejects_blank_display_names() {
        let error = SpeakerState::new(
            SpeakerId::new("speaker-1").expect("speaker id should be valid"),
            " ",
            LanguageCode::new("en").expect("language code should be valid"),
            PriorityScore::new(0.1).expect("priority should be valid"),
            false,
            false,
            0,
        )
        .expect_err("speaker should fail");

        assert_eq!(error.field(), "display_name");
    }
}
