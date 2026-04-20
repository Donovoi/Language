use crate::{SessionId, SpeakerState};

/// Describes how a session should interpret speaker-selection policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionMode {
    /// No explicit policy has been chosen yet.
    Unspecified,
    /// Optimize for a single primary speaker.
    Focus,
    /// Allow a wider set of speakers to remain relevant.
    Crowd,
    /// Keep the current speaker choice fixed until unlocked.
    Locked,
}

/// Immutable snapshot of session-level speaker state.
#[derive(Debug, Clone, PartialEq)]
pub struct SessionState {
    /// Unique session identifier.
    pub session_id: SessionId,
    /// Current policy mode for the session.
    pub mode: SessionMode,
    /// Known speakers that belong to the session snapshot.
    pub speakers: Vec<SpeakerState>,
}

impl SessionState {
    /// Creates a new session snapshot.
    pub fn new(session_id: SessionId, mode: SessionMode, speakers: Vec<SpeakerState>) -> Self {
        Self {
            session_id,
            mode,
            speakers,
        }
    }

    /// Returns the speaker with the highest effective priority.
    ///
    /// # Examples
    ///
    /// ```
    /// use audio_core::{
    ///     LanguageCode, PriorityScore, SessionId, SessionMode, SessionState, SpeakerId,
    ///     SpeakerState,
    /// };
    ///
    /// let session = SessionState::new(
    ///     SessionId::new("session-1").unwrap(),
    ///     SessionMode::Focus,
    ///     vec![
    ///         SpeakerState::new(
    ///             SpeakerId::new("speaker-a").unwrap(),
    ///             "Alice",
    ///             LanguageCode::new("en").unwrap(),
    ///             PriorityScore::new(0.6).unwrap(),
    ///             true,
    ///             false,
    ///             true,
    ///             0.1,
    ///             0,
    ///         )
    ///         .unwrap(),
    ///         SpeakerState::new(
    ///             SpeakerId::new("speaker-b").unwrap(),
    ///             "Bao",
    ///             LanguageCode::new("zh").unwrap(),
    ///             PriorityScore::new(0.5).unwrap(),
    ///             true,
    ///             false,
    ///             false,
    ///             0.3,
    ///             0,
    ///         )
    ///         .unwrap(),
    ///     ],
    /// );
    ///
    /// assert_eq!(session.top_speaker().unwrap().speaker_id.as_str(), "speaker-b");
    /// ```
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
