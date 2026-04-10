//! Shared low-latency domain primitives for the Language project.

mod ids;
mod priority;
mod session;
mod speaker;

pub use ids::{LanguageCode, SessionId, SpeakerId};
pub use priority::PriorityScore;
pub use session::{SessionMode, SessionState};
pub use speaker::SpeakerState;

use std::error::Error;
use std::fmt::{Display, Formatter};

pub type ValidationResult<T> = Result<T, ValidationError>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationError {
    field: &'static str,
    message: String,
}

impl ValidationError {
    pub fn new(field: &'static str, message: impl Into<String>) -> Self {
        Self {
            field,
            message: message.into(),
        }
    }

    pub fn field(&self) -> &'static str {
        self.field
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl Display for ValidationError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.field, self.message)
    }
}

impl Error for ValidationError {}

pub fn validate_non_empty(field: &'static str, value: &str) -> ValidationResult<()> {
    if value.trim().is_empty() {
        return Err(ValidationError::new(field, "must not be empty"));
    }

    Ok(())
}
