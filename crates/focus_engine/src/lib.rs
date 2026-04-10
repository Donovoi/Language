use audio_core::SpeakerFrame;

pub fn pick_top_speakers(mut speakers: Vec<SpeakerFrame>, limit: usize) -> Vec<SpeakerFrame> {
    speakers.sort_by(|a, b| b.priority.total_cmp(&a.priority));
    speakers.into_iter().take(limit).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn returns_highest_priority_first() {
        let result = pick_top_speakers(
            vec![
                SpeakerFrame::new("a", 0.2, true),
                SpeakerFrame::new("b", 0.9, true),
                SpeakerFrame::new("c", 0.5, true),
            ],
            2,
        );

        assert_eq!(result[0].speaker_id, "b");
        assert_eq!(result[1].speaker_id, "c");
    }
}
