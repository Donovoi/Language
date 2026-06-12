#!/usr/bin/env python3
"""Benchmark enrollment-aware target-speaker extraction artifacts.

The plain TSE contract proves that extracted audio can be scored. This harness
adds the missing target cue: an enrollment/reference clip for the speaker the
adapter claims to extract. It includes an oracle upper bound and a mismatched
enrollment negative control so future models cannot silently ignore the cue.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    PCM_SUBTYPE,
    analyze_fixture,
    dbfs,
    rms,
    scale_to_level,
    sha256_file,
    write_jsonl,
    write_report,
)
from benchmark_target_speaker_extraction_fixture import (
    base_fixture_dir,
    human_segments,
    overlap_s,
    read_mono,
    score_tse_predictions,
    segment_samples,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    prepare_multilingual_fixture,
)


DEFAULT_RUN_ID = "fleurs-enrolled-oracle-target-speaker-extraction"
DEFAULT_ADAPTER_ID = "oracle_enrolled_target_speaker_extraction_v1"
DEFAULT_MISMATCH_RUN_ID = "fleurs-mismatched-enrollment-target-speaker-extraction"
DEFAULT_MISMATCH_ADAPTER_ID = "mismatched_enrollment_target_speaker_extraction_v1"
DEFAULT_ENROLLMENT_DURATION_S = 1.0


def source_clip_audio(
    fixture_path: Path,
    segment: dict[str, Any],
    sample_rate_hz: int,
) -> np.ndarray:
    source_clip_path = segment.get("source_clip_path")
    if source_clip_path:
        audio, clip_rate_hz = read_mono(fixture_path / str(source_clip_path))
        if clip_rate_hz != sample_rate_hz:
            raise ValueError(f"{source_clip_path} sample rate mismatch")
        return audio

    stem_audio, stem_rate_hz = read_mono(fixture_path / segment["stem_path"])
    if stem_rate_hz != sample_rate_hz:
        raise ValueError(f"{segment['stem_path']} sample rate mismatch")
    return segment_samples(stem_audio, segment)


def fit_to_length(samples: np.ndarray, length: int) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32)
    if samples.shape[0] == length:
        return samples
    if samples.shape[0] > length:
        return samples[:length]
    if samples.shape[0] == 0:
        return np.zeros((length,), dtype=np.float32)
    repeats = int(np.ceil(length / float(samples.shape[0])))
    return np.tile(samples, repeats)[:length].astype(np.float32)


def write_enrollment_clip(
    fixture_path: Path,
    run_dir: Path,
    segment: dict[str, Any],
    sample_rate_hz: int,
    *,
    enrollment_duration_s: float,
) -> dict[str, Any]:
    clean_audio = source_clip_audio(fixture_path, segment, sample_rate_hz)
    requested_samples = max(1, int(round(enrollment_duration_s * sample_rate_hz)))
    enrollment_audio = clean_audio[: min(clean_audio.shape[0], requested_samples)]
    clip_path = run_dir / "enrollment_clips" / f"{segment['speaker_id']}.wav"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(clip_path, enrollment_audio, sample_rate_hz, subtype=PCM_SUBTYPE)
    return {
        "enrollment_audio_path": str(clip_path.relative_to(run_dir)),
        "enrollment_audio_sha256": sha256_file(clip_path),
        "enrollment_speaker_id": str(segment["speaker_id"]),
        "enrollment_duration_s": round(enrollment_audio.shape[0] / float(sample_rate_hz), 6),
        "enrollment_level_dbfs": round(dbfs(enrollment_audio), 3),
        "enrollment_kind": "clean_same_speaker_reference_clip",
    }


def mismatched_segment_for(
    segments: list[dict[str, Any]],
    target_index: int,
) -> dict[str, Any]:
    if len(segments) < 2:
        raise ValueError("mismatched enrollment check requires at least two speakers")
    return segments[(target_index + 1) % len(segments)]


def build_enrolled_oracle_tse_records(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str = DEFAULT_ADAPTER_ID,
    enrollment_duration_s: float = DEFAULT_ENROLLMENT_DURATION_S,
) -> list[dict[str, Any]]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    clip_dir = run_dir / "enrolled_oracle_tse_clips"
    prediction_segments: list[dict[str, Any]] = []
    for segment in human_segments(annotation):
        stem_audio, stem_rate_hz = read_mono(fixture_path / segment["stem_path"])
        if stem_rate_hz != sample_rate_hz:
            raise ValueError(f"{segment['stem_path']} sample rate mismatch")

        target_audio = segment_samples(stem_audio, segment)
        mixture_audio = segment_samples(mix_audio, segment)
        enrollment = write_enrollment_clip(
            fixture_path,
            run_dir,
            segment,
            sample_rate_hz,
            enrollment_duration_s=enrollment_duration_s,
        )
        clip_path = clip_dir / f"{segment['speaker_id']}.wav"
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(clip_path, target_audio, sample_rate_hz, subtype=PCM_SUBTYPE)

        prediction_segments.append(
            {
                "speaker_id": segment["speaker_id"],
                "target_speaker_id": segment["speaker_id"],
                "start_s": segment["start_s"],
                "end_s": segment["end_s"],
                "extracted_audio_path": str(clip_path.relative_to(run_dir)),
                "extracted_audio_sha256": sha256_file(clip_path),
                "source_mix_path": annotation["mix_path"],
                "reference_stem_path": segment["stem_path"],
                "input_level_dbfs": round(dbfs(mixture_audio), 3),
                "target_level_dbfs": round(dbfs(target_audio), 3),
                "output_level_dbfs": round(dbfs(target_audio), 3),
                "overlap_s": overlap_s(annotation, segment),
                "extraction_latency_ms": 0.0,
                **enrollment,
                "metadata": {
                    "kind": "oracle_enrolled_target_speaker_extraction_segment",
                    "oracle_upper_bound": True,
                    "target_condition": "clean_audio_enrollment",
                    "enrollment_same_speaker": True,
                    "same_utterance_enrollment_caveat": True,
                    "source_audio": "mixed_fixture",
                },
            }
        )

    return [
        {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": adapter_id,
            "segments": prediction_segments,
            "model_layer_latency_ms": {
                "separation_or_tse": 0.0,
                "enrollment_embedding": 0.0,
            },
            "metadata": {
                "kind": "oracle_enrolled_target_speaker_extraction",
                "oracle_upper_bound": True,
                "fixture_kind": "fleurs_multilingual_overlap",
                "contract": "target-speaker extraction JSONL v1 plus enrollment fields",
                "target_condition": "clean_audio_enrollment",
                "enrollment_duration_s": enrollment_duration_s,
                "detractor_note": (
                    "The enrollment clip is cut from the same clean source utterance for a "
                    "contract upper bound. Real adapters must use prior stable speaker audio, "
                    "voice profile capture, or explicit user enrollment."
                ),
            },
        }
    ]


def build_mismatched_enrollment_tse_records(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str = DEFAULT_MISMATCH_ADAPTER_ID,
    enrollment_duration_s: float = DEFAULT_ENROLLMENT_DURATION_S,
) -> list[dict[str, Any]]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    segments = human_segments(annotation)
    clip_dir = run_dir / "mismatched_enrollment_tse_clips"
    prediction_segments: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        wrong_segment = mismatched_segment_for(segments, index)
        target_stem_audio, target_stem_rate_hz = read_mono(fixture_path / segment["stem_path"])
        wrong_stem_audio, wrong_stem_rate_hz = read_mono(fixture_path / wrong_segment["stem_path"])
        if target_stem_rate_hz != sample_rate_hz or wrong_stem_rate_hz != sample_rate_hz:
            raise ValueError("stem sample rate mismatch")

        target_audio = segment_samples(target_stem_audio, segment)
        mixture_audio = segment_samples(mix_audio, segment)
        wrong_audio = segment_samples(wrong_stem_audio, segment)
        if rms(wrong_audio) <= 1.0e-8:
            wrong_audio = fit_to_length(
                source_clip_audio(fixture_path, wrong_segment, sample_rate_hz),
                int(target_audio.shape[0]),
            )
            wrong_audio = scale_to_level(wrong_audio, float(segment["level_dbfs"])).astype(np.float32)
        wrong_audio = fit_to_length(wrong_audio, int(target_audio.shape[0]))

        enrollment = write_enrollment_clip(
            fixture_path,
            run_dir,
            wrong_segment,
            sample_rate_hz,
            enrollment_duration_s=enrollment_duration_s,
        )
        clip_path = clip_dir / f"{segment['speaker_id']}.wav"
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(clip_path, wrong_audio, sample_rate_hz, subtype=PCM_SUBTYPE)

        prediction_segments.append(
            {
                "speaker_id": segment["speaker_id"],
                "target_speaker_id": segment["speaker_id"],
                "start_s": segment["start_s"],
                "end_s": segment["end_s"],
                "extracted_audio_path": str(clip_path.relative_to(run_dir)),
                "extracted_audio_sha256": sha256_file(clip_path),
                "source_mix_path": annotation["mix_path"],
                "reference_stem_path": segment["stem_path"],
                "input_level_dbfs": round(dbfs(mixture_audio), 3),
                "target_level_dbfs": round(dbfs(target_audio), 3),
                "output_level_dbfs": round(dbfs(wrong_audio), 3),
                "overlap_s": overlap_s(annotation, segment),
                "extraction_latency_ms": 0.0,
                **enrollment,
                "metadata": {
                    "kind": "mismatched_enrollment_target_speaker_extraction_segment",
                    "negative_control": True,
                    "target_condition": "clean_audio_enrollment",
                    "enrollment_same_speaker": False,
                    "expected_to_fail_target_audio_quality": True,
                    "source_audio": "wrong_enrollment_speaker_audio",
                },
            }
        )

    return [
        {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": adapter_id,
            "segments": prediction_segments,
            "model_layer_latency_ms": {
                "separation_or_tse": 0.0,
                "enrollment_embedding": 0.0,
            },
            "metadata": {
                "kind": "mismatched_enrollment_target_speaker_extraction",
                "negative_control": True,
                "fixture_kind": "fleurs_multilingual_overlap",
                "contract": "target-speaker extraction JSONL v1 plus enrollment fields",
                "target_condition": "clean_audio_enrollment",
                "enrollment_duration_s": enrollment_duration_s,
                "detractor_note": (
                    "This negative control deliberately pairs each target segment with another "
                    "speaker's enrollment. A real TSE model must reject or visibly fail this case."
                ),
            },
        }
    ]


def enrollment_contract_report(
    prediction: dict[str, Any],
    run_dir: Path,
    *,
    expect_mismatches: bool,
) -> dict[str, Any]:
    segments = prediction.get("segments", [])
    details: list[dict[str, Any]] = []
    for segment in segments:
        enrollment_path_value = str(segment.get("enrollment_audio_path", ""))
        enrollment_path = run_dir / enrollment_path_value if enrollment_path_value else None
        target_speaker_id = str(segment.get("target_speaker_id", segment.get("speaker_id", "")))
        enrollment_speaker_id = str(segment.get("enrollment_speaker_id", ""))
        duration_s = float(segment.get("enrollment_duration_s", 0.0) or 0.0)
        details.append(
            {
                "speaker_id": str(segment.get("speaker_id", "")),
                "target_speaker_id": target_speaker_id,
                "enrollment_speaker_id": enrollment_speaker_id,
                "enrollment_audio_path": enrollment_path_value,
                "enrollment_path_exists": bool(enrollment_path and enrollment_path.exists()),
                "enrollment_audio_sha256": segment.get("enrollment_audio_sha256"),
                "enrollment_duration_s": round(duration_s, 6),
                "enrollment_matches_target": enrollment_speaker_id == target_speaker_id,
            }
        )

    mismatch_count = sum(1 for detail in details if not detail["enrollment_matches_target"])
    summary = {
        "segment_count": len(segments),
        "enrollment_path_count": sum(1 for detail in details if detail["enrollment_audio_path"]),
        "enrollment_hash_count": sum(1 for detail in details if detail["enrollment_audio_sha256"]),
        "enrollment_files_exist_count": sum(
            1 for detail in details if detail["enrollment_path_exists"]
        ),
        "positive_duration_count": sum(
            1 for detail in details if float(detail["enrollment_duration_s"]) > 0.0
        ),
        "mismatched_enrollment_count": mismatch_count,
        "expected_mismatches": expect_mismatches,
    }
    summary["quality_gates"] = enrollment_quality_gates(summary)
    return {
        "summary": summary,
        "segments": details,
    }


def enrollment_quality_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    segment_count = int(summary["segment_count"])
    expect_mismatches = bool(summary["expected_mismatches"])
    mismatch_count = int(summary["mismatched_enrollment_count"])
    return [
        {
            "name": "enrollment_path_present",
            "value": int(summary["enrollment_path_count"]),
            "threshold": f"{segment_count} enrollment paths",
            "passed": int(summary["enrollment_path_count"]) == segment_count,
        },
        {
            "name": "enrollment_hash_present",
            "value": int(summary["enrollment_hash_count"]),
            "threshold": f"{segment_count} enrollment hashes",
            "passed": int(summary["enrollment_hash_count"]) == segment_count,
        },
        {
            "name": "enrollment_file_exists",
            "value": int(summary["enrollment_files_exist_count"]),
            "threshold": f"{segment_count} enrollment files",
            "passed": int(summary["enrollment_files_exist_count"]) == segment_count,
        },
        {
            "name": "enrollment_duration_positive",
            "value": int(summary["positive_duration_count"]),
            "threshold": f"{segment_count} positive-duration enrollment clips",
            "passed": int(summary["positive_duration_count"]) == segment_count,
        },
        {
            "name": "enrollment_match_expectation",
            "value": mismatch_count,
            "threshold": (
                f"{segment_count} mismatched enrollments"
                if expect_mismatches
                else "0 mismatched enrollments"
            ),
            "passed": mismatch_count == segment_count if expect_mismatches else mismatch_count == 0,
        },
    ]


def build_report(
    annotation: dict[str, Any],
    output_dir: Path,
    prediction: dict[str, Any],
    prediction_path: Path,
    *,
    expect_mismatches: bool,
) -> dict[str, Any]:
    run_dir = prediction_path.parent
    tse_report = score_tse_predictions(annotation, output_dir, prediction, run_dir)
    enrollment_report = enrollment_contract_report(
        prediction,
        run_dir,
        expect_mismatches=expect_mismatches,
    )
    fixture_report = analyze_fixture(output_dir, annotation)
    gates = tse_report["summary"]["quality_gates"] + enrollment_report["summary"]["quality_gates"]
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_enrollment_target_speaker_extraction",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
        },
        "benchmarks": {
            "target_speaker_extraction": tse_report,
            "enrollment_contract": enrollment_report,
        },
        "prediction_paths": {
            "target_speaker_extraction": str(prediction_path),
        },
        "fixtures": [fixture_report],
        "adapter": prediction["metadata"],
        "detractor_loop": {
            "strongest_objection": (
                "Same-utterance oracle enrollment proves the artifact contract, not real speaker "
                "verification. A production model must handle prior enrollment, noisy enrollment, "
                "target absence, and wrong-speaker cues."
            ),
            "cheapest_falsifying_benchmark": (
                "Run a mismatched enrollment through the same extraction path and require the "
                "adapter either reject the cue or fail visible quality gates."
            ),
            "fallback_if_falsified": (
                "Gate voice-cloned playback behind speaker-lock confidence and keep text captions "
                "when enrollment identity is missing or ambiguous."
            ),
        },
    }


def mismatch_failed_as_expected(report: dict[str, Any]) -> bool:
    gate_map = {str(gate["name"]): bool(gate["passed"]) for gate in report["summary"]["quality_gates"]}
    tse_failed = (
        gate_map.get("tse_min_segment_snr_db") is False
        and gate_map.get("tse_min_interferer_reduction_db") is False
    )
    enrollment_passed = (
        gate_map.get("enrollment_path_present") is True
        and gate_map.get("enrollment_hash_present") is True
        and gate_map.get("enrollment_file_exists") is True
        and gate_map.get("enrollment_duration_positive") is True
        and gate_map.get("enrollment_match_expectation") is True
    )
    return tse_failed and enrollment_passed


def self_test() -> dict[str, Any]:
    sample_rate_hz = 16000
    duration_s = 2.0
    samples = np.arange(int(sample_rate_hz * duration_s), dtype=np.float32) / sample_rate_hz
    speaker_a = 0.12 * np.sin(2.0 * np.pi * 220.0 * samples).astype(np.float32)
    speaker_b = 0.08 * np.sin(2.0 * np.pi * 330.0 * samples).astype(np.float32)
    stem_a = np.zeros_like(samples)
    stem_b = np.zeros_like(samples)
    stem_a[: int(1.4 * sample_rate_hz)] = speaker_a[: int(1.4 * sample_rate_hz)]
    stem_b[int(0.6 * sample_rate_hz) :] = speaker_b[int(0.6 * sample_rate_hz) :]
    mix = stem_a + stem_b

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir) / "audio_eval"
        annotation = {
            "schema_version": 1,
            "fixture_set_id": "self-test-enrolled-tse",
            "fixture_id": "self_test_enrolled_tse_overlap",
            "description": "self-test enrolled target speaker extraction fixture",
            "sample_rate_hz": sample_rate_hz,
            "duration_s": duration_s,
            "mix_path": "mix.wav",
            "mix_sha256": "",
            "stems": [],
            "background_noise_dbfs": None,
            "source_license": "generated self-test",
            "source_url": None,
            "detractor_note": "self-test only",
            "segments": [
                {
                    "index": 0,
                    "speaker_id": "speaker_a",
                    "source_kind": "human",
                    "language_code": "en-US",
                    "voice_profile": "self_test_a",
                    "start_s": 0.0,
                    "end_s": 1.4,
                    "start_sample": 0,
                    "end_sample": int(1.4 * sample_rate_hz),
                    "level_dbfs": -21.0,
                    "stem_path": "stems/speaker_a.wav",
                    "source_clip_path": "source_clips/speaker_a.wav",
                },
                {
                    "index": 1,
                    "speaker_id": "speaker_b",
                    "source_kind": "human",
                    "language_code": "es-419",
                    "voice_profile": "self_test_b",
                    "start_s": 0.6,
                    "end_s": 2.0,
                    "start_sample": int(0.6 * sample_rate_hz),
                    "end_sample": int(2.0 * sample_rate_hz),
                    "level_dbfs": -24.0,
                    "stem_path": "stems/speaker_b.wav",
                    "source_clip_path": "source_clips/speaker_b.wav",
                },
            ],
        }
        target_dir = base_fixture_dir(output_dir, annotation)
        (target_dir / "stems").mkdir(parents=True, exist_ok=True)
        (target_dir / "source_clips").mkdir(parents=True, exist_ok=True)
        sf.write(target_dir / "mix.wav", mix, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(target_dir / "stems" / "speaker_a.wav", stem_a, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(target_dir / "stems" / "speaker_b.wav", stem_b, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(
            target_dir / "source_clips" / "speaker_a.wav",
            speaker_a[: int(1.4 * sample_rate_hz)],
            sample_rate_hz,
            subtype=PCM_SUBTYPE,
        )
        sf.write(
            target_dir / "source_clips" / "speaker_b.wav",
            speaker_b[int(0.6 * sample_rate_hz) :],
            sample_rate_hz,
            subtype=PCM_SUBTYPE,
        )
        annotation["mix_sha256"] = sha256_file(target_dir / "mix.wav")
        annotation["stems"] = [
            {
                "track_id": "speaker_a",
                "path": "stems/speaker_a.wav",
                "sha256": sha256_file(target_dir / "stems" / "speaker_a.wav"),
            },
            {
                "track_id": "speaker_b",
                "path": "stems/speaker_b.wav",
                "sha256": sha256_file(target_dir / "stems" / "speaker_b.wav"),
            },
        ]

        oracle_run_dir = output_dir / "runs" / "self-test-enrolled-oracle"
        oracle_prediction_path = oracle_run_dir / "enrolled_oracle_tse_predictions.jsonl"
        oracle_record = build_enrolled_oracle_tse_records(
            annotation,
            output_dir,
            oracle_run_dir,
        )[0]
        oracle_report = build_report(
            annotation,
            output_dir,
            oracle_record,
            oracle_prediction_path,
            expect_mismatches=False,
        )
        if not all(bool(gate["passed"]) for gate in oracle_report["summary"]["quality_gates"]):
            raise RuntimeError("self-test expected enrolled oracle TSE gates to pass")

        mismatch_run_dir = output_dir / "runs" / "self-test-enrollment-mismatch"
        mismatch_prediction_path = mismatch_run_dir / "mismatched_enrollment_tse_predictions.jsonl"
        mismatch_record = build_mismatched_enrollment_tse_records(
            annotation,
            output_dir,
            mismatch_run_dir,
        )[0]
        mismatch_report = build_report(
            annotation,
            output_dir,
            mismatch_record,
            mismatch_prediction_path,
            expect_mismatches=True,
        )
        if not mismatch_failed_as_expected(mismatch_report):
            raise RuntimeError("self-test expected mismatched enrollment to fail TSE gates")
        return {
            "oracle_summary": oracle_report["benchmarks"]["target_speaker_extraction"]["summary"],
            "oracle_enrollment_summary": oracle_report["benchmarks"]["enrollment_contract"][
                "summary"
            ],
            "mismatch_summary": mismatch_report["benchmarks"]["target_speaker_extraction"][
                "summary"
            ],
            "mismatch_enrollment_summary": mismatch_report["benchmarks"]["enrollment_contract"][
                "summary"
            ],
        }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "WARN"
    tse_summary = report["benchmarks"]["target_speaker_extraction"]["summary"]
    enrollment_summary = report["benchmarks"]["enrollment_contract"]["summary"]
    print(f"enrolled target-speaker extraction {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "WARN"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  enrollment diagnostics: "
        f"mismatches={enrollment_summary['mismatched_enrollment_count']} "
        f"mean_snr_db={tse_summary['mean_segment_snr_db']} "
        f"min_interferer_reduction_db={tse_summary['min_interferer_reduction_db']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark enrolled TSE fixtures")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["oracle-check", "mismatch-check"],
        default="oracle-check",
    )
    parser.add_argument("--self-test", action="store_true", help="validate enrolled TSE scorer only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--adapter-id", default=None)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--enrollment-duration-s", type=float, default=DEFAULT_ENROLLMENT_DURATION_S)
    parser.add_argument("--max-stream-mb", type=int, default=64)
    parser.add_argument(
        "--score-warning-only",
        action="store_true",
        help="write measured report but exit 0 even when model quality gates warn",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        report = self_test()
        print("enrolled target-speaker extraction contract self-test PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    output_dir = args.output_dir.resolve()
    annotation = prepare_multilingual_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        max_stream_mb=args.max_stream_mb,
    )

    if args.command == "oracle-check":
        run_id = args.run_id or DEFAULT_RUN_ID
        adapter_id = args.adapter_id or DEFAULT_ADAPTER_ID
        run_dir = output_dir / "runs" / run_id
        prediction_path = run_dir / "enrolled_oracle_tse_predictions.jsonl"
        records = build_enrolled_oracle_tse_records(
            annotation,
            output_dir,
            run_dir,
            adapter_id=adapter_id,
            enrollment_duration_s=args.enrollment_duration_s,
        )
        expect_mismatches = False
    else:
        run_id = args.run_id or DEFAULT_MISMATCH_RUN_ID
        adapter_id = args.adapter_id or DEFAULT_MISMATCH_ADAPTER_ID
        run_dir = output_dir / "runs" / run_id
        prediction_path = run_dir / "mismatched_enrollment_tse_predictions.jsonl"
        records = build_mismatched_enrollment_tse_records(
            annotation,
            output_dir,
            run_dir,
            adapter_id=adapter_id,
            enrollment_duration_s=args.enrollment_duration_s,
        )
        expect_mismatches = True

    prediction = records[0]
    write_jsonl(records, prediction_path)
    report = build_report(
        annotation,
        output_dir,
        prediction,
        prediction_path,
        expect_mismatches=expect_mismatches,
    )
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "enrolled-tse-fixture-report.json"
    )
    write_report(report, report_path)
    print(f"wrote enrolled TSE predictions to {prediction_path}")
    print(f"wrote enrolled TSE report to {report_path}")
    print_summary(report)
    if args.command == "mismatch-check":
        if mismatch_failed_as_expected(report):
            print("mismatched enrollment target-speaker extraction failed expected quality gates")
            return 0
        print("mismatched enrollment target-speaker extraction did not fail expected gates")
        return 1
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
