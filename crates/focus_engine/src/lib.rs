//! Deterministic speaker-ranking policy built on top of `audio_core`.
//!
//! This crate keeps focus-selection logic small and reusable by accepting typed
//! speaker snapshots and returning stable ranking decisions.
//!
//! The authoritative session-mode policy table lives in [`ModeFocusPolicy::for_mode`].
//! Callers that need a one-off custom weighting can still inject [`FocusPolicy`]
//! values directly.

use audio_core::{PriorityScore, SessionMode, SpeakerState};

/// Normalized speaker inputs consumed by the ranking policy.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FocusInputs {
    /// Base score supplied by upstream state.
    pub base_score: PriorityScore,
    /// Whether the speaker is currently active.
    pub active: bool,
    /// Whether the user explicitly locked the speaker.
    pub user_locked: bool,
    /// Whether the speaker appears front-facing in the scene.
    pub front_facing: bool,
    /// Carry-over score from recent speaker history.
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

/// Weighting knobs for deterministic focus selection.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FocusPolicy {
    /// Score added when a speaker is actively talking.
    pub active_bonus: f32,
    /// Score subtracted when a speaker is inactive.
    pub inactive_penalty: f32,
    /// Score added when the user locks a speaker.
    pub user_lock_bonus: f32,
    /// Score added when the speaker is front-facing.
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
    /// Scores a single speaker input using a caller-supplied custom policy.
    pub fn score(&self, inputs: FocusInputs) -> f32 {
        score_with_persistence_multiplier(inputs, *self, 1.0)
    }
}

/// Authoritative mode-aware policy entry for deterministic focus selection.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ModeFocusPolicy {
    /// Base scoring weights for the current session mode.
    pub policy: FocusPolicy,
    /// Multiplier applied to the raw persistence carry-over input.
    pub persistence_multiplier: f32,
}

impl ModeFocusPolicy {
    /// Returns the authoritative policy entry for a session mode.
    pub const fn for_mode(mode: SessionMode) -> Self {
        match mode {
            SessionMode::Unspecified => Self {
                policy: FocusPolicy {
                    active_bonus: 0.25,
                    inactive_penalty: 1.0,
                    user_lock_bonus: 0.3,
                    front_facing_bonus: 0.1,
                },
                persistence_multiplier: 0.5,
            },
            SessionMode::Focus => Self {
                policy: FocusPolicy {
                    active_bonus: 0.4,
                    inactive_penalty: 1.1,
                    user_lock_bonus: 0.45,
                    front_facing_bonus: 0.2,
                },
                persistence_multiplier: 1.0,
            },
            SessionMode::Crowd => Self {
                policy: FocusPolicy {
                    active_bonus: 0.2,
                    inactive_penalty: 0.8,
                    user_lock_bonus: 0.2,
                    front_facing_bonus: 0.1,
                },
                persistence_multiplier: 0.6,
            },
            SessionMode::Locked => Self {
                policy: FocusPolicy {
                    active_bonus: 0.3,
                    inactive_penalty: 1.0,
                    user_lock_bonus: 0.9,
                    front_facing_bonus: 0.15,
                },
                persistence_multiplier: 0.8,
            },
        }
    }

    /// Scores a single speaker input using the authoritative session-mode policy.
    pub fn score(&self, inputs: FocusInputs) -> f32 {
        score_with_persistence_multiplier(inputs, self.policy, self.persistence_multiplier)
    }
}

fn score_with_persistence_multiplier(
    inputs: FocusInputs,
    policy: FocusPolicy,
    persistence_multiplier: f32,
) -> f32 {
    let mut score = inputs.base_score.value() + (inputs.persistence_bonus * persistence_multiplier);
    score += if inputs.active {
        policy.active_bonus
    } else {
        -policy.inactive_penalty
    };
    if inputs.user_locked {
        score += policy.user_lock_bonus;
    }
    if inputs.front_facing {
        score += policy.front_facing_bonus;
    }
    score
}

fn sort_speakers_by_score<F>(speakers: &[SpeakerState], mut score_for: F) -> Vec<SpeakerState>
where
    F: FnMut(&SpeakerState) -> f32,
{
    let mut ranked = speakers.to_vec();
    ranked.sort_by(|left, right| {
        let left_score = score_for(left);
        let right_score = score_for(right);

        right_score
            .total_cmp(&left_score)
            .then_with(|| left.speaker_id.as_str().cmp(right.speaker_id.as_str()))
    });
    ranked
}

/// Returns speakers sorted from highest to lowest policy score.
///
/// Ties are broken by `speaker_id` to keep ordering deterministic.
///
/// # Examples
///
/// ```
/// use audio_core::{LanguageCode, PriorityScore, SpeakerId, SpeakerState};
/// use focus_engine::{rank_speakers, FocusPolicy};
///
/// let ranked = rank_speakers(
///     &[
///         SpeakerState::new(
///             SpeakerId::new("speaker-a").unwrap(),
///             "Alice",
///             LanguageCode::new("en").unwrap(),
///             PriorityScore::new(0.6).unwrap(),
///             true,
///             false,
///             false,
///             0.0,
///             0,
///         )
///         .unwrap(),
///         SpeakerState::new(
///             SpeakerId::new("speaker-b").unwrap(),
///             "Bao",
///             LanguageCode::new("en").unwrap(),
///             PriorityScore::new(0.4).unwrap(),
///             true,
///             true,
///             false,
///             0.0,
///             0,
///         )
///         .unwrap(),
///     ],
///     &FocusPolicy::default(),
/// );
///
/// assert_eq!(ranked[0].speaker_id.as_str(), "speaker-b");
/// ```
pub fn rank_speakers(speakers: &[SpeakerState], policy: &FocusPolicy) -> Vec<SpeakerState> {
    sort_speakers_by_score(speakers, |speaker| policy.score(FocusInputs::from(speaker)))
}

/// Returns speakers sorted from highest to lowest score for an authoritative session mode.
///
/// Ties are broken by `speaker_id` to keep ordering deterministic across Rust and Python.
///
/// # Examples
///
/// ```
/// use audio_core::{LanguageCode, PriorityScore, SessionMode, SpeakerId, SpeakerState};
/// use focus_engine::rank_speakers_for_mode;
///
/// let ranked = rank_speakers_for_mode(
///     &[
///         SpeakerState::new(
///             SpeakerId::new("speaker-a").unwrap(),
///             "Alice",
///             LanguageCode::new("en").unwrap(),
///             PriorityScore::new(0.6).unwrap(),
///             true,
///             false,
///             false,
///             0.0,
///             0,
///         )
///         .unwrap(),
///         SpeakerState::new(
///             SpeakerId::new("speaker-b").unwrap(),
///             "Bao",
///             LanguageCode::new("en").unwrap(),
///             PriorityScore::new(0.4).unwrap(),
///             true,
///             true,
///             false,
///             0.0,
///             0,
///         )
///         .unwrap(),
///     ],
///     SessionMode::Locked,
/// );
///
/// assert_eq!(ranked[0].speaker_id.as_str(), "speaker-b");
/// ```
pub fn rank_speakers_for_mode(speakers: &[SpeakerState], mode: SessionMode) -> Vec<SpeakerState> {
    let policy = ModeFocusPolicy::for_mode(mode);
    sort_speakers_by_score(speakers, |speaker| policy.score(FocusInputs::from(speaker)))
}

/// Returns up to `limit` active speakers after applying ranking policy.
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

/// Returns up to `limit` active speakers after applying the authoritative session-mode policy.
pub fn top_n_active_speakers_for_mode(
    speakers: &[SpeakerState],
    mode: SessionMode,
    limit: usize,
) -> Vec<SpeakerState> {
    rank_speakers_for_mode(speakers, mode)
        .into_iter()
        .filter(|speaker| speaker.active)
        .take(limit)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::{rank_speakers, rank_speakers_for_mode, top_n_active_speakers, FocusPolicy};
    use audio_core::{LanguageCode, PriorityScore, SessionMode, SpeakerId, SpeakerState};

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

    #[test]
    fn ranks_speakers_using_authoritative_mode_table() {
        let ranked = rank_speakers_for_mode(
            &[
                speaker("speaker-a", 0.72, true, false, false, 0.05),
                speaker("speaker-b", 0.60, true, true, true, 0.02),
                speaker("speaker-c", 0.96, false, false, false, 0.10),
            ],
            SessionMode::Focus,
        );

        let ranked_ids: Vec<_> = ranked.iter().map(|item| item.speaker_id.as_str()).collect();
        assert_eq!(ranked_ids, vec!["speaker-b", "speaker-a", "speaker-c"]);
    }
}
