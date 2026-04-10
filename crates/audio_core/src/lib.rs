//! Shared low-latency domain primitives for the Language project.

#[derive(Debug, Clone, PartialEq)]
pub struct SpeakerFrame {
    pub speaker_id: String,
    pub priority: f32,
    pub active: bool,
}

impl SpeakerFrame {
    pub fn new(speaker_id: impl Into<String>, priority: f32, active: bool) -> Self {
        Self {
            speaker_id: speaker_id.into(),
            priority,
            active,
        }
    }
}
