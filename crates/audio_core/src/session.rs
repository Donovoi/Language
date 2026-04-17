use crate::{SessionId, SpeakerState};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionMode {
    Unspecified,
    Focus,
    Crowd,
    Locked,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SessionState {
    pub session_id: SessionId,
    pub mode: SessionMode,
    pub speakers: Vec<SpeakerState>,
}

impl SessionState {
    pub fn new(session_id: SessionId, mode: SessionMode, speakers: Vec<SpeakerState>) -> Self {
        Self {
            session_id,
            mode,
            speakers,
        }
    }

    pub fn top_speaker(&self) -> Option<&SpeakerState> {
        self.speakers.iter().max_by(|left, right| {
            left.effective_priority()
                .total_cmp(&right.effective_priority())
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{SessionMode, SessionState};
    use crate::{LanguageCode, PriorityScore, SessionId, SpeakerId, SpeakerState};

    #[test]
    fn returns_top_speaker_by_effective_priority() {
        let session = SessionState::new(
            SessionId::new("session-1").expect("session id"),
            SessionMode::Focus,
            vec![
                SpeakerState::new(
                    SpeakerId::new("speaker-1").expect("speaker id"),
                    "Alice",
                    LanguageCode::new("en").expect("language code"),
                    PriorityScore::new(0.8).expect("priority"),
                    true,
                    false,
                    true,
                    0.0,
                    0,
                )
                .expect("valid speaker"),
                SpeakerState::new(
                    SpeakerId::new("speaker-2").expect("speaker id"),
                    "Bao",
                    LanguageCode::new("zh").expect("language code"),
                    PriorityScore::new(0.7).expect("priority"),
                    true,
                    false,
                    false,
                    0.2,
                    0,
                )
                .expect("valid speaker"),
            ],
        );

        assert_eq!(
            session
                .top_speaker()
                .expect("top speaker")
                .speaker_id
                .as_str(),
            "speaker-2",
        );
    }
}
