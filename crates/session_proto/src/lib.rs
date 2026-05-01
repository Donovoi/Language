//! Rust transport bindings generated from `proto/session.proto`.
//!
//! This crate keeps protobuf concerns out of `audio_core` while still making the
//! shared session contract usable from Rust code paths.

use std::error::Error;
use std::fmt;

use audio_core::{
    LanguageCode, PriorityScore, SessionId, SessionMode as DomainSessionMode, SessionState,
    SpeakerId, SpeakerState, ValidationError,
};
use focus_engine::rank_speakers_for_mode;

pub mod language {
    pub mod session {
        pub mod v1 {
            #![allow(clippy::derive_partial_eq_without_eq)]
            include!(concat!(env!("OUT_DIR"), "/language.session.v1.rs"));
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtoConversionError {
    InvalidEnumValue { field: &'static str, value: i32 },
    DomainValidation(ValidationError),
}

impl fmt::Display for ProtoConversionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidEnumValue { field, value } => {
                write!(f, "invalid enum value {value} for field {field}")
            }
            Self::DomainValidation(error) => write!(f, "domain validation failed: {error:?}"),
        }
    }
}

impl Error for ProtoConversionError {}

impl From<ValidationError> for ProtoConversionError {
    fn from(value: ValidationError) -> Self {
        Self::DomainValidation(value)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RankedSpeakerOrder {
    pub ordered_speaker_ids: Vec<String>,
    pub top_speaker_id: Option<String>,
}

impl From<DomainSessionMode> for language::session::v1::SessionMode {
    fn from(value: DomainSessionMode) -> Self {
        match value {
            DomainSessionMode::Unspecified => Self::Unspecified,
            DomainSessionMode::Focus => Self::Focus,
            DomainSessionMode::Crowd => Self::Crowd,
            DomainSessionMode::Locked => Self::Locked,
        }
    }
}

impl TryFrom<language::session::v1::SessionMode> for DomainSessionMode {
    type Error = ProtoConversionError;

    fn try_from(value: language::session::v1::SessionMode) -> Result<Self, Self::Error> {
        Ok(match value {
            language::session::v1::SessionMode::Unspecified => Self::Unspecified,
            language::session::v1::SessionMode::Focus => Self::Focus,
            language::session::v1::SessionMode::Crowd => Self::Crowd,
            language::session::v1::SessionMode::Locked => Self::Locked,
        })
    }
}

fn domain_session_mode_from_i32(value: i32) -> Result<DomainSessionMode, ProtoConversionError> {
    let mode = language::session::v1::SessionMode::try_from(value).map_err(|_| {
        ProtoConversionError::InvalidEnumValue {
            field: "mode",
            value,
        }
    })?;
    DomainSessionMode::try_from(mode)
}

impl From<&SpeakerState> for language::session::v1::SpeakerState {
    fn from(value: &SpeakerState) -> Self {
        Self {
            speaker_id: value.speaker_id.as_str().to_string(),
            display_name: value.display_name.clone(),
            language_code: value.language_code.as_str().to_string(),
            priority: value.priority.value(),
            active: value.active,
            is_locked: value.is_locked,
            front_facing: value.front_facing,
            persistence_bonus: value.persistence_bonus,
            last_updated_unix_ms: value.last_updated_unix_ms,
            source_caption: String::new(),
            translated_caption: String::new(),
            target_language_code: String::new(),
            lane_status: language::session::v1::LaneStatus::Unspecified as i32,
            status_message: String::new(),
        }
    }
}

impl TryFrom<language::session::v1::SpeakerState> for SpeakerState {
    type Error = ProtoConversionError;

    fn try_from(value: language::session::v1::SpeakerState) -> Result<Self, Self::Error> {
        Ok(SpeakerState::new(
            SpeakerId::new(value.speaker_id)?,
            value.display_name,
            LanguageCode::new(value.language_code)?,
            PriorityScore::new(value.priority)?,
            value.active,
            value.is_locked,
            value.front_facing,
            value.persistence_bonus,
            value.last_updated_unix_ms,
        )?)
    }
}

impl From<&SessionState> for language::session::v1::SessionState {
    fn from(value: &SessionState) -> Self {
        Self {
            session_id: value.session_id.as_str().to_string(),
            mode: language::session::v1::SessionMode::from(value.mode) as i32,
            speakers: value
                .speakers
                .iter()
                .map(language::session::v1::SpeakerState::from)
                .collect(),
            top_speaker_id: value
                .top_speaker()
                .map(|speaker| speaker.speaker_id.as_str().to_string())
                .unwrap_or_default(),
        }
    }
}

impl TryFrom<language::session::v1::SessionState> for SessionState {
    type Error = ProtoConversionError;

    fn try_from(value: language::session::v1::SessionState) -> Result<Self, Self::Error> {
        let speakers = value
            .speakers
            .into_iter()
            .map(SpeakerState::try_from)
            .collect::<Result<Vec<_>, _>>()?;

        Ok(SessionState::new(
            SessionId::new(value.session_id)?,
            domain_session_mode_from_i32(value.mode)?,
            speakers,
        ))
    }
}

pub fn rank_proto_speakers(
    mode: DomainSessionMode,
    speakers: &[language::session::v1::SpeakerState],
) -> Result<RankedSpeakerOrder, ProtoConversionError> {
    let domain_speakers = speakers
        .iter()
        .cloned()
        .map(SpeakerState::try_from)
        .collect::<Result<Vec<_>, _>>()?;
    let ranked = rank_speakers_for_mode(&domain_speakers, mode);
    let ordered_speaker_ids = ranked
        .iter()
        .map(|speaker| speaker.speaker_id.as_str().to_string())
        .collect::<Vec<_>>();
    let top_speaker_id = ordered_speaker_ids.first().cloned();

    Ok(RankedSpeakerOrder {
        ordered_speaker_ids,
        top_speaker_id,
    })
}

pub fn rank_proto_session(
    session: &language::session::v1::SessionState,
) -> Result<RankedSpeakerOrder, ProtoConversionError> {
    let mode = domain_session_mode_from_i32(session.mode)?;
    rank_proto_speakers(mode, &session.speakers)
}

#[cfg(test)]
mod tests {
    use super::{
        domain_session_mode_from_i32, language::session::v1, rank_proto_session, DomainSessionMode,
        ProtoConversionError, SessionState, SpeakerState,
    };
    use audio_core::{LanguageCode, PriorityScore, SessionId, SpeakerId};

    fn sample_speaker() -> SpeakerState {
        SpeakerState::new(
            SpeakerId::new("speaker-1").expect("speaker id"),
            "Alice",
            LanguageCode::new("en").expect("language code"),
            PriorityScore::new(0.8).expect("priority"),
            true,
            false,
            true,
            0.1,
            1_700_000_000_000,
        )
        .expect("speaker should be valid")
    }

    #[test]
    fn converts_domain_session_mode_to_proto() {
        assert_eq!(
            v1::SessionMode::from(DomainSessionMode::Locked),
            v1::SessionMode::Locked,
        );
    }

    #[test]
    fn converts_proto_speaker_into_audio_core() {
        let speaker = SpeakerState::try_from(v1::SpeakerState {
            speaker_id: String::from("speaker-1"),
            display_name: String::from("Alice"),
            language_code: String::from("EN-us"),
            priority: 0.8,
            active: true,
            is_locked: false,
            front_facing: true,
            persistence_bonus: 0.1,
            last_updated_unix_ms: 1_700_000_000_000,
            source_caption: String::new(),
            translated_caption: String::new(),
            target_language_code: String::new(),
            lane_status: v1::LaneStatus::Ready as i32,
            status_message: String::new(),
        })
        .expect("speaker conversion should succeed");

        assert_eq!(speaker.language_code.as_str(), "en-us");
        assert_eq!(speaker.speaker_id.as_str(), "speaker-1");
    }

    #[test]
    fn rejects_unknown_session_mode_values() {
        assert_eq!(
            domain_session_mode_from_i32(99),
            Err(ProtoConversionError::InvalidEnumValue {
                field: "mode",
                value: 99,
            }),
        );
    }

    #[test]
    fn converts_domain_session_into_proto() {
        let session = SessionState::new(
            SessionId::new("session-1").expect("session id"),
            DomainSessionMode::Focus,
            vec![sample_speaker()],
        );

        let proto_session = v1::SessionState::from(&session);
        assert_eq!(proto_session.session_id, "session-1");
        assert_eq!(proto_session.mode, v1::SessionMode::Focus as i32);
        assert_eq!(proto_session.speakers.len(), 1);
        assert_eq!(proto_session.top_speaker_id, "speaker-1");
    }

    #[test]
    fn ranks_proto_session_using_focus_engine_authority() {
        let ranked = rank_proto_session(&v1::SessionState {
            session_id: String::from("session-1"),
            mode: v1::SessionMode::Locked as i32,
            speakers: vec![
                v1::SpeakerState {
                    speaker_id: String::from("speaker-a"),
                    display_name: String::from("Alice"),
                    language_code: String::from("en"),
                    priority: 0.6,
                    active: true,
                    is_locked: false,
                    front_facing: false,
                    persistence_bonus: 0.0,
                    last_updated_unix_ms: 1,
                    source_caption: String::new(),
                    translated_caption: String::new(),
                    target_language_code: String::new(),
                    lane_status: v1::LaneStatus::Ready as i32,
                    status_message: String::new(),
                },
                v1::SpeakerState {
                    speaker_id: String::from("speaker-b"),
                    display_name: String::from("Bao"),
                    language_code: String::from("en"),
                    priority: 0.4,
                    active: true,
                    is_locked: true,
                    front_facing: false,
                    persistence_bonus: 0.0,
                    last_updated_unix_ms: 2,
                    source_caption: String::new(),
                    translated_caption: String::new(),
                    target_language_code: String::new(),
                    lane_status: v1::LaneStatus::Ready as i32,
                    status_message: String::new(),
                },
            ],
            top_speaker_id: String::new(),
        })
        .expect("proto ranking should succeed");

        assert_eq!(ranked.top_speaker_id.as_deref(), Some("speaker-b"));
        assert_eq!(ranked.ordered_speaker_ids, vec!["speaker-b", "speaker-a"]);
    }
}
