#!/usr/bin/env python3
"""Benchmark volume-matched playback and honest source-suppression metadata.

This is not a true room-cancellation implementation. It creates a repeatable
fixture that measures the first conservative product behavior: translated
playback at the source speaker's measured level, source residual ducking while
playback is active, clipping safety, and explicit "not true cancellation"
diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    PCM_SUBTYPE,
    apply_fade,
    dbfs,
    db_to_linear,
    linear_to_db,
    rms,
    scale_to_level,
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


DEFAULT_RUN_ID = "fleurs-playback-ducking-suppression"
DEFAULT_ADAPTER_ID = "ducking_masking_playback_suppression_v1"
DEFAULT_SOURCE_ATTENUATION_DB = -10.0
DEFAULT_MAX_LEVEL_ERROR_DB = 0.25
DEFAULT_MIN_SUPPRESSION_DB = 6.0
DEFAULT_MIN_TRANSLATED_TO_RESIDUAL_DB = 6.0
DEFAULT_MAX_PEAK_DBFS = -0.1
CLAIM_KIND = "ducking_masking_simulation_not_true_cancellation"
_EPS = 1.0e-10
_DB_CAP = 120.0


def stable_seed(*parts: object) -> int:
    material = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate_hz = sf.read(path, dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    return np.asarray(audio, dtype=np.float32), int(sample_rate_hz)


def segment_samples(audio: np.ndarray, segment: dict[str, Any]) -> np.ndarray:
    return np.asarray(
        audio[int(segment["start_sample"]) : int(segment["end_sample"])],
        dtype=np.float32,
    )


def human_segments(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        segment
        for segment in sorted(annotation["segments"], key=lambda item: float(item["start_s"]))
        if segment.get("source_kind") == "human"
    ]


def ratio_db(numerator: float, denominator: float) -> float:
    if denominator <= _EPS:
        return _DB_CAP if numerator > _EPS else 0.0
    return min(_DB_CAP, linear_to_db(max(numerator, _EPS) / denominator))


def translated_surrogate(
    source_audio: np.ndarray,
    sample_rate_hz: int,
    segment: dict[str, Any],
) -> np.ndarray:
    """Create a deterministic speech-shaped playback surrogate.

    This stands in for same-voice TTS until a provider/model exists. It follows
    the source envelope and level so the playback/suppression scorer can be
    exercised without claiming voice similarity.
    """

    frame_count = int(source_audio.size)
    if frame_count <= 0:
        return np.zeros((0,), dtype=np.float32)

    speaker_id = str(segment["speaker_id"])
    seed = stable_seed("translated_surrogate", speaker_id, segment["start_s"], segment["end_s"])
    rng = np.random.default_rng(seed)
    t = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    base_hz = 155.0 + float(seed % 140)
    phase = float(rng.uniform(0.0, 2.0 * math.pi))

    carrier = np.sin(2.0 * math.pi * base_hz * t + phase)
    carrier += 0.35 * np.sin(2.0 * math.pi * base_hz * 2.01 * t + phase * 0.37)
    carrier += 0.14 * np.sin(2.0 * math.pi * base_hz * 3.07 * t + phase * 0.17)

    envelope = np.abs(source_audio.astype(np.float64))
    smoothing = max(1, int(round(sample_rate_hz * 0.025)))
    kernel = np.ones(smoothing, dtype=np.float64) / float(smoothing)
    envelope = np.convolve(envelope, kernel, mode="same")
    if float(np.max(envelope)) > 0.0:
        envelope = envelope / float(np.max(envelope))
    envelope = 0.18 + 0.82 * envelope

    translated = (carrier * envelope).astype(np.float32)
    translated = apply_fade(translated, sample_rate_hz)
    return scale_to_level(translated, dbfs(source_audio)).astype(np.float32)


def build_playback_record(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str,
    source_attenuation_db: float,
) -> dict[str, Any]:
    base_dir = fixture_dir(output_dir, annotation["fixture_set_id"], annotation["fixture_id"])
    source_mix, sample_rate_hz = read_mono(base_dir / annotation["mix_path"])
    expected_rate_hz = int(annotation["sample_rate_hz"])
    if sample_rate_hz != expected_rate_hz:
        raise ValueError(f"expected {expected_rate_hz} Hz source mix, got {sample_rate_hz}")

    frame_count = int(source_mix.shape[0])
    source_reference = np.zeros(frame_count, dtype=np.float32)
    translated_playback = np.zeros(frame_count, dtype=np.float32)
    segment_records: list[dict[str, Any]] = []

    for segment in human_segments(annotation):
        stem_audio, stem_rate_hz = read_mono(base_dir / segment["stem_path"])
        if stem_rate_hz != sample_rate_hz:
            raise ValueError(f"{segment['stem_path']} sample rate mismatch")

        start_sample = int(segment["start_sample"])
        end_sample = int(segment["end_sample"])
        source_window = segment_samples(stem_audio, segment)
        playback_window = translated_surrogate(source_window, sample_rate_hz, segment)
        source_reference[start_sample:end_sample] += source_window
        translated_playback[start_sample:end_sample] += playback_window

        input_level_dbfs = dbfs(source_window)
        playback_level_dbfs = dbfs(playback_window)
        segment_records.append(
            {
                "speaker_id": segment["speaker_id"],
                "source_language_code": segment["language_code"],
                "target_language_code": "en",
                "start_s": float(segment["start_s"]),
                "end_s": float(segment["end_s"]),
                "start_sample": start_sample,
                "end_sample": end_sample,
                "input_level_dbfs": round(input_level_dbfs, 3),
                "target_output_level_dbfs": round(input_level_dbfs, 3),
                "translated_playback_level_dbfs": round(playback_level_dbfs, 3),
                "output_level_error_db": round(abs(playback_level_dbfs - input_level_dbfs), 3),
                "source_text": segment.get("text"),
                "translated_text": segment.get("english_reference_text"),
                "voice_clone_status": "surrogate_not_same_voice",
            }
        )

    residual_source = source_reference * db_to_linear(source_attenuation_db)
    rendered_mix = translated_playback + residual_source

    run_dir.mkdir(parents=True, exist_ok=True)
    source_path = run_dir / "source_reference.wav"
    translated_path = run_dir / "translated_playback_surrogate.wav"
    residual_path = run_dir / "ducked_source_residual.wav"
    rendered_path = run_dir / "rendered_translated_overlay.wav"
    sf.write(source_path, source_reference, sample_rate_hz, subtype=PCM_SUBTYPE)
    sf.write(translated_path, translated_playback, sample_rate_hz, subtype=PCM_SUBTYPE)
    sf.write(residual_path, residual_source, sample_rate_hz, subtype=PCM_SUBTYPE)
    sf.write(rendered_path, rendered_mix, sample_rate_hz, subtype=PCM_SUBTYPE)

    for record in segment_records:
        start_sample = int(record["start_sample"])
        end_sample = int(record["end_sample"])
        source_window = source_reference[start_sample:end_sample]
        residual_window = residual_source[start_sample:end_sample]
        translated_window = translated_playback[start_sample:end_sample]
        rendered_window = rendered_mix[start_sample:end_sample]
        source_level = dbfs(source_window)
        residual_level = dbfs(residual_window)
        translated_level = dbfs(translated_window)
        record.update(
            {
                "rendered_mix_level_dbfs": round(dbfs(rendered_window), 3),
                "source_residual_level_dbfs": round(residual_level, 3),
                "original_voice_suppression_db": round(source_level - residual_level, 3),
                "translated_to_source_residual_db": round(translated_level - residual_level, 3),
                "playback_latency_ms": 0.0,
            }
        )

    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": adapter_id,
        "claim_kind": CLAIM_KIND,
        "sample_rate_hz": sample_rate_hz,
        "source_attenuation_db": source_attenuation_db,
        "audio_paths": {
            "source_reference": str(source_path.relative_to(run_dir)),
            "translated_playback": str(translated_path.relative_to(run_dir)),
            "source_residual": str(residual_path.relative_to(run_dir)),
            "rendered_mix": str(rendered_path.relative_to(run_dir)),
        },
        "audio_hashes": {
            "source_reference": sha256_file(source_path),
            "translated_playback": sha256_file(translated_path),
            "source_residual": sha256_file(residual_path),
            "rendered_mix": sha256_file(rendered_path),
        },
        "segments": segment_records,
        "model_layer_latency_ms": {
            "voice_clone_or_tts": None,
            "echo_or_suppression": 0.0,
        },
        "metadata": {
            "kind": "playback_ducking_masking_fixture",
            "translated_audio_is_surrogate": True,
            "true_room_cancellation": False,
            "fallback_behavior": "translated overlay plus honest suppression diagnostics",
        },
    }


def summarize_playback_record(record: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    rendered_mix, sample_rate_hz = read_mono(run_dir / record["audio_paths"]["rendered_mix"])
    translated, translated_rate_hz = read_mono(run_dir / record["audio_paths"]["translated_playback"])
    residual, residual_rate_hz = read_mono(run_dir / record["audio_paths"]["source_residual"])
    if translated_rate_hz != sample_rate_hz or residual_rate_hz != sample_rate_hz:
        raise ValueError("playback artifact sample-rate mismatch")

    segments = record["segments"]
    max_level_error = max(float(item["output_level_error_db"]) for item in segments)
    min_suppression = min(float(item["original_voice_suppression_db"]) for item in segments)
    mean_suppression = sum(float(item["original_voice_suppression_db"]) for item in segments) / len(segments)
    min_translated_to_residual = min(
        float(item["translated_to_source_residual_db"]) for item in segments
    )
    rendered_peak_dbfs = linear_to_db(float(np.max(np.abs(rendered_mix)))) if rendered_mix.size else float("-inf")
    clipped_samples = int(np.sum(np.abs(rendered_mix) >= 1.0))
    full_mix_translated_to_residual = ratio_db(rms(translated), rms(residual))
    all_hashes_present = all(bool(value) for value in record["audio_hashes"].values())

    summary = {
        "segment_count": len(segments),
        "claim_kind": record["claim_kind"],
        "max_output_level_error_db": round(max_level_error, 3),
        "min_original_voice_suppression_db": round(min_suppression, 3),
        "mean_original_voice_suppression_db": round(mean_suppression, 3),
        "min_translated_to_source_residual_db": round(min_translated_to_residual, 3),
        "full_mix_translated_to_source_residual_db": round(full_mix_translated_to_residual, 3),
        "rendered_peak_dbfs": round(rendered_peak_dbfs, 3),
        "clipped_sample_count": clipped_samples,
        "all_hashes_present": all_hashes_present,
    }
    summary["quality_gates"] = playback_quality_gates(summary)
    return summary


def playback_quality_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "playback_segment_count",
            "value": int(summary["segment_count"]),
            "threshold": ">= 4 translated playback segments",
            "passed": int(summary["segment_count"]) >= 4,
        },
        {
            "name": "playback_output_level_matched",
            "value": float(summary["max_output_level_error_db"]),
            "threshold": f"<= {DEFAULT_MAX_LEVEL_ERROR_DB} dB max source/playback level error",
            "passed": float(summary["max_output_level_error_db"]) <= DEFAULT_MAX_LEVEL_ERROR_DB,
        },
        {
            "name": "source_residual_ducked",
            "value": float(summary["min_original_voice_suppression_db"]),
            "threshold": f">= {DEFAULT_MIN_SUPPRESSION_DB} dB measured source residual reduction",
            "passed": float(summary["min_original_voice_suppression_db"]) >= DEFAULT_MIN_SUPPRESSION_DB,
        },
        {
            "name": "translated_audio_dominates_residual",
            "value": float(summary["min_translated_to_source_residual_db"]),
            "threshold": f">= {DEFAULT_MIN_TRANSLATED_TO_RESIDUAL_DB} dB translated/residual ratio",
            "passed": (
                float(summary["min_translated_to_source_residual_db"])
                >= DEFAULT_MIN_TRANSLATED_TO_RESIDUAL_DB
            ),
        },
        {
            "name": "rendered_mix_not_clipped",
            "value": int(summary["clipped_sample_count"]),
            "threshold": "0 samples at or above full scale",
            "passed": int(summary["clipped_sample_count"]) == 0,
        },
        {
            "name": "rendered_peak_headroom",
            "value": float(summary["rendered_peak_dbfs"]),
            "threshold": f"<= {DEFAULT_MAX_PEAK_DBFS} dBFS peak",
            "passed": float(summary["rendered_peak_dbfs"]) <= DEFAULT_MAX_PEAK_DBFS,
        },
        {
            "name": "suppression_claim_is_honest",
            "value": summary["claim_kind"],
            "threshold": CLAIM_KIND,
            "passed": summary["claim_kind"] == CLAIM_KIND,
        },
        {
            "name": "playback_artifacts_hashed",
            "value": bool(summary["all_hashes_present"]),
            "threshold": "sha256 recorded for every playback/suppression artifact",
            "passed": bool(summary["all_hashes_present"]),
        },
    ]


def build_report(record: dict[str, Any], run_dir: Path, output_dir: Path) -> dict[str, Any]:
    playback_summary = summarize_playback_record(record, run_dir)
    gates = playback_summary["quality_gates"]
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_playback_suppression",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
        },
        "benchmarks": {
            "playback_suppression": {
                "adapter_id": record["adapter_id"],
                "summary": playback_summary,
                "segments": record["segments"],
            }
        },
        "prediction_paths": {
            "playback_suppression": str(run_dir / "playback_suppression_predictions.jsonl"),
        },
        "artifact_paths": record["audio_paths"],
        "artifact_hashes": record["audio_hashes"],
        "detractor_loop": {
            "strongest_objection": (
                "This benchmark proves gain staging and honest diagnostics only. It does not prove "
                "that a phone or speaker can cancel a live human voice at the listener position."
            ),
            "cheapest_falsifying_benchmark": (
                "Play a known source voice and translated playback through the target device in a "
                "real room, record at the listener position, and measure residual source audibility "
                "plus translated-speech distortion."
            ),
            "fallback_if_falsified": (
                "Use translated overlay, captions, headphones or earpiece mode, and visible "
                "suppression-unavailable diagnostics."
            ),
        },
    }


def self_test() -> dict[str, Any]:
    passing_summary = {
        "segment_count": 4,
        "claim_kind": CLAIM_KIND,
        "max_output_level_error_db": 0.0,
        "min_original_voice_suppression_db": 10.0,
        "min_translated_to_source_residual_db": 10.0,
        "rendered_peak_dbfs": -6.0,
        "clipped_sample_count": 0,
        "all_hashes_present": True,
    }
    failing_summary = {
        **passing_summary,
        "min_original_voice_suppression_db": 0.0,
        "min_translated_to_source_residual_db": 0.0,
    }
    passing_gates = playback_quality_gates(passing_summary)
    failing_gates = playback_quality_gates(failing_summary)
    if not all(bool(gate["passed"]) for gate in passing_gates):
        raise RuntimeError("self-test expected conservative playback summary to pass")
    failed_gate_names = {str(gate["name"]) for gate in failing_gates if not bool(gate["passed"])}
    expected_failures = {"source_residual_ducked", "translated_audio_dominates_residual"}
    if not expected_failures.issubset(failed_gate_names):
        raise RuntimeError("self-test expected unducked source residual to fail")
    return {
        "passing_gate_count": len(passing_gates),
        "failing_gate_names": sorted(failed_gate_names),
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    playback = report["benchmarks"]["playback_suppression"]["summary"]
    print(f"playback suppression {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  playback diagnostics: "
        f"min_suppression_db={playback['min_original_voice_suppression_db']} "
        f"max_level_error_db={playback['max_output_level_error_db']} "
        f"peak_dbfs={playback['rendered_peak_dbfs']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark playback/suppression fixture")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["check"],
        default="check",
    )
    parser.add_argument("--self-test", action="store_true", help="validate scorer gates only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-stream-mb", type=int, default=64)
    parser.add_argument("--source-attenuation-db", type=float, default=DEFAULT_SOURCE_ATTENUATION_DB)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        report = self_test()
        print("playback suppression contract self-test PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    output_dir = args.output_dir.resolve()
    annotation = prepare_multilingual_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        max_stream_mb=args.max_stream_mb,
    )
    run_dir = output_dir / "runs" / args.run_id
    record = build_playback_record(
        annotation,
        output_dir,
        run_dir,
        adapter_id=args.adapter_id,
        source_attenuation_db=args.source_attenuation_db,
    )
    prediction_path = run_dir / "playback_suppression_predictions.jsonl"
    write_jsonl([record], prediction_path)
    report = build_report(record, run_dir, output_dir)
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "playback-suppression-report.json"
    )
    write_report(report, report_path)
    print(f"wrote playback suppression predictions to {prediction_path}")
    print(f"wrote playback suppression report to {report_path}")
    print_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
