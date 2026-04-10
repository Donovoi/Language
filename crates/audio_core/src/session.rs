use crate::{SessionId, SpeakerState};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionMode {
    Focus,
    Crowd,
    Locked,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SessionState {
    session_id: SessionId,
    mode: SessionMode,
    speakers: Vec<SpeakerState>,
}

impl SessionState {
    pub fn new(session_id: SessionId, mode: SessionMode, speakers: Vec<SpeakerState>) -> Self {
        Self {
            session_id,
            mode,
            speakers,
        }
    }

    pub fn session_id(&self) -> &SessionId {
        &self.session_id
    }

    pub fn mode(&self) -> SessionMode {
        self.mode
    }

    pub fn speakers(&self) -> &[SpeakerState] {
        &self.speakers
    }

    pub fn active_speakers(&self) -> impl Iterator<Item = &SpeakerState> {
        self.speakers.iter().filter(|speaker| speaker.active())
    }

    pub fn top_speaker(&self) -> Option<&SpeakerState> {
        self.speakers
            .iter()
            .max_by(|left, right| left.priority().value().total_cmp(&right.priority().value()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{LanguageCode, PriorityScore, SpeakerId};

    fn speaker(id: &str, priority: f32, active: bool) -> SpeakerState {
        SpeakerState::new(
            SpeakerId::new(id).expect("speaker id should be valid"),
            format!("Speaker {id}"),
            LanguageCode::new("en").expect("language code should be valid"),
            PriorityScore::new(priority).expect("priority should be valid"),
            active,
            false,
            10,
        )
        .expect("speaker should be valid")
    }

    #[test]
    fn returns_top_speaker_by_priority() {
        let session = SessionState::new(
            SessionId::new("session-1").expect("session id should be valid"),
            SessionMode::Focus,
            vec![speaker("a", 0.2, true), speaker("b", 0.9, true)],
        );

        assert_eq!(session.top_speaker().map(|speaker| speaker.speaker_id().as_str()), Some("b"));
    }

    #[test]
    fn filters_active_speakers() {
        let session = SessionState::new(
            SessionId::new("session-1").expect("session id should be valid"),
            SessionMode::Crowd,
            vec![speaker("a", 0.2, false), speaker("b", 0.9, true)],
        );

        let active: Vec<&str> = session
            .active_speakers()
            .map(|speaker| speaker.speaker_id().as_str())
            .collect();

        assert_eq!(active, vec!["b"]);
    }
}
