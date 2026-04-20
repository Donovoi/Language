/// Validation failures returned by typed `audio_core` constructors.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValidationError {
    /// A required string field was empty or contained only whitespace.
    EmptyField(&'static str),
    /// A language code did not match the crate's normalized `xx` or `xx-yy` form.
    InvalidLanguageCode(String),
    /// A floating-point priority score was NaN or infinite.
    NonFinitePriority,
    /// A persistence bonus was negative or not finite.
    NegativePersistenceBonus,
}

/// Stable identifier for a realtime audio session.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SessionId(String);

impl SessionId {
    /// Creates a validated session identifier.
    pub fn new(value: impl Into<String>) -> Result<Self, ValidationError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ValidationError::EmptyField("session_id"));
        }
        Ok(Self(value))
    }

    /// Returns the original identifier as a string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Stable identifier for a speaker within a session.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SpeakerId(String);

impl SpeakerId {
    /// Creates a validated speaker identifier.
    pub fn new(value: impl Into<String>) -> Result<Self, ValidationError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ValidationError::EmptyField("speaker_id"));
        }
        Ok(Self(value))
    }

    /// Returns the original identifier as a string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Normalized BCP-47-style language code used by speaker state.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct LanguageCode(String);

impl LanguageCode {
    /// Parses and normalizes a language code to lowercase ASCII.
    ///
    /// # Examples
    ///
    /// ```
    /// use audio_core::LanguageCode;
    ///
    /// let code = LanguageCode::new("EN-us").unwrap();
    /// assert_eq!(code.as_str(), "en-us");
    /// ```
    pub fn new(value: impl Into<String>) -> Result<Self, ValidationError> {
        let normalized = value.into().trim().to_ascii_lowercase();
        let mut segments = normalized.split('-');
        let primary = segments.next().unwrap_or_default();
        let region = segments.next();
        let is_valid = !normalized.is_empty()
            && segments.next().is_none()
            && primary.len() >= 2
            && primary.len() <= 3
            && primary
                .chars()
                .all(|character| character.is_ascii_alphabetic())
            && region.is_none_or(|segment| {
                (2..=4).contains(&segment.len())
                    && segment
                        .chars()
                        .all(|character| character.is_ascii_alphabetic())
            });

        if !is_valid {
            return Err(ValidationError::InvalidLanguageCode(normalized));
        }

        Ok(Self(normalized))
    }

    /// Returns the normalized language code.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[cfg(test)]
mod tests {
    use super::{LanguageCode, SessionId, SpeakerId, ValidationError};

    #[test]
    fn rejects_blank_ids() {
        assert_eq!(
            SessionId::new(" "),
            Err(ValidationError::EmptyField("session_id"))
        );
        assert_eq!(
            SpeakerId::new(""),
            Err(ValidationError::EmptyField("speaker_id"))
        );
    }

    #[test]
    fn normalizes_language_codes() {
        let code = LanguageCode::new("EN-us").expect("language code should be valid");
        assert_eq!(code.as_str(), "en-us");
    }

    #[test]
    fn rejects_invalid_language_codes() {
        assert_eq!(
            LanguageCode::new("english"),
            Err(ValidationError::InvalidLanguageCode(String::from(
                "english"
            ))),
        );
        assert_eq!(
            LanguageCode::new("en_au"),
            Err(ValidationError::InvalidLanguageCode(String::from("en_au"))),
        );
    }
}
