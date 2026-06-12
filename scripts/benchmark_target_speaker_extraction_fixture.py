#!/usr/bin/env python3
"""Benchmark target-speaker extraction artifacts on the FLEURS overlap fixture.

The first adapter is intentionally oracle-backed: it writes per-speaker clips
from fixture stems, scores the separation contract, and establishes the upper
bound that real target-speaker extraction models must approach before spoken
translated playback is trusted.
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
    linear_to_db,
    rms,
    sha256_file,
    write_jsonl,
    write_report,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    prepare_multilingual_fixture,
)
from prepare_real_speech_fixture import fixture_dir


DEFAULT_RUN_ID = "fleurs-oracle-target-speaker-extraction"
DEFAULT_ADAPTER_ID = "oracle_target_speaker_extraction_v1"
DEFAULT_PASSTHROUGH_RUN_ID = "fleurs-passthrough-target-speaker-extraction"
DEFAULT_PASSTHROUGH_ADAPTER_ID = "mixture_passthrough_target_speaker_extraction_v1"
DEFAULT_SCORE_RUN_ID = "fleurs-target-speaker-extraction-score"
_EPS = 1.0e-10
_DB_CAP = 120.0


def human_segments(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        segment
        for segment in sorted(annotation["segments"], key=lambda item: float(item["start_s"]))
        if segment.get("source_kind") == "human"
    ]


def base_fixture_dir(output_dir: Path, annotation: dict[str, Any]) -> Path:
    return fixture_dir(output_dir, annotation["fixture_set_id"], annotation["fixture_id"])


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate_hz = sf.read(path, dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    return np.asarray(audio, dtype=np.float32), int(sample_rate_hz)


def segment_samples(audio: np.ndarray, segment: dict[str, Any]) -> np.ndarray:
    start_sample = int(segment["start_sample"])
    end_sample = int(segment["end_sample"])
    return np.asarray(audio[start_sample:end_sample], dtype=np.float32)


def intersection_duration(left: dict[str, Any], right: dict[str, Any]) -> float:
    start_s = max(float(left["start_s"]), float(right["start_s"]))
    end_s = min(float(left["end_s"]), float(right["end_s"]))
    return max(0.0, end_s - start_s)


def overlap_s(annotation: dict[str, Any], target: dict[str, Any]) -> float:
    return round(
        sum(
            intersection_duration(target, other)
            for other in human_segments(annotation)
            if other["speaker_id"] != target["speaker_id"]
        ),
        6,
    )


def ratio_db(numerator: float, denominator: float) -> float:
    if denominator <= _EPS:
        return _DB_CAP if numerator > _EPS else 0.0
    return min(_DB_CAP, linear_to_db(max(numerator, _EPS) / denominator))


def aligned_pair(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    length = min(int(left.shape[0]), int(right.shape[0]))
    if length <= 0:
        return np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.float32)
    return left[:length], right[:length]


def build_oracle_tse_records(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str = DEFAULT_ADAPTER_ID,
) -> list[dict[str, Any]]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    clip_dir = run_dir / "oracle_tse_clips"
    prediction_segments: list[dict[str, Any]] = []
    for segment in human_segments(annotation):
        stem_audio, stem_rate_hz = read_mono(fixture_path / segment["stem_path"])
        if stem_rate_hz != sample_rate_hz:
            raise ValueError(f"{segment['stem_path']} sample rate mismatch")

        target_audio = segment_samples(stem_audio, segment)
        mixture_audio = segment_samples(mix_audio, segment)
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
                "metadata": {
                    "kind": "oracle_target_speaker_extraction_segment",
                    "oracle_upper_bound": True,
                    "target_condition": "fixture_speaker_id_and_stem",
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
            },
            "metadata": {
                "kind": "oracle_target_speaker_extraction",
                "oracle_upper_bound": True,
                "fixture_kind": "fleurs_multilingual_overlap",
                "contract": "target-speaker extraction JSONL v1",
            },
        }
    ]


def build_passthrough_tse_records(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str = DEFAULT_PASSTHROUGH_ADAPTER_ID,
) -> list[dict[str, Any]]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    clip_dir = run_dir / "passthrough_tse_clips"
    prediction_segments: list[dict[str, Any]] = []
    for segment in human_segments(annotation):
        mixture_audio = segment_samples(mix_audio, segment)
        clip_path = clip_dir / f"{segment['speaker_id']}.wav"
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(clip_path, mixture_audio, sample_rate_hz, subtype=PCM_SUBTYPE)

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
                "target_level_dbfs": float(segment["level_dbfs"]),
                "output_level_dbfs": round(dbfs(mixture_audio), 3),
                "overlap_s": overlap_s(annotation, segment),
                "extraction_latency_ms": 0.0,
                "metadata": {
                    "kind": "mixture_passthrough_target_speaker_extraction_segment",
                    "negative_control": True,
                    "target_condition": "fixture_speaker_id_without_separation",
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
            },
            "metadata": {
                "kind": "mixture_passthrough_target_speaker_extraction",
                "negative_control": True,
                "fixture_kind": "fleurs_multilingual_overlap",
                "contract": "target-speaker extraction JSONL v1",
            },
        }
    ]


def read_prediction_record(path: Path) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 1:
        raise ValueError(f"expected exactly one target-speaker extraction JSONL record in {path}")
    return rows[0]


def score_tse_predictions(
    annotation: dict[str, Any],
    output_dir: Path,
    prediction: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    predicted = {
        str(segment.get("speaker_id", segment.get("target_speaker_id", ""))): segment
        for segment in prediction.get("segments", [])
    }
    segment_scores: list[dict[str, Any]] = []
    for expected in human_segments(annotation):
        speaker_id = str(expected["speaker_id"])
        pred = predicted.get(speaker_id)
        if pred is None:
            segment_scores.append(
                {
                    "speaker_id": speaker_id,
                    "missing_prediction": True,
                    "overlap_s": overlap_s(annotation, expected),
                    "segment_snr_db": float("-inf"),
                    "interferer_reduction_db": float("-inf"),
                    "duration_error_ms": None,
                    "level_error_db": None,
                }
            )
            continue

        estimate_path = run_dir / str(pred["extracted_audio_path"])
        estimate_audio, estimate_rate_hz = read_mono(estimate_path)
        stem_audio, stem_rate_hz = read_mono(fixture_path / expected["stem_path"])
        if estimate_rate_hz != sample_rate_hz or stem_rate_hz != sample_rate_hz:
            raise ValueError(f"{speaker_id} sample rate mismatch")

        reference_audio = segment_samples(stem_audio, expected)
        mixture_audio = segment_samples(mix_audio, expected)
        estimate_aligned, reference_aligned = aligned_pair(estimate_audio, reference_audio)
        _, mixture_aligned = aligned_pair(reference_aligned, mixture_audio)
        residual_same_polarity = estimate_aligned - reference_aligned
        residual_inverted_polarity = -estimate_aligned - reference_aligned
        if rms(residual_inverted_polarity) < rms(residual_same_polarity):
            metric_estimate = -estimate_aligned
            residual = residual_inverted_polarity
            polarity_multiplier = -1
        else:
            metric_estimate = estimate_aligned
            residual = residual_same_polarity
            polarity_multiplier = 1
        interferer = mixture_aligned - reference_aligned
        reference_rms = rms(reference_aligned)
        residual_rms = rms(residual)
        interferer_rms = rms(interferer)
        estimate_dbfs = dbfs(metric_estimate)
        reference_dbfs = dbfs(reference_aligned)
        duration_error_ms = abs(
            (float(estimate_audio.shape[0] - reference_audio.shape[0]) / sample_rate_hz) * 1000.0
        )
        segment_scores.append(
            {
                "speaker_id": speaker_id,
                "missing_prediction": False,
                "extracted_audio_path": str(pred["extracted_audio_path"]),
                "extracted_audio_sha256": pred.get("extracted_audio_sha256"),
                "overlap_s": overlap_s(annotation, expected),
                "input_sir_db": round(ratio_db(reference_rms, interferer_rms), 3),
                "segment_snr_db": round(ratio_db(reference_rms, residual_rms), 3),
                "interferer_reduction_db": round(ratio_db(interferer_rms, residual_rms), 3),
                "polarity_multiplier_for_metrics": polarity_multiplier,
                "target_level_dbfs": round(reference_dbfs, 3),
                "output_level_dbfs": round(estimate_dbfs, 3),
                "level_error_db": round(estimate_dbfs - reference_dbfs, 3),
                "duration_error_ms": round(duration_error_ms, 3),
            }
        )

    present_scores = [score for score in segment_scores if not score["missing_prediction"]]
    overlapped_scores = [score for score in present_scores if float(score["overlap_s"]) > 0.0]
    snr_values = [float(score["segment_snr_db"]) for score in present_scores]
    reduction_values = [float(score["interferer_reduction_db"]) for score in overlapped_scores]
    level_errors = [
        abs(float(score["level_error_db"]))
        for score in present_scores
        if score["level_error_db"] is not None
    ]
    duration_errors = [
        float(score["duration_error_ms"])
        for score in present_scores
        if score["duration_error_ms"] is not None
    ]

    summary = {
        "segment_count": len(segment_scores),
        "prediction_count": len(present_scores),
        "overlapped_segment_count": len(overlapped_scores),
        "min_segment_snr_db": round(min(snr_values), 3) if snr_values else float("-inf"),
        "mean_segment_snr_db": (
            round(sum(snr_values) / len(snr_values), 3) if snr_values else float("-inf")
        ),
        "min_interferer_reduction_db": (
            round(min(reduction_values), 3) if reduction_values else _DB_CAP
        ),
        "mean_interferer_reduction_db": (
            round(sum(reduction_values) / len(reduction_values), 3)
            if reduction_values
            else _DB_CAP
        ),
        "max_abs_level_error_db": round(max(level_errors), 3) if level_errors else float("inf"),
        "max_duration_error_ms": (
            round(max(duration_errors), 3) if duration_errors else float("inf")
        ),
        "all_hashes_present": all(
            bool(score.get("extracted_audio_sha256")) for score in present_scores
        ),
        "polarity_invariant_scoring": True,
        "polarity_inverted_segment_count": sum(
            1 for score in present_scores if int(score.get("polarity_multiplier_for_metrics", 1)) == -1
        ),
    }
    summary["quality_gates"] = tse_quality_gates(summary)
    return {
        "adapter_id": str(prediction.get("adapter_id", "unknown_tse_adapter")),
        "summary": summary,
        "segments": segment_scores,
    }


def tse_quality_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "tse_prediction_segment_count",
            "value": int(summary["prediction_count"]),
            "threshold": f"{summary['segment_count']} extracted speaker clips",
            "passed": int(summary["prediction_count"]) == int(summary["segment_count"]),
        },
        {
            "name": "tse_overlap_covered",
            "value": int(summary["overlapped_segment_count"]),
            "threshold": ">= 1 overlapped target segment",
            "passed": int(summary["overlapped_segment_count"]) >= 1,
        },
        {
            "name": "tse_min_segment_snr_db",
            "value": float(summary["min_segment_snr_db"]),
            "threshold": ">= 60 dB for oracle upper bound",
            "passed": float(summary["min_segment_snr_db"]) >= 60.0,
        },
        {
            "name": "tse_min_interferer_reduction_db",
            "value": float(summary["min_interferer_reduction_db"]),
            "threshold": ">= 60 dB on overlapped target segments",
            "passed": float(summary["min_interferer_reduction_db"]) >= 60.0,
        },
        {
            "name": "tse_output_level_preserved",
            "value": float(summary["max_abs_level_error_db"]),
            "threshold": "<= 0.25 dB absolute target-level error",
            "passed": float(summary["max_abs_level_error_db"]) <= 0.25,
        },
        {
            "name": "tse_duration_preserved",
            "value": float(summary["max_duration_error_ms"]),
            "threshold": "<= 20 ms extracted/reference duration error",
            "passed": float(summary["max_duration_error_ms"]) <= 20.0,
        },
        {
            "name": "tse_extracted_audio_hashed",
            "value": bool(summary["all_hashes_present"]),
            "threshold": "sha256 recorded for every extracted clip",
            "passed": bool(summary["all_hashes_present"]),
        },
        {
            "name": "tse_polarity_invariant_scoring_declared",
            "value": {
                "enabled": bool(summary["polarity_invariant_scoring"]),
                "inverted_segment_count": int(summary["polarity_inverted_segment_count"]),
            },
            "threshold": "global waveform polarity is sign-invariant for TSE metrics",
            "passed": bool(summary["polarity_invariant_scoring"]),
        },
    ]


def build_report(
    annotation: dict[str, Any],
    output_dir: Path,
    prediction: dict[str, Any],
    prediction_path: Path,
) -> dict[str, Any]:
    run_dir = prediction_path.parent
    tse_report = score_tse_predictions(annotation, output_dir, prediction, run_dir)
    fixture_report = analyze_fixture(output_dir, annotation)
    gates = tse_report["summary"]["quality_gates"]
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_oracle_target_speaker_extraction",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
        },
        "benchmarks": {
            "target_speaker_extraction": tse_report,
        },
        "prediction_paths": {
            "target_speaker_extraction": str(prediction_path),
        },
        "fixtures": [fixture_report],
        "adapter": prediction["metadata"],
        "detractor_loop": {
            "strongest_objection": (
                "Oracle stems are an upper bound and passthrough mixtures are only a negative "
                "control. These checks prove the artifact contract, metrics, and downstream "
                "evaluation path before a real target-speaker extraction model is trusted."
            ),
            "cheapest_falsifying_benchmark": (
                "Swap in a real streaming TSE model on the same FLEURS overlap mix and compare "
                "interferer reduction plus Whisper translation token F1 against this oracle report."
            ),
            "fallback_if_falsified": (
                "Bypass separation outside overlap/locked-speaker windows and keep uncertain output "
                "in captions until real TSE improves downstream ASR/translation."
            ),
        },
    }


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
            "fixture_set_id": "self-test-tse",
            "fixture_id": "self_test_tse_overlap",
            "description": "self-test target speaker extraction fixture",
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
                },
            ],
        }
        target_dir = base_fixture_dir(output_dir, annotation)
        (target_dir / "stems").mkdir(parents=True, exist_ok=True)
        sf.write(target_dir / "mix.wav", mix, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(target_dir / "stems" / "speaker_a.wav", stem_a, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(target_dir / "stems" / "speaker_b.wav", stem_b, sample_rate_hz, subtype=PCM_SUBTYPE)
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
        run_dir = output_dir / "runs" / "self-test-tse"
        records = build_oracle_tse_records(annotation, output_dir, run_dir)
        report = score_tse_predictions(annotation, output_dir, records[0], run_dir)
        if not all(bool(gate["passed"]) for gate in report["summary"]["quality_gates"]):
            raise RuntimeError("self-test expected oracle TSE gates to pass")

        inverted_clip = run_dir / "inverted_speaker_a.wav"
        sf.write(
            inverted_clip,
            -stem_a[: int(1.4 * sample_rate_hz)],
            sample_rate_hz,
            subtype=PCM_SUBTYPE,
        )
        inverted_record = {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": "self_test_inverted_oracle",
            "segments": [
                {
                    "speaker_id": "speaker_a",
                    "extracted_audio_path": str(inverted_clip.relative_to(run_dir)),
                    "extracted_audio_sha256": sha256_file(inverted_clip),
                }
            ],
        }
        inverted_report = score_tse_predictions(annotation, output_dir, inverted_record, run_dir)
        inverted_score = next(
            score
            for score in inverted_report["segments"]
            if score["speaker_id"] == "speaker_a"
        )
        if int(inverted_score["polarity_multiplier_for_metrics"]) != -1:
            raise RuntimeError("self-test expected inverted oracle polarity to be detected")
        if float(inverted_score["segment_snr_db"]) < 60.0:
            raise RuntimeError("self-test expected inverted oracle to pass polarity-invariant SNR")

        bad_clip = run_dir / "bad_mix_speaker_a.wav"
        sf.write(
            bad_clip,
            mix[: int(1.4 * sample_rate_hz)],
            sample_rate_hz,
            subtype=PCM_SUBTYPE,
        )
        bad_record = {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": "self_test_bad_mixture",
            "segments": [
                {
                    "speaker_id": "speaker_a",
                    "extracted_audio_path": str(bad_clip.relative_to(run_dir)),
                    "extracted_audio_sha256": sha256_file(bad_clip),
                }
            ],
        }
        bad_report = score_tse_predictions(annotation, output_dir, bad_record, run_dir)
        if float(bad_report["summary"]["min_segment_snr_db"]) >= 60.0:
            raise RuntimeError("self-test expected mixed-audio prediction to fail SNR gate")
        return {
            "oracle_summary": report["summary"],
            "bad_mixture_summary": bad_report["summary"],
        }


def passthrough_failed_as_expected(report: dict[str, Any]) -> bool:
    failed_gate_names = {
        str(gate["name"])
        for gate in report["summary"]["quality_gates"]
        if not bool(gate["passed"])
    }
    required_failures = {
        "tse_min_segment_snr_db",
        "tse_min_interferer_reduction_db",
    }
    passed_gate_names = {
        str(gate["name"])
        for gate in report["summary"]["quality_gates"]
        if bool(gate["passed"])
    }
    required_successes = {
        "tse_prediction_segment_count",
        "tse_overlap_covered",
        "tse_duration_preserved",
        "tse_extracted_audio_hashed",
    }
    return required_failures.issubset(failed_gate_names) and required_successes.issubset(
        passed_gate_names
    )


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    tse_summary = report["benchmarks"]["target_speaker_extraction"]["summary"]
    print(f"target-speaker extraction {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  tse diagnostics: "
        f"mean_snr_db={tse_summary['mean_segment_snr_db']} "
        f"min_interferer_reduction_db={tse_summary['min_interferer_reduction_db']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark target-speaker extraction fixtures")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["check", "passthrough-check", "score"],
        default="check",
    )
    parser.add_argument("--self-test", action="store_true", help="validate TSE scorer contract only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-stream-mb", type=int, default=64)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        report = self_test()
        print("target-speaker extraction contract self-test PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    output_dir = args.output_dir.resolve()
    annotation = prepare_multilingual_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        max_stream_mb=args.max_stream_mb,
    )
    if args.command == "check":
        run_id = args.run_id or DEFAULT_RUN_ID
        run_dir = output_dir / "runs" / run_id
        prediction_path = run_dir / "oracle_tse_predictions.jsonl"
        records = build_oracle_tse_records(
            annotation,
            output_dir,
            run_dir,
            adapter_id=args.adapter_id,
        )
        write_jsonl(records, prediction_path)
        prediction = records[0]
    elif args.command == "passthrough-check":
        run_id = args.run_id or DEFAULT_PASSTHROUGH_RUN_ID
        run_dir = output_dir / "runs" / run_id
        prediction_path = run_dir / "passthrough_tse_predictions.jsonl"
        adapter_id = (
            DEFAULT_PASSTHROUGH_ADAPTER_ID
            if args.adapter_id == DEFAULT_ADAPTER_ID
            else args.adapter_id
        )
        records = build_passthrough_tse_records(
            annotation,
            output_dir,
            run_dir,
            adapter_id=adapter_id,
        )
        write_jsonl(records, prediction_path)
        prediction = records[0]
    else:
        if args.predictions is None:
            raise SystemExit("score requires --predictions pointing to TSE JSONL")
        prediction_path = args.predictions.resolve()
        run_id = args.run_id or DEFAULT_SCORE_RUN_ID
        run_dir = prediction_path.parent
        prediction = read_prediction_record(prediction_path)

    report = build_report(annotation, output_dir, prediction, prediction_path)
    report_name = "tse-score-report.json" if args.command == "score" else "tse-fixture-report.json"
    report_path = args.report.resolve() if args.report else run_dir / report_name
    write_report(report, report_path)
    print(f"wrote target-speaker extraction predictions to {prediction_path}")
    print(f"wrote target-speaker extraction report to {report_path}")
    print_summary(report)
    if args.command == "passthrough-check":
        if passthrough_failed_as_expected(report):
            print("passthrough target-speaker extraction failed expected quality gates")
            return 0
        print("passthrough target-speaker extraction did not fail the expected gates")
        return 1
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
