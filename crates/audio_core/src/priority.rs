use crate::ids::ValidationError;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PriorityScore(f32);

impl PriorityScore {
    pub fn new(value: f32) -> Result<Self, ValidationError> {
        if !value.is_finite() {
            return Err(ValidationError::NonFinitePriority);
        }
        Ok(Self(value))
    }

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
