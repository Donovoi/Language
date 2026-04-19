use audio_core::{PriorityScore, SpeakerState};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FocusInputs {
    pub base_score: PriorityScore,
    pub active: bool,
    pub user_locked: bool,
    pub front_facing: bool,
    pub persistence_bonus: f32,
}

impl From<&SpeakerState> for FocusInputs {
    fn from(value: &SpeakerState) -> Self {
        Self {
            base_score: value.priority,
            active: value.active,
            user_locked: value.is_locked,
            front_facing: value.front_facing,
            persistence_bonus: value.persistence_bonus,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FocusPolicy {
    pub active_bonus: f32,
    pub inactive_penalty: f32,
    pub user_lock_bonus: f32,
    pub front_facing_bonus: f32,
}

impl Default for FocusPolicy {
    fn default() -> Self {
        Self {
            active_bonus: 0.35,
            inactive_penalty: 1.0,
            user_lock_bonus: 0.5,
            front_facing_bonus: 0.15,
        }
    }
}

impl FocusPolicy {
    pub fn score(&self, inputs: FocusInputs) -> f32 {
        let mut score = inputs.base_score.value() + inputs.persistence_bonus;
        score += if inputs.active {
            self.active_bonus
        } else {
            -self.inactive_penalty
        };
        if inputs.user_locked {
            score += self.user_lock_bonus;
        }
        if inputs.front_facing {
            score += self.front_facing_bonus;
        }
        score
    }
}

pub fn rank_speakers(speakers: &[SpeakerState], policy: &FocusPolicy) -> Vec<SpeakerState> {
    let mut ranked = speakers.to_vec();
    ranked.sort_by(|left, right| {
        let left_score = policy.score(FocusInputs::from(left));
        let right_score = policy.score(FocusInputs::from(right));

        right_score
            .total_cmp(&left_score)
            .then_with(|| left.speaker_id.as_str().cmp(right.speaker_id.as_str()))
    });
    ranked
}

pub fn top_n_active_speakers(
    speakers: &[SpeakerState],
    policy: &FocusPolicy,
    limit: usize,
) -> Vec<SpeakerState> {
    rank_speakers(speakers, policy)
        .into_iter()
        .filter(|speaker| speaker.active)
        .take(limit)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::{rank_speakers, top_n_active_speakers, FocusPolicy};
    use audio_core::{LanguageCode, PriorityScore, SpeakerId, SpeakerState};

    fn speaker(
        id: &str,
        priority: f32,
        active: bool,
        is_locked: bool,
        front_facing: bool,
        persistence_bonus: f32,
    ) -> SpeakerState {
        SpeakerState::new(
            SpeakerId::new(id).expect("speaker id"),
            format!("Speaker {id}"),
            LanguageCode::new("en").expect("language code"),
            PriorityScore::new(priority).expect("priority"),
            active,
            is_locked,
            front_facing,
            persistence_bonus,
            0,
        )
        .expect("speaker should be valid")
    }

    #[test]
    fn ranks_speakers_using_policy_weighting() {
        let policy = FocusPolicy::default();
        let ranked = rank_speakers(
            &[
                speaker("speaker-a", 0.7, true, false, false, 0.0),
                speaker("speaker-b", 0.5, true, true, false, 0.0),
                speaker("speaker-c", 0.9, false, false, false, 0.0),
            ],
            &policy,
        );

        let ranked_ids: Vec<_> = ranked.iter().map(|item| item.speaker_id.as_str()).collect();
        assert_eq!(ranked_ids, vec!["speaker-b", "speaker-a", "speaker-c"]);
    }

    #[test]
    fn takes_only_active_speakers_for_top_n() {
        let policy = FocusPolicy::default();
        let ranked = top_n_active_speakers(
            &[
                speaker("speaker-a", 0.2, false, false, false, 0.4),
                speaker("speaker-b", 0.6, true, false, true, 0.0),
                speaker("speaker-c", 0.5, true, false, false, 0.3),
            ],
            &policy,
            2,
        );

        let ranked_ids: Vec<_> = ranked.iter().map(|item| item.speaker_id.as_str()).collect();
        assert_eq!(ranked_ids, vec!["speaker-c", "speaker-b"]);
    }
}
