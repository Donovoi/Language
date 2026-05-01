use std::error::Error;
use std::io::{self, Read};

use audio_core::SessionMode as DomainSessionMode;
use serde::{Deserialize, Serialize};
use session_proto::{language::session::v1, rank_proto_session};

#[derive(Debug, Deserialize)]
struct RankRequest {
    mode: String,
    speakers: Vec<RankSpeaker>,
}

#[derive(Debug, Deserialize)]
struct RankSpeaker {
    speaker_id: String,
    display_name: String,
    language_code: String,
    priority: f32,
    active: bool,
    is_locked: bool,
    front_facing: bool,
    persistence_bonus: f32,
    last_updated_unix_ms: u64,
}

#[derive(Debug, Serialize)]
struct RankResponse {
    ordered_speaker_ids: Vec<String>,
    top_speaker_id: Option<String>,
}

fn parse_mode(value: &str) -> Result<DomainSessionMode, String> {
    match value {
        "UNSPECIFIED" | "SESSION_MODE_UNSPECIFIED" => Ok(DomainSessionMode::Unspecified),
        "FOCUS" | "SESSION_MODE_FOCUS" => Ok(DomainSessionMode::Focus),
        "CROWD" | "SESSION_MODE_CROWD" => Ok(DomainSessionMode::Crowd),
        "LOCKED" | "SESSION_MODE_LOCKED" => Ok(DomainSessionMode::Locked),
        _ => Err(format!("unsupported mode: {value}")),
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut stdin = String::new();
    io::stdin().read_to_string(&mut stdin)?;
    let request: RankRequest = serde_json::from_str(&stdin)?;
    let mode = parse_mode(&request.mode)?;
    let session = v1::SessionState {
        session_id: String::from("runtime-prioritizer"),
        mode: v1::SessionMode::from(mode) as i32,
        speakers: request
            .speakers
            .into_iter()
            .map(|speaker| v1::SpeakerState {
                speaker_id: speaker.speaker_id,
                display_name: speaker.display_name,
                language_code: speaker.language_code,
                priority: speaker.priority,
                active: speaker.active,
                is_locked: speaker.is_locked,
                front_facing: speaker.front_facing,
                persistence_bonus: speaker.persistence_bonus,
                last_updated_unix_ms: speaker.last_updated_unix_ms,
                source_caption: String::new(),
                translated_caption: String::new(),
                target_language_code: String::new(),
                lane_status: v1::LaneStatus::LaneStatusUnspecified as i32,
                status_message: String::new(),
            })
            .collect(),
        top_speaker_id: String::new(),
    };

    let ranked = rank_proto_session(&session)?;
    let response = RankResponse {
        ordered_speaker_ids: ranked.ordered_speaker_ids,
        top_speaker_id: ranked.top_speaker_id,
    };
    println!("{}", serde_json::to_string(&response)?);
    Ok(())
}