use std::collections::{btree_map::Entry, BTreeMap};

use audio_core::{LanguageCode, PriorityScore, SessionMode, SpeakerId, SpeakerState};
use focus_engine::{
    rank_speakers_for_mode, top_n_active_speakers_for_mode, FocusInputs, ModeFocusPolicy,
};

const FIXTURE: &str = include_str!("../testdata/prioritization_vectors.tsv");

#[derive(Debug)]
struct FixtureSpeaker {
    speaker_id: String,
    display_name: String,
    priority: f32,
    active: bool,
    is_locked: bool,
    front_facing: bool,
    persistence_bonus: f32,
    expected_score: f32,
}

#[derive(Debug)]
struct FixtureCase {
    case_id: String,
    mode: SessionMode,
    expected_order: Vec<String>,
    speakers: Vec<FixtureSpeaker>,
}

#[test]
fn shared_parity_vectors_match_mode_authority() {
    for case in parse_cases() {
        let case_id = case.case_id.clone();
        let expected_order = case.expected_order.clone();
        let speakers: Vec<_> = case.speakers.iter().map(build_speaker).collect();
        let policy = ModeFocusPolicy::for_mode(case.mode);

        for (fixture_speaker, speaker) in case.speakers.iter().zip(speakers.iter()) {
            assert_eq!(
                round3(policy.score(FocusInputs::from(speaker))),
                fixture_speaker.expected_score,
                "score drifted for case {case_id} speaker {}",
                fixture_speaker.speaker_id,
            );
        }

        let ranked = rank_speakers_for_mode(&speakers, case.mode);
        let ranked_ids: Vec<_> = ranked
            .iter()
            .map(|speaker| speaker.speaker_id.as_str().to_string())
            .collect();
        assert_eq!(
            ranked_ids, expected_order,
            "ranking drifted for case {case_id}"
        );

        let expected_active_ids: Vec<_> = case
            .expected_order
            .iter()
            .filter(|speaker_id| {
                case.speakers
                    .iter()
                    .find(|fixture_speaker| &fixture_speaker.speaker_id == *speaker_id)
                    .expect("fixture speaker should exist")
                    .active
            })
            .cloned()
            .collect();
        let ranked_active =
            top_n_active_speakers_for_mode(&speakers, case.mode, expected_active_ids.len());
        let ranked_active_ids: Vec<_> = ranked_active
            .iter()
            .map(|speaker| speaker.speaker_id.as_str().to_string())
            .collect();
        assert_eq!(
            ranked_active_ids, expected_active_ids,
            "active-speaker drifted for case {case_id}",
        );
    }
}

fn parse_cases() -> Vec<FixtureCase> {
    let mut lines = FIXTURE
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#'));

    let header = lines.next().expect("fixture header should exist");
    assert_eq!(
        header,
        "case_id\tmode\tspeaker_id\tdisplay_name\tpriority\tactive\tis_locked\tfront_facing\tpersistence_bonus\texpected_score\texpected_order",
        "unexpected prioritization parity header",
    );

    let mut cases = BTreeMap::<String, FixtureCase>::new();
    for line in lines {
        let columns: Vec<_> = line.split('\t').collect();
        assert_eq!(
            columns.len(),
            11,
            "expected 11 tab-separated columns in prioritization parity row: {line}",
        );

        let case_id = columns[0].to_string();
        let mode = parse_mode(columns[1]);
        let expected_order = columns[10]
            .split(',')
            .map(|speaker_id| speaker_id.to_string())
            .collect::<Vec<_>>();
        let fixture_speaker = FixtureSpeaker {
            speaker_id: columns[2].to_string(),
            display_name: columns[3].to_string(),
            priority: columns[4].parse().expect("priority should parse"),
            active: parse_bool(columns[5]),
            is_locked: parse_bool(columns[6]),
            front_facing: parse_bool(columns[7]),
            persistence_bonus: columns[8].parse().expect("persistence bonus should parse"),
            expected_score: columns[9].parse().expect("expected score should parse"),
        };

        match cases.entry(case_id.clone()) {
            Entry::Vacant(entry) => {
                entry.insert(FixtureCase {
                    case_id,
                    mode,
                    expected_order,
                    speakers: vec![fixture_speaker],
                });
            }
            Entry::Occupied(mut entry) => {
                let case = entry.get_mut();
                assert_eq!(case.mode, mode, "fixture case mode drifted for {case_id}");
                assert_eq!(
                    case.expected_order, expected_order,
                    "fixture case ordering drifted for {case_id}",
                );
                case.speakers.push(fixture_speaker);
            }
        }
    }

    cases.into_values().collect()
}

fn parse_mode(raw: &str) -> SessionMode {
    match raw {
        "UNSPECIFIED" => SessionMode::Unspecified,
        "FOCUS" => SessionMode::Focus,
        "CROWD" => SessionMode::Crowd,
        "LOCKED" => SessionMode::Locked,
        _ => panic!("unexpected session mode {raw}"),
    }
}

fn parse_bool(raw: &str) -> bool {
    match raw {
        "true" => true,
        "false" => false,
        _ => panic!("unexpected boolean value {raw}"),
    }
}

fn build_speaker(fixture: &FixtureSpeaker) -> SpeakerState {
    SpeakerState::new(
        SpeakerId::new(&fixture.speaker_id).expect("speaker id"),
        fixture.display_name.clone(),
        LanguageCode::new("en").expect("language code"),
        PriorityScore::new(fixture.priority).expect("priority"),
        fixture.active,
        fixture.is_locked,
        fixture.front_facing,
        fixture.persistence_bonus,
        0,
    )
    .expect("speaker should be valid")
}

fn round3(value: f32) -> f32 {
    (value * 1000.0).round() / 1000.0
}
