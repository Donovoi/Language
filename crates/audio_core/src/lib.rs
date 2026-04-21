//! Shared low-latency domain primitives for the Language project.
//!
//! The crate provides validated identifiers, speaker/session state, and
//! lightweight priority primitives that higher-level policy crates can reuse
//! without depending on transport or UI concerns.

mod ids;
mod priority;
mod session;
mod speaker;

pub use ids::{LanguageCode, SessionId, SpeakerId, ValidationError};
pub use priority::PriorityScore;
pub use session::{SessionMode, SessionState};
pub use speaker::SpeakerState;
