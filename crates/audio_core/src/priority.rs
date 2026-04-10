use crate::{ValidationError, ValidationResult};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PriorityScore(f32);

impl PriorityScore {
    pub fn new(value: f32) -> ValidationResult<Self> {
        if !value.is_finite() {
            return Err(ValidationError::new("priority", "must be finite"));
        }

        if value < 0.0 {
            return Err(ValidationError::new(
                "priority",
                "must be greater than or equal to zero",
            ));
        }

        Ok(Self(value))
    }

    pub fn value(self) -> f32 {
        self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_negative_priority_scores() {
        let error = PriorityScore::new(-0.1).expect_err("negative priority should fail");
        assert_eq!(error.field(), "priority");
    }

    #[test]
    fn accepts_positive_priority_scores() {
        let priority = PriorityScore::new(1.5).expect("priority should be valid");
        assert_eq!(priority.value(), 1.5);
    }
}
