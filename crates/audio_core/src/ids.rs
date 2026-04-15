use crate::{validate_non_empty, ValidationError, ValidationResult};

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SessionId(String);

impl SessionId {
    pub fn new(value: impl Into<String>) -> ValidationResult<Self> {
        let value = value.into();
        validate_non_empty("session_id", &value)?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SpeakerId(String);

impl SpeakerId {
    pub fn new(value: impl Into<String>) -> ValidationResult<Self> {
        let value = value.into();
        validate_non_empty("speaker_id", &value)?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct LanguageCode(String);

impl LanguageCode {
    pub fn new(value: impl Into<String>) -> ValidationResult<Self> {
        let value = value.into();
        validate_non_empty("language_code", &value)?;

        let is_valid = value
            .chars()
            .all(|character| character.is_ascii_alphabetic() || character == '-');

        if !is_valid {
            return Err(ValidationError::new(
                "language_code",
                "must contain only ASCII letters or hyphens",
            ));
        }

        if value.len() < 2 || value.len() > 15 {
            return Err(ValidationError::new(
                "language_code",
                "must be between 2 and 15 characters",
            ));
        }

        Ok(Self(value.to_ascii_lowercase()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_session_ids() {
        let error = SessionId::new(" ").expect_err("session id should fail");
        assert_eq!(error.field(), "session_id");
    }

    #[test]
    fn normalizes_language_codes() {
        let code = LanguageCode::new("EN-US").expect("language code should be valid");
        assert_eq!(code.as_str(), "en-us");
    }

    #[test]
    fn rejects_invalid_language_code_characters() {
        let error = LanguageCode::new("en_US").expect_err("language code should fail");
        assert_eq!(error.field(), "language_code");
    }
}
