use audio_core::{PriorityScore, SpeakerState};

#[derive(Debug, Clone, PartialEq)]
pub struct FocusInputs {
    pub speaker: SpeakerState,
    pub user_locked: Option<bool>,
    pub front_facing_bias: Option<f32>,
    pub persistence_bonus: Option<f32>,
}

impl FocusInputs {
    pub fn new(speaker: SpeakerState) -> Self {
        Self {
            speaker,
            user_locked: None,
            front_facing_bias: None,
            persistence_bonus: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct FocusPolicy {
    pub active_bonus: f32,
    pub inactive_penalty: f32,
    pub locked_bonus: f32,
    pub front_facing_weight: f32,
    pub persistence_weight: f32,
}

impl Default for FocusPolicy {
    fn default() -> Self {
        Self {
            active_bonus: 0.25,
            inactive_penalty: 0.2,
            locked_bonus: 0.5,
            front_facing_weight: 0.1,
            persistence_weight: 0.1,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RankedSpeaker {
    pub speaker: SpeakerState,
    pub score: PriorityScore,
}

impl FocusPolicy {
    pub fn score(&self, inputs: &FocusInputs) -> PriorityScore {
        let mut total = inputs.speaker.priority().value();

        if inputs.speaker.active() {
            total += self.active_bonus;
        } else {
            total = (total - self.inactive_penalty).max(0.0);
        }

        if inputs.user_locked.unwrap_or_else(|| inputs.speaker.is_locked()) {
            total += self.locked_bonus;
        }

        if let Some(front_facing_bias) = inputs.front_facing_bias {
            total += front_facing_bias * self.front_facing_weight;
        }

        if let Some(persistence_bonus) = inputs.persistence_bonus {
            total += persistence_bonus * self.persistence_weight;
        }

        PriorityScore::new(total.max(0.0)).expect("policy scores should always be valid")
    }
}

pub fn rank_speakers<I>(policy: &FocusPolicy, speakers: I) -> Vec<RankedSpeaker>
where
    I: IntoIterator<Item = FocusInputs>,
{
    let mut ranked: Vec<RankedSpeaker> = speakers
        .into_iter()
        .map(|inputs| RankedSpeaker {
            score: policy.score(&inputs),
            speaker: inputs.speaker,
        })
        .collect();

    ranked.sort_by(|left, right| {
        right
            .score
            .value()
            .total_cmp(&left.score.value())
            .then_with(|| {
                right
                    .speaker
                    .active()
                    .cmp(&left.speaker.active())
            })
            .then_with(|| {
                left.speaker
                    .speaker_id()
                    .as_str()
                    .cmp(right.speaker.speaker_id().as_str())
            })
    });

    ranked
}

pub fn top_n_active_speakers<I>(policy: &FocusPolicy, speakers: I, limit: usize) -> Vec<RankedSpeaker>
where
    I: IntoIterator<Item = FocusInputs>,
{
    rank_speakers(policy, speakers)
        .into_iter()
        .filter(|speaker| speaker.speaker.active())
        .take(limit)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use audio_core::{LanguageCode, SpeakerId};

    fn speaker(id: &str, priority: f32, active: bool, locked: bool) -> SpeakerState {
        SpeakerState::new(
            SpeakerId::new(id).expect("speaker id should be valid"),
            format!("Speaker {id}"),
            LanguageCode::new("en").expect("language code should be valid"),
            PriorityScore::new(priority).expect("priority should be valid"),
            active,
            locked,
            100,
        )
        .expect("speaker should be valid")
    }

    #[test]
    fn ranks_by_weighted_score() {
        let policy = FocusPolicy::default();
        let ranked = rank_speakers(
            &policy,
            vec![
                FocusInputs {
                    speaker: speaker("alpha", 0.5, true, false),
                    user_locked: None,
                    front_facing_bias: Some(0.2),
                    persistence_bonus: Some(0.0),
                },
                FocusInputs {
                    speaker: speaker("bravo", 0.45, true, true),
                    user_locked: None,
                    front_facing_bias: Some(0.0),
                    persistence_bonus: Some(0.0),
                },
            ],
        );

        assert_eq!(ranked[0].speaker.speaker_id().as_str(), "bravo");
        assert!(ranked[0].score.value() > ranked[1].score.value());
    }

    #[test]
    fn returns_only_active_speakers_for_top_n() {
        let policy = FocusPolicy::default();
        let top = top_n_active_speakers(
            &policy,
            vec![
                FocusInputs::new(speaker("alpha", 0.6, false, false)),
                FocusInputs::new(speaker("bravo", 0.5, true, false)),
                FocusInputs::new(speaker("charlie", 0.7, true, false)),
            ],
            2,
        );

        let ids: Vec<&str> = top
            .iter()
            .map(|speaker| speaker.speaker.speaker_id().as_str())
            .collect();

        assert_eq!(ids, vec!["charlie", "bravo"]);
    }

    #[test]
    fn user_lock_can_override_speaker_lock_state() {
        let policy = FocusPolicy::default();
        let unlocked_score = policy.score(&FocusInputs::new(speaker("alpha", 0.4, true, false)));
        let locked_score = policy.score(&FocusInputs {
            speaker: speaker("alpha", 0.4, true, false),
            user_locked: Some(true),
            front_facing_bias: None,
            persistence_bonus: None,
        });

        assert!(locked_score.value() > unlocked_score.value());
    }
}
