#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValidationError {
    EmptyField(&'static str),
    InvalidLanguageCode(String),
    NonFinitePriority,
    NegativePersistenceBonus,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SessionId(String);

impl SessionId {
    pub fn new(value: impl Into<String>) -> Result<Self, ValidationError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ValidationError::EmptyField("session_id"));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SpeakerId(String);

impl SpeakerId {
    pub fn new(value: impl Into<String>) -> Result<Self, ValidationError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ValidationError::EmptyField("speaker_id"));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct LanguageCode(String);

impl LanguageCode {
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
