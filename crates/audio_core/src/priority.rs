use crate::ids::ValidationError;

/// Validated base priority used by focus-selection policy.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PriorityScore(f32);

impl PriorityScore {
    /// Creates a score from any finite floating-point value.
    pub fn new(value: f32) -> Result<Self, ValidationError> {
        if !value.is_finite() {
            return Err(ValidationError::NonFinitePriority);
        }
        Ok(Self(value))
    }

    /// Returns the raw score value.
    pub fn value(self) -> f32 {
        self.0
    }
}

#[cfg(test)]
mod tests {
    use super::PriorityScore;
    use crate::ValidationError;

    #[test]
    fn rejects_non_finite_scores() {
        assert_eq!(
            PriorityScore::new(f32::NAN),
            Err(ValidationError::NonFinitePriority)
        );
    }
}
